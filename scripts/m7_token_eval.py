"""Compare the local heuristic prompt budget with llama-server's rendered token count.

This performs tokenization only; it does not generate model responses.
Example:
  .venv/bin/python scripts/m7_token_eval.py --output docs/m7-token-calibration.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import tempfile
from pathlib import Path

from zerocoding.core.tokens import TokenCounter
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.llama_cpp import LlamaCppProvider


SHORT_PROMPTS = [
    "Leia calc.py e explique o retorno de soma.",
    "Busque a função dobro e resuma o que ela faz.",
    "Quantos módulos Python há no projeto? Responda brevemente.",
    "Confira se soma(a, b) retorna a soma dos argumentos.",
    "Explique em uma frase como executar os testes do projeto.",
]

LONG_PROMPTS = [
    "Agora localize a validação de entrada e resuma os casos tratados.",
    "Compare a função atual com as decisões discutidas e identifique divergências.",
    "Resuma quais módulos seriam afetados por uma mudança na assinatura.",
    "Explique a relação entre os testes e a implementação, citando os arquivos.",
    "Liste as premissas que ainda precisam ser verificadas antes de editar.",
]


def _messages(sample: int, long: bool) -> list[dict[str, str]]:
    system = "You are a concise coding assistant. Inspect project files before proposing changes."
    messages = [{"role": "system", "content": system}]
    if long:
        for turn in range(8 + sample * 2):
            messages.append({
                "role": "user",
                "content": (
                    f"Request {turn}: inspect module part_{turn}.py, explain behavior and edge cases, "
                    f"and note how it connects to {('the parser' if turn % 2 else 'the test suite')}. "
                    f"Calibration sample {sample} records a request about {('imports' if turn % 3 else 'error handling')}."
                ),
            })
            messages.append({
                "role": "assistant",
                "content": (
                    f"The module was inspected. Its main behavior, edge cases, and relationship to "
                    f"{('the parser' if turn % 2 else 'the test suite')} were summarized. "
                    f"No files were changed; the public API remains unchanged (review {turn + 1})."
                ),
            })
    messages.append({
        "role": "user",
        "content": (LONG_PROMPTS if long else SHORT_PROMPTS)[sample - 1],
    })
    return messages


def _summarize(rows: list[dict]) -> dict:
    errors = [row["relative_error_pct"] for row in rows if row["relative_error_pct"] is not None]
    return {
        "samples": len(rows),
        "median_relative_error_pct": round(statistics.median(errors), 3) if errors else None,
        "mean_relative_error_pct": round(statistics.mean(errors), 3) if errors else None,
        "max_relative_error_pct": round(max(errors), 3) if errors else None,
        "within_3_percent": bool(errors) and max(errors) <= 3.0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="ornith-1.5-9b-q5-k-m")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True, help="new JSON report path")
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.samples > len(SHORT_PROMPTS):
        parser.error(f"--samples must be at most {len(SHORT_PROMPTS)}; the calibration set has that many distinct prompts")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing report: {args.output}")

    provider = LlamaCppProvider("", args.base_url, args.model, timeout=30)
    fallback = TokenCounter()
    with tempfile.TemporaryDirectory(prefix="zc_m7_token_tools_") as temporary:
        tools = ToolRegistry(temporary).schemas
        records = []
        for long in (False, True):
            for with_tools in (False, True):
                case = f"{'long' if long else 'short'}_{'with_tools' if with_tools else 'without_tools'}"
                for sample in range(1, args.samples + 1):
                    messages = _messages(sample, long)
                    selected_tools = tools if with_tools else None
                    exact = provider.count_prompt(messages, selected_tools)
                    estimate = fallback.count_prompt(messages, selected_tools)
                    relative_error = (
                        abs(estimate - exact) / exact * 100.0
                        if isinstance(exact, int) and exact > 0 else None
                    )
                    records.append({
                        "case": case,
                        "sample": sample,
                        "exact_tokens": exact,
                        "fallback_estimate_tokens": estimate,
                        "relative_error_pct": round(relative_error, 3) if relative_error is not None else None,
                    })
                    print(f"{case:24} [{sample}/{args.samples}] exact={exact} fallback={estimate} "
                          f"error={records[-1]['relative_error_pct']}%", flush=True)

    summaries = {
        name: _summarize([row for row in records if row["case"] == name])
        for name in sorted({row["case"] for row in records})
    }
    report = {
        "label": args.model,
        "date": time.strftime("%Y-%m-%d"),
        "base_url": args.base_url,
        "method": "server /apply-template followed by /tokenize versus TokenCounter fallback",
        "samples_per_case": args.samples,
        "acceptance_threshold_relative_error_pct": 3.0,
        "all_cases_within_3_percent": all(item["within_3_percent"] for item in summaries.values()),
        "summary": summaries,
        "samples": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"all_cases_within_3_percent": report["all_cases_within_3_percent"],
                      "summary": summaries}, indent=2, ensure_ascii=False))
    print("salvo em", args.output)
    return 0 if report["all_cases_within_3_percent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
