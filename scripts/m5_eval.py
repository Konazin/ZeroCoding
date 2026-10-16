"""M5: avaliação do fluxo integrado do agente contra um llama-server local.

Roda 7 casos x N repetições em workspaces temporários, com aprovação programática, e registra por tentativa:
conclusão objetiva da tarefa, validade das chamadas de ferramenta, tokens de entrada/saída (usage do servidor),
tempo de processamento do prompt (proxy de TTFT; o provider não faz streaming), tokens/s de geração (timings do
llama.cpp), duração total e RAM/VRAM de pico. Agrega mediana e pior caso.

Uso: uv run python scripts/m5_eval.py --label ornith-1.5-9b-q5_k_m [--repetitions 3] [--streaming] [--extensions] [--output docs/m5-<label>-results.json]
--extensions liga, sem uso previsto, um servidor MCP de teste (2 ferramentas) e o subagente explore, para medir o custo ocioso (M6).
Não baixa nem troca modelos: mede o que estiver servido em --base-url.
"""
from __future__ import annotations

import argparse
import glob
import sys
import json
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.subagent import make_explorer_tool
from zerocoding.mcp.manager import McpManager
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.llama_cpp import LlamaCppProvider

CALC_BUGGY = "def soma(a, b):\n    return a + b\n\n\ndef dobro(x):\n    return x * 3\n"
CALC_FIXED = CALC_BUGGY.replace("x * 3", "x * 2")
TEST_CALC = (
    "import unittest\nfrom calc import soma, dobro\n\n\nclass T(unittest.TestCase):\n"
    "    def test_soma(self):\n        self.assertEqual(soma(1, 2), 3)\n\n"
    "    def test_dobro(self):\n        self.assertEqual(dobro(2), 4)\n\n\nif __name__ == '__main__':\n    unittest.main()\n"
)


def _read(root: Path, name: str) -> str:
    path = root / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


# Cada caso: id, prompt, calc inicial, aprovar?, plan?, verificação(ctx) -> bool
CASES = [
    dict(id="direct", prompt="Responda em uma frase: o que é uma função pura?", calc=CALC_BUGGY, approve=False, plan=False,
         check=lambda c: bool(c["answer"].strip()) and not c["tools_called"]),
    dict(id="read", prompt="Leia calc.py e diga o que a função soma retorna.", calc=CALC_BUGGY, approve=False, plan=False,
         check=lambda c: "read_file" in c["tools_completed"] and any(w in c["answer"].lower() for w in ("a + b", "soma", "adi"))),
    dict(id="search", prompt="Procure em quais arquivos aparece a palavra dobro.", calc=CALC_BUGGY, approve=False, plan=False,
         check=lambda c: "search_files" in c["tools_completed"] and "calc.py" in c["answer"] and "test_calc.py" in c["answer"]),
    dict(id="edit_approved", prompt="Em calc.py a função dobro multiplica por 3 em vez de 2. Corrija com uma edição mínima.",
         calc=CALC_BUGGY, approve=True, plan=False,
         check=lambda c: _read(c["root"], "calc.py") == CALC_FIXED),
    dict(id="write_refused", prompt="Crie o arquivo novo.py com print('oi').", calc=CALC_BUGGY, approve=False, plan=False,
         check=lambda c: not (c["root"] / "novo.py").exists() and c["approvals"] >= 1),
    dict(id="plan_blocks_write", prompt="Crie o arquivo novo.py com print('oi').", calc=CALC_BUGGY, approve=True, plan=True,
         check=lambda c: not (c["root"] / "novo.py").exists() and c["approvals"] == 0 and _read(c["root"], "calc.py") == CALC_BUGGY),
    dict(id="command_approved", prompt="Rode os testes com python3 -m unittest e diga se passaram.", calc=CALC_FIXED, approve=True, plan=False,
         check=lambda c: any(x.startswith("exit 0") for x in c["command_summaries"]) and bool(c["answer"].strip())),
]


