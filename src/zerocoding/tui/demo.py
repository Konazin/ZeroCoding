"""Run the provider-free M1 UI prototypes."""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m zerocoding.tui.demo",
        description="Compare the two ZeroCoding M1 terminal UI prototypes.",
    )
    parser.add_argument("stack", choices=("rich", "textual"), help="prototype to open")
    args = parser.parse_args(argv)

    if args.stack == "rich":
        from .demo_rich import run
    else:
        from .demo_textual import run
    return run()


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

