"""Exercise mid-stream cancellation against a running llama-server.

This sends one local generation request and verifies that the server slot becomes idle.
Example:
  .venv/bin/python scripts/m7_stream_cancel_check.py --output docs/m7-stream-cancel.json
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from zerocoding.core.cancel import CancelToken, TurnCancelled
from zerocoding.providers.llama_cpp import LlamaCppProvider


def _slot_processing(base_url: str) -> list[bool]:
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    request = urllib.request.Request(root.rstrip("/") + "/slots", method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        slots = json.loads(response.read().decode("utf-8"))
    if not isinstance(slots, list):
        raise RuntimeError("llama-server /slots returned an unexpected response")
    return [bool(slot.get("is_processing")) for slot in slots if isinstance(slot, dict)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="ornith-1.5-9b-q5-k-m")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--idle-timeout", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True, help="new JSON report path")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"refusing to overwrite existing report: {args.output}")

    provider = LlamaCppProvider("", args.base_url, args.model, timeout=args.timeout)
    cancel = CancelToken()
    deltas = []
    started = time.monotonic()
    first_delta_s = None

    def on_delta(fragment: str) -> None:
        nonlocal first_delta_s
        deltas.append(fragment)
        if first_delta_s is None:
            first_delta_s = time.monotonic() - started
            cancel.cancel()

    cancellation_raised = False
    error = None
    try:
        provider.chat_stream_turn(
            [{"role": "user", "content": "Write a detailed explanation of how Python dictionaries work, with examples."}],
            max_tokens=768,
            on_delta=on_delta,
            cancel=cancel,
        )
    except TurnCancelled:
        cancellation_raised = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    request_duration_s = time.monotonic() - started

    idle_started = time.monotonic()
    slot_states = None
    slot_error = None
    while time.monotonic() - idle_started < args.idle_timeout:
        try:
            slot_states = _slot_processing(args.base_url)
            if not any(slot_states):
                break
        except Exception as exc:
            slot_error = f"{type(exc).__name__}: {exc}"
            break
        time.sleep(0.25)

    server_idle = slot_states is not None and bool(slot_states) and not any(slot_states)
    passed = cancellation_raised and bool(deltas) and server_idle and error is None and slot_error is None
    report = {
        "model": args.model,
        "base_url": args.base_url,
        "request_duration_s": round(request_duration_s, 3),
        "first_public_delta_s": round(first_delta_s, 3) if first_delta_s is not None else None,
        "public_delta_count": len(deltas),
        "public_text_chars_before_cancel": sum(map(len, deltas)),
        "cancellation_raised": cancellation_raised,
        "server_slot_processing_after_cancel": slot_states,
        "server_idle_after_cancel": server_idle,
        "error": error,
        "slot_error": slot_error,
        "passed": passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("salvo em", args.output)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
