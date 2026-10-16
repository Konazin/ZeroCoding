"""Local per-turn metrics (JSON lines). Stores numbers only: never prompts, answers or file content."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

DEFAULT_METRICS_PATH = Path(".zerocoding") / "metrics" / "turns.jsonl"
MAX_RECENT = 500


class MetricsLog:
    def __init__(self, path: str | Path = DEFAULT_METRICS_PATH):
        self.path = Path(path)

    def record(self, stats: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(stats, ensure_ascii=False) + "\n")
        except OSError:
            return  # metrics must never break a turn

    def recent(self, limit: int = MAX_RECENT) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows


def summarize(rows: list[dict]) -> dict:
    """Aggregate turns: outcome counts, median/worst latency and tokens, tool error and trim rates."""
    if not rows:
        return {"turns": 0}

    def column(key):
        return [r[key] for r in rows if isinstance(r.get(key), (int, float))]

    def med_worst(key):
        values = column(key)
        return {"median": round(statistics.median(values), 2), "worst": round(max(values), 2)} if values else None

    tool_calls = sum(column("tool_calls"))
    trimmed_turns = sum(1 for r in rows if r.get("trimmed_messages", 0) > 0)
    outcomes: dict[str, int] = {}
    for row in rows:
        outcomes[row.get("outcome", "unknown")] = outcomes.get(row.get("outcome", "unknown"), 0) + 1
    return {
        "turns": len(rows),
        "outcomes": outcomes,
        "duration_s": med_worst("duration_s"),
        "ttft_ms": med_worst("ttft_ms"),
        "prompt_tokens": med_worst("prompt_tokens"),
        "completion_tokens": med_worst("completion_tokens"),
        "tool_calls": tool_calls,
        "tool_error_rate": round(sum(column("tool_errors")) / tool_calls, 3) if tool_calls else 0.0,
        "turns_with_trimmed_history": trimmed_turns,
        "trimmed_turn_rate": round(trimmed_turns / len(rows), 3),
    }
