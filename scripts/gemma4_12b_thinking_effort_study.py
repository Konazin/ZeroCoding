#!/usr/bin/env python3
"""Run the shared ZeroCoding thinking/effort matrix with Gemma 4 12B settings."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.qwen35_thinking_effort_study import main as study_main


def main() -> int:
    arguments = sys.argv[1:]
    command = arguments[0] if arguments and arguments[0] in {"plan", "run", "summarize"} else "run"
    if arguments and arguments[0] in {"plan", "run", "summarize"}:
        arguments = arguments[1:]
    if command == "summarize":
        sys.argv = [
            sys.argv[0], command, "--output", "docs/gemma4-12b-thinking-effort-results.json", *arguments,
        ]
    else:
        sys.argv = [sys.argv[0], command, "--profile", "gemma4", *arguments]
    return study_main()


if __name__ == "__main__":
    raise SystemExit(main())
