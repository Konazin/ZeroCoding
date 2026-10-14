#!/usr/bin/env python3
"""Small, local-only comparison of system prompt, effort budgets, and Plan mode.

Every trial uses a disposable synthetic workspace. File writes and commands are
always denied; the Plan guard is also checked directly without launching a
subprocess. The script never downloads a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import re
import statistics
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from zerocoding.core.agent import Agent
from zerocoding.core.project_context import ProjectContext
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import normalize_turn
from zerocoding.providers.ollama import OllamaProvider


DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_REPETITIONS = 2
MAX_INPUT_TOKENS = 4096
BASE_MAX_OUTPUT_TOKENS = 1024
BASE_MAX_TOOL_ROUNDS = 6
TEMPERATURE = 0.2
SEED_BASE = 31415
CONTEXT_MARKER = "Project context explicitly added by the user:"

CURRENT_PROMPT = (
    "You are ZeroCoding, a concise coding assistant. Use project tools to inspect files. "
    "Propose changes clearly; file writes and commands require user approval."
)

REFORMULATED_PROMPT = (
    "You are ZeroCoding, a coding agent. Verify project facts from context or read tools. "
    "Use native tool calls; never show raw tool JSON as an answer. Get approval before writes or commands; "
    "claim success only after tool confirmation. Follow the requested format concisely."
)

EFFORT_PROFILES = {
    "low": {"max_output_tokens": 512, "max_tool_rounds": 3},
    "medium": {"max_output_tokens": 1024, "max_tool_rounds": 6},
    "high": {"max_output_tokens": 2048, "max_tool_rounds": 8},
}

CORE_SCENARIOS = ("project_fact", "symbol_read")


def build_matrix(repetitions: int = DEFAULT_REPETITIONS) -> list[dict[str, Any]]:
    """Compare prompts at Low, then vary effort only under the new prompt."""
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    core_conditions = (
        ("current", "low", False),
        ("reframed", "low", False),
        ("reframed", "medium", False),
        ("reframed", "high", False),
        # Medium + Ultrathink has the same 2,048/8 caps as High.
        ("reframed", "medium", True),
    )
    rows = []
    for scenario in CORE_SCENARIOS:
        for prompt_variant, effort, ultrathink in core_conditions:
            for repetition in range(1, repetitions + 1):
                rows.append({
                    "scenario": scenario,
                    "prompt_variant": prompt_variant,
                    "effort": effort,
                    "ultrathink": ultrathink,
                    "plan_mode": False,
                    "repetition": repetition,
                })
    for plan_mode in (False, True):
        for repetition in range(1, repetitions + 1):
            rows.append({
                "scenario": "plan_edit",
                "prompt_variant": "reframed",
                "effort": "low",
                "ultrathink": False,
                "plan_mode": plan_mode,
                "repetition": repetition,
            })
    return rows


class RecordingProvider:
    """Keep provider options and normalized tool calls for each trial."""

    def __init__(self, provider: OllamaProvider, repetition: int):
        self.provider = provider
        self.seed = SEED_BASE + repetition
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, **kwargs):
        options = dict(kwargs.get("options") or {})
        options.update({"temperature": TEMPERATURE, "seed": self.seed})
        kwargs["options"] = options
        started = time.perf_counter()
        try:
            response = self.provider.chat(messages=messages, **kwargs)
        except Exception as exc:
            self.calls.append({
                "messages": messages,
                "tools": kwargs.get("tools"),
                "max_tokens": kwargs.get("max_tokens"),
                "num_ctx": kwargs.get("num_ctx"),
                "options": options,
                "wall_seconds": time.perf_counter() - started,
                "error": f"{type(exc).__name__}: {exc}",
            })
            raise
        elapsed = time.perf_counter() - started
        turn = normalize_turn(response)
        self.calls.append({
            "messages": messages,
            "tools": kwargs.get("tools"),
            "max_tokens": kwargs.get("max_tokens"),
            "num_ctx": kwargs.get("num_ctx"),
            "options": options,
            "response": turn.content,
            "tool_calls": [
                {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                for call in turn.tool_calls
            ],
            "provider_usage": turn.usage,
            "wall_seconds": elapsed,
        })
        return turn

    def tool_result_message(self, call_id: str, name: str, content: str) -> dict:
        return self.provider.tool_result_message(call_id, name, content)

    def native_effort_kwargs(self, level: str):
        return self.provider.native_effort_kwargs(level)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False) + "\n")
        stream.flush()


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _make_fixture(root: Path) -> None:
    (root / "tax_config.py").write_text("TAX_RATE = 0.08\n", encoding="utf-8")
    source = root / "src"
    source.mkdir()
    (source / "calculations.py").write_text(
        'def format_total(items):\n'
        '    """Return the sum of item prices formatted as dollars."""\n'
        '    return f"${sum(item[\'price\'] for item in items):.2f}"\n',
        encoding="utf-8",
    )
    (source / "settings.py").write_text("TIMEOUT_SECONDS = 10\n", encoding="utf-8")
    (root / "README.md").write_text("# Prompt control fixture\n", encoding="utf-8")


def _system_prompt(variant: str, scenario: str, workspace: Path) -> str | None:
    base = CURRENT_PROMPT if variant == "current" else REFORMULATED_PROMPT
    if scenario != "project_fact":
        return None if variant == "current" else base

    context = ProjectContext(workspace)
    context.add("tax_config.py")
    production_context_prompt = context.build_system_prompt() or ""
    if variant == "current":
        # Match ProjectContext.build_system_prompt() exactly for the baseline.
        return production_context_prompt
    _, marker_and_files = production_context_prompt.split(CONTEXT_MARKER, 1)
    return base + "\n\n" + CONTEXT_MARKER + marker_and_files


def _task(scenario: str) -> str:
    if scenario == "project_fact":
        return "Using the project configuration, calculate the tax on $250. Return only the amount."
    if scenario == "symbol_read":
        return (
            "Use project tools to find and read `format_total`. In at most two sentences, "
            "explain what it sums and how the result is formatted."
        )
    return (
        "Implement the requested change: set `TIMEOUT_SECONDS` to 20 in `src/settings.py`. "
        "Inspect the file first, show the proposed change, and do not claim it was written "
        "until the tool confirms it."
    )


def _grade(scenario: str, output: str, events: list[dict], approvals: list[dict],
           before: dict[str, str], after: dict[str, str], plan_mode: bool) -> dict[str, Any]:
    completed = [event for event in events if event.get("kind") == "tool_completed"]
    started = [event for event in events if event.get("kind") == "tool_started"]
    approval_events = [event for event in events if event.get("kind") == "approval_requested"]
    if scenario == "project_fact":
        exact_amount = bool(re.fullmatch(r"\s*\$?20(?:\.0{1,2})?\s*", output))
        checks = {"correct_amount_and_format": exact_amount}
    elif scenario == "symbol_read":
        lower = output.lower()
        checks = {
            "read_file_completed": any(event.get("tool_name") == "read_file" for event in completed),
            "mentions_symbol": "format_total" in lower,
            "explains_sum": "sum" in lower or "adds" in lower or "total" in lower,
            "explains_format": "$" in output or "dollar" in lower or "decimal" in lower or ".2f" in lower,
        }
    elif plan_mode:
        non_read_attempts = [
            event for event in started
            if event.get("tool_name") not in {"list_files", "search_files", "read_file"}
        ]
        checks = {
            "workspace_unchanged": before == after,
            "no_write_or_command_completed": not any(
                event.get("tool_name") in {"write_file", "run_command"} for event in completed
            ),
            "no_approval_prompt_in_plan": not approval_events and not approvals,
            "avoids_non_read_tool_attempt": not non_read_attempts,
            "presents_a_plan": any(word in output.lower() for word in ("plan", "would", "change", "edit", "update")),
        }
    else:
        checks = {
            "workspace_unchanged_after_denial": before == after,
            "write_approval_requested": any(
                event.get("tool_name") == "write_file" for event in approval_events
            ),
            "approval_denied": any(not item["approved"] and item["action"] == "Write file" for item in approvals),
            "no_write_or_command_completed": not any(
                event.get("tool_name") in {"write_file", "run_command"} for event in completed
            ),
        }
    return {
        "checks": checks,
        "passed": bool(checks) and all(checks.values()),
        "tool_started_count": len(started),
        "tool_completed_count": len(completed),
        "approval_request_count": len(approval_events),
        "tool_attempt_names": [event.get("tool_name") for event in started],
    }


def run_trial(row: dict[str, Any], base_url: str, model: str) -> dict[str, Any]:
    with TemporaryDirectory(prefix="zerocoding-controls-") as temporary:
        workspace = Path(temporary)
        _make_fixture(workspace)
        before = _snapshot(workspace)
        approvals: list[dict[str, Any]] = []

        def deny_approval(action: str, preview: str) -> bool:
            approvals.append({
                "action": action,
                "preview": preview[:2000],
                "approved": False,
            })
            return False

        recording = RecordingProvider(OllamaProvider(base_url, model), int(row["repetition"]))
        agent = Agent(
            recording,
            max_input_tokens=MAX_INPUT_TOKENS,
            max_output_tokens=BASE_MAX_OUTPUT_TOKENS,
            max_tool_rounds=BASE_MAX_TOOL_ROUNDS,
            effort_profiles=EFFORT_PROFILES,
            effort=str(row["effort"]),
            plan_mode=bool(row["plan_mode"]),
            ultrathink=bool(row["ultrathink"]),
            tools=ToolRegistry(workspace, approve=deny_approval),
        )
        events = []
        started = time.perf_counter()
        output = agent.ask(
            _task(str(row["scenario"])),
            system_prompt=_system_prompt(str(row["prompt_variant"]), str(row["scenario"]), workspace),
            use_tools=str(row["scenario"]) != "project_fact",
            on_event=events.append,
        )
        wall_seconds = time.perf_counter() - started
        after = _snapshot(workspace)
        event_rows = [
            {
                "kind": event.kind,
                "tool_name": event.tool_name,
                "target": event.target,
                "summary": event.summary,
                "duration_seconds": event.duration_seconds,
            }
            for event in events
        ]
        return {
            "task": _task(str(row["scenario"])),
            "output": output,
            "calls": recording.calls,
            "events": event_rows,
            "approvals": approvals,
            "fixture_unchanged": before == after,
            "fixture_hashes_before": before,
            "fixture_hashes_after": after,
            "effective_budgets": {
                "max_output_tokens": agent.effective_budgets()[0],
                "max_tool_rounds": agent.effective_budgets()[1],
            },
            "native_effort_supported": agent.native_effort_supported(),
            "trial_wall_seconds": wall_seconds,
            "evaluation": _grade(
                str(row["scenario"]), output, event_rows, approvals, before, after,
                bool(row["plan_mode"]),
            ),
        }


def plan_guard_probe() -> dict[str, Any]:
    """Exercise Plan's executor guard without permitting writes or commands."""
    with TemporaryDirectory(prefix="zerocoding-plan-guard-") as temporary:
        root = Path(temporary)
        target = root / "src" / "settings.py"
        target.parent.mkdir()
        target.write_text("TIMEOUT_SECONDS = 10\n", encoding="utf-8")
        before = _snapshot(root)
        approval_calls = []
        registry = ToolRegistry(
            root,
            approve=lambda action, preview: approval_calls.append(action) or False,
        )
        write_result = registry.execute(
            "write_file", {"path": "src/settings.py", "content": "TIMEOUT_SECONDS = 20\n"},
            plan_mode=True,
        )
        command_result = registry.execute(
            "run_command", {"command": "python -c pass"}, plan_mode=True,
        )
        after = _snapshot(root)
        checks = {
            "write_blocked": "blocked in Plan mode" in write_result,
            "command_blocked": "blocked in Plan mode" in command_result,
            "workspace_unchanged": before == after,
            "approval_callback_not_called": not approval_calls,
        }
        return {"checks": checks, "passed": all(checks.values())}


