"""A/B de `dynamic_context` contra um llama-server local (1 repetição por caso; negação de toda escrita/comando).

Uso: uv run python scripts/dynamic_context_ab.py
"""
import statistics
import tempfile
import time
from pathlib import Path
from zerocoding.core.agent import Agent
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.llama_cpp import LlamaCppProvider

WS = tempfile.mkdtemp(prefix="zc_ab_")
Path(WS, "calc.py").write_text("def soma(a, b):\n    return a + b\n")


class Rec(LlamaCppProvider):
    def chat(self, messages, **kw):
        turn = super().chat(messages, **kw)
        self.log.append(getattr(turn, "usage", {}) or {})
        return turn

CASES = [  # (prompt, expected: 'read'|'write'|'command')
 ("Leia calc.py e explique a função.", "read"),
 ("Liste os arquivos do projeto e busque a palavra soma.", "read"),
 ("Crie o arquivo hello.py com um print de olá mundo.", "write"),
 ("Altere calc.py para também ter uma função subtrai(a, b).", "write"),
 ("Rode o comando ls -la no projeto.", "command"),
 ("Execute os testes do projeto com python -m unittest.", "command"),
 ("Mostre calc.py e depois me diga como eu poderia melhorar o nome das variáveis.", "read"),
 ("Quero que o arquivo calc.py retorne 0 se algum argumento for None. Pode ajustar?", "write"),  # sem palavras-gatilho óbvias
]
def trial(dynamic, prompt, expected):
    prov = Rec("", "http://127.0.0.1:8080/v1", "ornith-1.5-9b-q5-k-m", timeout=300); prov.log = []
    reg = ToolRegistry(WS, approve=lambda a, p: False)
    agent = Agent(prov, max_input_tokens=4096, max_output_tokens=1024, tools=reg, dynamic_context=dynamic)
    ev = []
    t = time.time()
    try: agent.ask(prompt, use_tools=True, on_event=lambda e: ev.append((e.kind, e.tool_name)))
    except Exception as exc: ev.append(("error", str(exc)[:80]))
    first_prompt = prov.log[0].get("prompt_tokens") if prov.log else None
    asked = {n for k, n in ev if k == "approval_requested"}
    ok = ({"read": any(k == "tool_completed" for k, _ in ev),
           "write": "write_file" in asked, "command": "run_command" in asked})[expected]
    return dict(first_prompt=first_prompt, ok=ok, secs=time.time() - t)
res = {}
for dyn in (False, True):
    res[dyn] = [trial(dyn, p, e) for p, e in CASES]
for i, (p, e) in enumerate(CASES):
    a, b = res[False][i], res[True][i]
    print(f"{e:8} off: prompt={a['first_prompt']} ok={a['ok']} | on: prompt={b['first_prompt']} ok={b['ok']}  {p[:50]}")
for dyn in (False, True):
    r = res[dyn]
    print("dynamic", dyn, "ok", sum(x['ok'] for x in r), "/", len(r), "mediana prompt_tokens", statistics.median(x['first_prompt'] or 0 for x in r), "tempo", round(sum(x['secs'] for x in r)))
