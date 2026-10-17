"""Helpers for tool calls inside the agent loop: compact-marker parsing, events and summaries."""
from __future__ import annotations

import json
import re

from .events import AgentEvent
from ..providers.base import ProviderTurn, ToolCall

SHELL_FENCE = re.compile(r"```[ \t]*(?:bash|sh|shell|zsh|console|terminal)[ \t]*\n(.*?)```", re.IGNORECASE | re.DOTALL)
# run_command launches an argv without a shell, so these cannot work and are left as plain text.
UNSUPPORTED_SHELL = re.compile(r"&&|\|\||[|;<>`]|\$\(|\\$")
MAX_TEXT_COMMANDS = 4
CHANGING_TOOLS = frozenset({"write_file", "edit_file", "run_command"})

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
        reason = " ".join(value[len("Tool error:"):].split())
        return f"Tool error · {reason[:90]}" if reason else "Tool error"
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


def shell_calls_from_text(turn: ProviderTurn, limit: int = MAX_TEXT_COMMANDS) -> ProviderTurn:
    """Small models often print a command in a ```bash block instead of calling `run_command`.

    Turn the runnable lines of such blocks into `run_command` calls so they go through the normal
    approval flow. A block with any line that needs a shell (pipes, `&&`, redirects, `cd`) is left
    untouched as text, and the converted blocks are removed from the visible text.
    """
    if turn.tool_calls:
        return turn
    commands: list[str] = []
    content = turn.content
    for match in list(SHELL_FENCE.finditer(turn.content)):
        block: list[str] = []
        for raw in match.group(1).splitlines():
            line = raw.strip()
            if line.startswith("$ "):
                line = line[2:].strip()
            if not line or line.startswith("#"):
                continue
            if UNSUPPORTED_SHELL.search(line) or line.split()[0] == "cd":
                block = []
                break
            block.append(line)
        if block:
            commands.extend(block)
            content = content.replace(match.group(0), "", 1)
    commands = commands[:limit]
    if not commands:
        return turn
    return ProviderTurn(
        content=re.sub(r"\n{3,}", "\n\n", content).strip(),
        tool_calls=[ToolCall("run_command", {"command": command}) for command in commands],
        usage=turn.usage,
        thinking_present=turn.thinking_present,
        reasoning_content=turn.reasoning_content,
    )