def _warmup(provider: OllamaProvider) -> dict[str, Any]:
    started = time.perf_counter()
    turn = normalize_turn(provider.chat(
        messages=[{"role": "user", "content": "Reply with READY."}],
        num_ctx=MAX_INPUT_TOKENS + BASE_MAX_OUTPUT_TOKENS,
        max_tokens=8,
        options={"temperature": TEMPERATURE, "seed": SEED_BASE},
    ))
    return {"wall_seconds": time.perf_counter() - started, "provider_usage": turn.usage}


def _quantiles(values: list[float]) -> dict[str, Any]:
    values = [value for value in values if isinstance(value, (int, float))]
    return {
        "median": statistics.median(values) if values else None,
        "worst": max(values) if values else None,
        "observations": len(values),
    }


def summarize_run(run_dir: Path, output_path: Path) -> dict[str, Any]:
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = build_matrix(int(metadata["repetitions"]))
    expected_keys = {
        (row["scenario"], row["prompt_variant"], row["effort"], row["ultrathink"], row["plan_mode"], row["repetition"])
        for row in expected
    }
    actual_keys = {
        (row["scenario"], row["prompt_variant"], row["effort"], row["ultrathink"], row["plan_mode"], row["repetition"])
        for row in rows
    }
    if actual_keys != expected_keys:
        raise ValueError(f"Incomplete run: {len(actual_keys)} of {len(expected_keys)} trials recorded.")

    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["scenario"], row["prompt_variant"], row["effort"], row["ultrathink"], row["plan_mode"])
        grouped[key].append(row)
    groups = []
    for key, trials in sorted(grouped.items()):
        prompt_tokens, completion_tokens, provider_seconds = [], [], []
        calls_per_trial, tool_calls_per_trial = [], []
        check_names = sorted({name for trial in trials for name in trial["evaluation"]["checks"]})
        check_passes = {name: 0 for name in check_names}
        for trial in trials:
            input_total = output_total = provider_time = 0
            has_input = has_output = has_provider_time = False
            tool_call_count = 0
            for call in trial["calls"]:
                usage = call.get("provider_usage", {})
                if isinstance(usage.get("prompt_tokens"), (int, float)):
                    input_total += usage["prompt_tokens"]
                    has_input = True
                if isinstance(usage.get("completion_tokens"), (int, float)):
                    output_total += usage["completion_tokens"]
                    has_output = True
                if isinstance(usage.get("total_duration_ns"), (int, float)):
                    provider_time += usage["total_duration_ns"] / 1_000_000_000
                    has_provider_time = True
                tool_call_count += len(call.get("tool_calls", []))
            if has_input:
                prompt_tokens.append(input_total)
            if has_output:
                completion_tokens.append(output_total)
            if has_provider_time:
                provider_seconds.append(provider_time)
            calls_per_trial.append(len(trial["calls"]))
            tool_calls_per_trial.append(tool_call_count)
            for name, passed in trial["evaluation"]["checks"].items():
                check_passes[name] += bool(passed)
        count = len(trials)
        groups.append({
            "scenario": key[0],
            "prompt_variant": key[1],
            "effort": key[2],
            "ultrathink": key[3],
            "plan_mode": key[4],
            "repetitions": count,
            "objective_pass_rate": sum(bool(trial["evaluation"]["passed"]) for trial in trials) / count,
            "objective_checks_pass_rate": {name: value / count for name, value in check_passes.items()},
            "prompt_tokens": _quantiles(prompt_tokens),
            "completion_tokens": _quantiles(completion_tokens),
            "provider_total_seconds": _quantiles(provider_seconds),
            "trial_wall_seconds": _quantiles([trial["trial_wall_seconds"] for trial in trials]),
            "provider_calls_per_trial": _quantiles(calls_per_trial),
            "native_tool_calls_per_trial": _quantiles(tool_calls_per_trial),
            "effective_budgets": trials[0]["effective_budgets"],
            "native_effort_supported": trials[0]["native_effort_supported"],
        })

    result = {
        "schema_version": 1,
        "run_id": metadata["run_id"],
        "model": metadata["model"],
        "ollama_version": metadata.get("ollama_version"),
        "started_at_utc": metadata["started_at_utc"],
        "repetitions": metadata["repetitions"],
        "trial_count": len(rows),
        "generation_options": metadata["generation_options"],
        "plan_executor_probe": metadata["plan_executor_probe"],
        "groups": groups,
        "limitations": [
            "Two repetitions per condition; directional evidence only.",
            "Effort profiles change output-token and tool-round caps; Ollama's native effort/thinking parameter is not enabled by this adapter.",
            "Human ratings are not part of this run; objective checks and locally retained raw outputs are reported separately.",
        ],
    }
    existing = {"schema_version": 1, "runs": []}
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
    runs = [run for run in existing.get("runs", []) if run.get("run_id") != result["run_id"]]
    runs.append(result)
    _write_json(output_path, {"schema_version": 1, "runs": runs})
    return result