class RecordingProvider(LlamaCppProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.responses: list[dict] = []

    def _post(self, endpoint, payload):
        response = super()._post(endpoint, payload)
        if endpoint.endswith("chat/completions"):
            self.responses.append(response)
        return response


def _server_pid() -> int | None:
    out = subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def _rss_mb(pid) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def _vram_mb() -> float:
    best = 0.0
    for path in glob.glob("/sys/class/drm/card*/device/mem_info_vram_used"):
        try:
            best = max(best, int(Path(path).read_text()) / 2**20)
        except (OSError, ValueError):
            continue
    return best


class MemorySampler:
    def __init__(self, pid):
        self.pid, self.peak_rss, self.peak_vram, self._stop = pid, 0.0, 0.0, threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            self.peak_rss = max(self.peak_rss, _rss_mb(self.pid))
            self.peak_vram = max(self.peak_vram, _vram_mb())
            self._stop.wait(0.25)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


EXTENSION_TOOLS: list = []  # filled by --extensions (shared MCP server across trials)
USE_EXPLORER = False


def run_trial(case, base_url, model, pid, timeout, streaming=False):
    root = Path(tempfile.mkdtemp(prefix=f"zc_m5_{case['id']}_"))
    (root / "calc.py").write_text(case["calc"], encoding="utf-8")
    (root / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
    approvals = []

    def approve(action, preview):
        approvals.append(action)
        return case["approve"]

    provider = RecordingProvider("", base_url, model, timeout=timeout)
    registry = ToolRegistry(root, approve=approve)
    for tool in EXTENSION_TOOLS:
        registry.register_external(tool)
    agent = Agent(provider, tools=registry, plan_mode=case["plan"], streaming_enabled=streaming)
    if USE_EXPLORER:
        registry.register_external(make_explorer_tool(agent))
    events = []
    error = None
    answer = ""
    started = time.monotonic()
    with MemorySampler(pid) as memory:
        try:
            answer = agent.ask(case["prompt"], use_tools=True, on_event=events.append)
        except Exception as exc:  # a provider failure is a result, not a crash
            error = str(exc)[:200]
    duration = time.monotonic() - started

    completed = [e.tool_name for e in events if e.kind == "tool_completed"]
    errors = [e for e in events if e.kind == "tool_error"]
    started_calls = [e for e in events if e.kind == "tool_started"]
    usage = [r.get("usage", {}) for r in provider.responses]
    timings = [r.get("timings", {}) for r in provider.responses]
    gen_rates = [t["predicted_per_second"] for t in timings if t.get("predicted_per_second")]
    summaries = [e.summary for e in events if e.kind == "tool_completed" and e.tool_name == "run_command"]
    ctx = dict(root=root, answer=answer, approvals=len(approvals), tools_called={e.tool_name for e in started_calls},
               tools_completed=set(completed), command_summaries=summaries)
    try:
        passed = bool(case["check"](ctx)) and error is None
    except Exception:
        passed = False
    return dict(
        case=case["id"], passed=passed, error=error, duration_s=round(duration, 2),
        llm_calls=agent.last_turn.get("llm_calls", len(provider.responses)),
        prompt_tokens=agent.last_turn.get("prompt_tokens", sum(u.get("prompt_tokens", 0) for u in usage)),
        completion_tokens=agent.last_turn.get("completion_tokens", sum(u.get("completion_tokens", 0) for u in usage)),
        first_prompt_ms=round(timings[0].get("prompt_ms", 0), 1) if timings else None,
        ttft_ms=agent.last_turn.get("ttft_ms"),
        gen_tokens_per_s=round(statistics.mean(gen_rates), 2) if gen_rates else None,
        tool_calls=len(started_calls), tool_rounds=agent.last_turn.get("tool_rounds", 0),
        tool_errors=len(errors), approvals=len(approvals),
        peak_rss_mb=round(memory.peak_rss), peak_vram_mb=round(memory.peak_vram),
    )


def _med_worst(values, worst=max):
    values = [v for v in values if v is not None]
    return (round(statistics.median(values), 2), round(worst(values), 2)) if values else (None, None)


def summarize(trials):
    per_case = {}
    for case in CASES:
        rows = [t for t in trials if t["case"] == case["id"]]
        if not rows:
            continue
        per_case[case["id"]] = dict(
            passed=f"{sum(r['passed'] for r in rows)}/{len(rows)}",
            duration_s=dict(zip(("median", "worst"), _med_worst([r["duration_s"] for r in rows]))),
            prompt_tokens=dict(zip(("median", "worst"), _med_worst([r["prompt_tokens"] for r in rows]))),
            completion_tokens=dict(zip(("median", "worst"), _med_worst([r["completion_tokens"] for r in rows]))),
            first_prompt_ms=dict(zip(("median", "worst"), _med_worst([r["first_prompt_ms"] for r in rows]))),
            ttft_ms=dict(zip(("median", "worst"), _med_worst([r.get("ttft_ms") for r in rows]))),
            gen_tokens_per_s=dict(zip(("median", "worst"), _med_worst([r["gen_tokens_per_s"] for r in rows], worst=min))),
            tool_errors_total=sum(r["tool_errors"] for r in rows),
        )
    return dict(
        per_case=per_case,
        overall_passed=f"{sum(t['passed'] for t in trials)}/{len(trials)}",
        tool_calls=sum(t["tool_calls"] for t in trials),
        tool_rounds=sum(t["tool_rounds"] for t in trials),
        tool_errors=sum(t["tool_errors"] for t in trials),
        peak_rss_mb=max((t["peak_rss_mb"] for t in trials), default=0),
        peak_vram_mb=max((t["peak_vram_mb"] for t in trials), default=0),
    )


def server_info(base_url):
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    info = {}
    try:
        with urllib.request.urlopen(root + "/props", timeout=10) as r:
            props = json.loads(r.read())
        info = {
            "model_path": props.get("model_alias") or props.get("model_path"),
            "n_ctx": (props.get("default_generation_settings") or {}).get("n_ctx"),
            "total_slots": props.get("total_slots"),
            "build_info": props.get("build_info"),
            "supports_tools": (props.get("chat_template_caps") or {}).get("supports_tools"),
        }
    except Exception as exc:
        info["error"] = str(exc)
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="identificador do modelo/configuração medido")
    parser.add_argument("--model", default="ornith-1.5-9b-q5-k-m")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--streaming", action="store_true", help="opt in to SSE and record measured TTFT")
    parser.add_argument("--extensions", action="store_true", help="liga MCP de teste + explore (custo ocioso)")
    args = parser.parse_args(argv)
    global USE_EXPLORER
    manager = None
    if args.extensions:
        fake = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "fake_mcp_server.py"
        manager = McpManager({"servers": {"fake": {"command": [sys.executable, str(fake)],
                                                   "tools": {"echo": {"read_only": True}, "add": {}}}}}, Path.cwd())
        EXTENSION_TOOLS.extend(manager.start_all())
        USE_EXPLORER = True
        print("extensões:", [t.name for t in EXTENSION_TOOLS] + ["explore"], {n: s.status for n, s in manager.states.items()})
    pid = _server_pid()
    idle = dict(rss_mb=round(_rss_mb(pid)), vram_mb=round(_vram_mb()))
    trials = []
    for repetition in range(1, args.repetitions + 1):
        for case in CASES:
            trial = run_trial(case, args.base_url, args.model, pid, args.timeout, streaming=args.streaming)
            trial["repetition"] = repetition
            trials.append(trial)
            print(f"[{repetition}/{args.repetitions}] {case['id']:18} {'PASS' if trial['passed'] else 'FAIL'} "
                  f"{trial['duration_s']:6.1f}s  in={trial['prompt_tokens']:5} out={trial['completion_tokens']:4} "
                  f"ttft={trial['ttft_ms']}ms gen={trial['gen_tokens_per_s']} tok/s  tool_err={trial['tool_errors']}"
                  + (f"  ERROR {trial['error']}" if trial["error"] else ""), flush=True)
    if manager:
        manager.close()
    report = dict(label=args.label, date=time.strftime("%Y-%m-%d"), server=server_info(args.base_url),
                  streaming=args.streaming,
                  extensions=([t.name for t in EXTENSION_TOOLS] + ["explore"]) if args.extensions else None,
                  idle_memory=idle, repetitions=args.repetitions, summary=summarize(trials), trials=trials)
    output = args.output or Path("docs") / f"m5-{args.label}-results.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    print("salvo em", output)


if __name__ == "__main__":
    main()
