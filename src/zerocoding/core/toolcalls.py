"""Helpers for tool calls inside the agent loop: compact-marker parsing, events and summaries."""
from __future__ import annotations

import json
import re

from .events import AgentEvent
from ..providers.base import ProviderTurn, ToolCall

COMPACT_CALL = re.compile(r"<tool_call>\s*(\{.*\})\s*</tool_call>", re.DOTALL)


def emit_event(callback, event: AgentEvent) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # A presentation callback must never break the agent's tool loop.
        return


def tool_target(name: str, arguments: dict) -> str:
    value = arguments.get("path") or arguments.get("pattern") or arguments.get("command") or ""
    target = " ".join(str(value).split())
    return target if len(target) <= 96 else target[:93] + "…"


def tool_summary(name: str, result: str) -> str:
    value = result.strip()
    lower = value.lower()
    if "denied by user" in lower or "nothing was executed" in lower:
        return "Denied · no action taken"
    if value.startswith("Tool error:"):
        return "Tool error"
    lines = [line for line in value.splitlines() if line.strip()]
    if name == "read_file":
        return f"{len(lines)} lines read"
    if name == "list_files":
        if lower == "no files found.":
            return "0 files"
        return f"{len(lines)} files listed"
    if name == "search_files":
        if lower == "no matches found.":
            return "0 matches"
        return f"{len(lines)} matches"
    if name == "run_command":
        exit_code = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("exit code:")), "unknown")
        output_lines = max(0, len(lines) - 1)
        return f"exit {exit_code} · {output_lines} output lines"
    if name == "edit_file":
        return "File edited" if value.lower().startswith("edited ") else "Completed"
    if name == "write_file":
        return "File written" if value.lower().startswith("wrote ") else "Completed"
    if len(lines) > 1:
        return f"Completed · {len(lines)} lines"
    return f"Completed · {len(value)} characters" if value else "Completed"


def parse_compact_call(turn: ProviderTurn) -> ProviderTurn:
    if turn.tool_calls:
        return turn
    match = COMPACT_CALL.search(turn.content)
    if not match:
        return turn
    try:
        payload = json.loads(match.group(1))
        name = payload.get("name") or payload.get("tool")
        args = payload.get("arguments", payload.get("parameters", {}))
        if name and isinstance(args, dict):
            content = (turn.content[:match.start()] + turn.content[match.end():]).strip()
            return ProviderTurn(
                content=content,
                tool_calls=[ToolCall(str(name), args)],
                usage=turn.usage,
                thinking_present=turn.thinking_present,
                reasoning_content=turn.reasoning_content,
            )
    except (ValueError, TypeError):
        pass
    return turn