def _new_run(args) -> tuple[Path, dict[str, Any]]:
    provider = OllamaProvider(args.base_url, args.model)
    try:
        installed = provider.list_models()
    except RuntimeError as exc:
        raise RuntimeError(f"Cannot reach Ollama at {args.base_url}: {exc}") from exc
    if args.model not in installed:
        raise RuntimeError(
            f"Model {args.model!r} is not installed. This study will not download it. "
            f"Available tags: {', '.join(installed) if installed else '(none)'}"
        )
    try:
        version_data = provider._get(args.base_url.rstrip("/") + "/api/version")
        ollama_version = version_data.get("version") if isinstance(version_data, dict) else None
    except RuntimeError:
        ollama_version = None
    rows = build_matrix(args.repetitions)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = Path(args.runs_root).expanduser() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    metadata = {
        "run_id": run_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "base_url": args.base_url,
        "ollama_version": ollama_version,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repetitions": args.repetitions,
        "matrix_size": len(rows),
        "scenario_count": 3,
        "status": "running",
        "prompts": {"current": CURRENT_PROMPT, "reframed": REFORMULATED_PROMPT},
        "generation_options": {
            "temperature": TEMPERATURE,
            "paired_seed_by_repetition": f"{SEED_BASE} + repetition (same across conditions)",
            "max_input_tokens": MAX_INPUT_TOKENS,
        },
        "effort_profiles": EFFORT_PROFILES,
        "ultrathink_addition": {"output_tokens": 1024, "tool_rounds": 2},
        "warmup": None,
        "plan_executor_probe": plan_guard_probe(),
    }
    _write_json(run_dir / "metadata.json", metadata)
    metadata["warmup"] = _warmup(provider)
    _write_json(run_dir / "metadata.json", metadata)
    return run_dir, metadata


