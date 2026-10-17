"""Re-measure the TokenCounter fallback against llama-server on repository-derived prompts.

Builds varied prompts (code, docs, config; 1-14 messages; with and without tool schemas), asks the
server for the exact rendered count and reports the error of `estimate_prompt_tokens`.
Tokenization only; no generation. Example:
  .venv/bin/python scripts/m7_token_fit.py --output docs/m7-token-fallback-20261016.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import tempfile
import time
from pathlib import Path

from zerocoding.core.tokens import estimate_prompt_tokens
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.llama_cpp import LlamaCppProvider

SKIP = {".venv", "node_modules", ".git", ".pytest_cache", "studies", "__pycache__"}


def _files(root: Path) -> dict[Path, str]:
    found = {}
    for ext in ("py", "md", "yaml", "json", "toml"):
        for path in root.rglob(f"*.{ext}"):
            if SKIP & set(path.parts) or not 200 < path.stat().st_size < 400_000:
                continue
            found[path] = path.read_text(encoding="utf-8", errors="ignore")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="ornith-1.5-9b-q5-k-m")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--samples", type=int, default=160)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"refusing to overwrite existing report: {args.output}")
    rng = random.Random(args.seed)
    texts = _files(args.root)
    paths = sorted(texts)

    def chunk() -> str:
        text = texts[rng.choice(paths)]
        size = rng.choice([80, 300, 900, 2500])
        start = rng.randrange(0, max(1, len(text) - size))
        return text[start:start + size]

    provider = LlamaCppProvider("", args.base_url, args.model, timeout=60)
    with tempfile.TemporaryDirectory() as directory:
        schemas = ToolRegistry(directory).schemas
    rows = []
    for _ in range(args.samples):
        messages = [{"role": "system", "content": "You are a concise coding assistant."}]
        for _ in range(rng.randint(1, 6)):
            messages.append({"role": "user", "content": chunk()})
            messages.append({"role": "assistant", "content": chunk() if rng.random() < 0.6 else "Done."})
        messages.append({"role": "user", "content": chunk()})
        tools = rng.sample(schemas, rng.randint(3, len(schemas))) if rng.random() < 0.5 else None
        exact = provider.count_prompt(messages, tools)
        if not isinstance(exact, int) or exact <= 0:
            continue
        estimate = estimate_prompt_tokens(messages, tools)
        rows.append({"with_tools": bool(tools), "exact": exact, "estimate": estimate,
                     "error_pct": round((estimate - exact) / exact * 100, 2)})
    errors = [row["error_pct"] for row in rows]
    absolute = sorted(abs(value) for value in errors)
    report = {
        "date": time.strftime("%Y-%m-%d"), "label": args.model, "samples": len(rows),
        "median_abs_error_pct": round(statistics.median(absolute), 2),
        "p90_abs_error_pct": round(absolute[int(len(absolute) * 0.9)], 2),
        "worst_underestimate_pct": min(errors), "worst_overestimate_pct": max(errors),
        "rows": rows,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print({key: value for key, value in report.items() if key != "rows"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