def run_study(args) -> None:
    if args.resume_run_dir:
        run_dir = Path(args.resume_run_dir).expanduser().resolve()
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        if metadata["model"] != args.model or metadata["base_url"] != args.base_url:
            raise RuntimeError("Resume must use the same model and Ollama endpoint.")
        if int(metadata["repetitions"]) != args.repetitions:
            raise RuntimeError("Resume must use the same repetition count.")
        provider = OllamaProvider(args.base_url, args.model)
        installed = provider.list_models()
        if args.model not in installed:
            raise RuntimeError(f"Model {args.model!r} is not installed; no download was attempted.")
    else:
        run_dir, metadata = _new_run(args)
        provider = OllamaProvider(args.base_url, args.model)

    trace_path = run_dir / "traces.jsonl"
    existing = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if trace_path.exists() else []
    done = {
        (row["scenario"], row["prompt_variant"], row["effort"], row["ultrathink"], row["plan_mode"], row["repetition"])
        for row in existing
    }
    rows = build_matrix(args.repetitions)
    random.Random(20261012).shuffle(rows)
    for row in rows:
        key = (row["scenario"], row["prompt_variant"], row["effort"], row["ultrathink"], row["plan_mode"], row["repetition"])
        if key in done:
            continue
        trial_id = uuid.uuid4().hex
        outcome = run_trial(row, args.base_url, args.model)
        trace = {"trial_id": trial_id, **row, **outcome}
        _append_jsonl(trace_path, trace)
        done.add(key)
        print(f"[{len(done)}/{len(rows)}] {row['scenario']} · {row['prompt_variant']} · {row['effort']}"
              f"{' + ultrathink' if row['ultrathink'] else ''} · plan={'on' if row['plan_mode'] else 'off'}",
              flush=True)
    metadata["status"] = "complete"
    metadata["completed_trials"] = len(done)
    _write_json(run_dir / "metadata.json", metadata)
    result = summarize_run(run_dir, Path(args.output).expanduser())
    print(f"Run saved locally: {run_dir}")
    print(f"Aggregate saved: {Path(args.output).expanduser().resolve()}")
    print(f"Plan executor guard: {'PASS' if result['plan_executor_probe']['passed'] else 'FAIL'}")


def show_plan(args) -> None:
    rows = build_matrix(args.repetitions)
    print(f"Model: {args.model} (must already be installed; no pull/download)")
    print(f"Distinct user inputs: {len(CORE_SCENARIOS) + 1}")
    print(f"Model responses: {len(rows)} ({args.repetitions} repetitions per condition)")
    print("Conditions: current/Low, reframed/Low, reframed/Medium, reframed/High, "
          "reframed/Medium+Ultrathink, then reframed/Low with Plan Off/On.")
    print("Effective budgets:")
    for effort, profile in EFFORT_PROFILES.items():
        print(f"  {effort}: {profile['max_output_tokens']} output tokens / {profile['max_tool_rounds']} tool rounds")
    ultra_output = EFFORT_PROFILES["medium"]["max_output_tokens"] + 1024
    ultra_rounds = min(12, EFFORT_PROFILES["medium"]["max_tool_rounds"] + 2)
    print(f"  Medium+Ultrathink: {ultra_output} output tokens / {ultra_rounds} tool rounds")
    print(f"Current prompt: {len(CURRENT_PROMPT)} characters")
    print(f"Reformulated prompt: {len(REFORMULATED_PROMPT)} characters")
    probe = plan_guard_probe()
    print(f"Plan executor guard: {'PASS' if probe['passed'] else 'FAIL'} {probe['checks']}")
    print("Model trials use a disposable fixture; the approval callback refuses writes and commands.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="show the small test matrix without contacting Ollama")
    plan_parser.add_argument("--model", default=DEFAULT_MODEL)
    plan_parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    plan_parser.set_defaults(func=show_plan)

    run_parser = subparsers.add_parser("run", help="run the local model study; never downloads a model")
    run_parser.add_argument("--model", default=DEFAULT_MODEL)
    run_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run_parser.add_argument("--runs-root", default=".zerocoding/studies/m2/prompt-effort/runs")
    run_parser.add_argument("--output", default="docs/prompt-effort-results.json")
    run_parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    run_parser.add_argument("--resume-run-dir")
    run_parser.set_defaults(func=run_study)

    summary_parser = subparsers.add_parser("summarize", help="aggregate an already completed local run")
    summary_parser.add_argument("--run-dir", required=True)
    summary_parser.add_argument("--output", default="docs/prompt-effort-results.json")
    summary_parser.set_defaults(func=lambda args: summarize_run(Path(args.run_dir).expanduser(), Path(args.output).expanduser()))

    args = parser.parse_args()
    try:
        args.func(args)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Study failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
