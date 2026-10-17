"""Prompt budget fitting without breaking tool-call protocol messages."""
from __future__ import annotations

from .tokens import estimate_tokens


DIGEST_RESERVE = 200  # tokens


class PromptTooLargeError(ValueError):
    """Raised when the system instructions and current request cannot fit intact."""


def count_prompt(count, messages: list[dict], tools: list[dict] | None) -> int:
    method = getattr(count, "count_prompt", None)
    if callable(method):
        return method(messages, tools)
    if tools:
        return count({"messages": messages, "tools": tools})
    return count(messages)


def turn_groups(messages: list[dict]) -> list[list[dict]]:
    """Keep each user turn, including its assistant tool calls and results, together."""
    groups: list[list[dict]] = []
    for message in messages:
        role = message.get("role")
        if role in {"system", "user"} or not groups:
            groups.append([message])
        else:
            groups[-1].append(message)
    return groups


def _first_line(message: dict, limit: int) -> str:
    text = " ".join(str(message.get("content") or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def digest_turns(dropped: list[list[dict]], max_entries: int = 6, max_chars: int = 700) -> str:
    """Deterministic one-line-per-turn summary of turns removed to fit the budget."""
    lines = []
    for group in dropped[-max_entries:]:
        asked = next((m for m in group if m.get("role") == "user"), None)
        answered = next((m for m in reversed(group) if m.get("role") == "assistant" and m.get("content")), None)
        if asked is None:
            continue
        line = f"- asked: {_first_line(asked, 100)}"
        if answered is not None:
            line += f" | answered: {_first_line(answered, 100)}"
        lines.append(line)
    if not lines:
        return ""
    text = "Earlier turns, shortened to fit context:\n" + "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


COMPACT_MIN_CHARS = 240


def compact_tool_results(messages: list[dict], keep_last_round: bool = True) -> int:
    """Replace large old tool outputs with a one-line stub; returns how many were compacted.

    Tool-call/result pairing stays intact. The newest round of results is kept whole so the
    model can still act on what it just read.
    """
    tool_positions = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if keep_last_round and tool_positions:
        last_assistant = max((i for i, m in enumerate(messages) if m.get("role") == "assistant" and m.get("tool_calls")),
                             default=-1)
        tool_positions = [i for i in tool_positions if i < last_assistant]
    compacted = 0
    for index in tool_positions:
        message = messages[index]
        content = str(message.get("content") or "")
        if len(content) < COMPACT_MIN_CHARS or content.startswith("[compacted"):
            continue
        head = " ".join(content.split())[:80]
        lines = content.count("\n") + 1
        message["content"] = f"[compacted {message.get('name') or 'tool'} result: {lines} lines, {len(content)} chars; starts: {head}]"
        compacted += 1
    return compacted


def _trim_tool_output(message: dict) -> bool:
    content = str(message.get("content", ""))
    marker = "\n[… tool output truncated to fit context …]\n"
    if len(content) <= 80:
        omitted = "[tool output omitted to fit context]"
        replacement = omitted if len(content) > len(omitted) else ""
        if content != replacement:
            message["content"] = replacement
            return True
        return False
    keep = max(40, (len(content) - len(marker)) // 2)
    left = keep // 2
    right = keep - left
    message["content"] = content[:left] + marker + content[-right:]
    return True


def fit_messages(messages: list[dict], max_tokens: int, count=estimate_tokens,
                 tools: list[dict] | None = None) -> list[dict]:
    """Fit a prompt while retaining the current request and complete tool-call groups.

    Old user turns are removed as units. If the active turn still does not fit, tool outputs
    may be shortened while their protocol messages remain paired. The latest user request is
    never truncated; an explicit error is returned when the remaining prompt cannot fit.
    """
    result = [dict(message) for message in messages]
    if not result:
        return result
    if max_tokens < 1:
        raise PromptTooLargeError("Prompt budget must be at least one token.")

    groups = turn_groups(result)
    current_group = max(
        (index for index, group in enumerate(groups)
         if any(message.get("role") == "user" for message in group)),
        default=len(groups) - 1,
    )

    def flattened() -> list[dict]:
        return [message for group in groups for message in group]

    dropped: list[list[dict]] = []
    # Leave room for the digest of dropped turns when the budget is large enough to spare it.
    drop_limit = max_tokens - DIGEST_RESERVE if max_tokens >= 4 * DIGEST_RESERVE else max_tokens
    # Cheap pre-pass: long histories would otherwise cost one exact count per dropped turn.
    cheap = [sum(len(str(m.get("content") or "")) // 4 + 4 for m in group) for group in groups]
    while sum(cheap) > 2 * max_tokens:
        removable = next(
            (index for index, group in enumerate(groups)
             if index < current_group and not any(message.get("role") == "system" for message in group)),
            None,
        )
        if removable is None:
            break
        dropped.append(groups.pop(removable))
        cheap.pop(removable)
        current_group -= 1

    while count_prompt(count, flattened(), tools) > drop_limit:
        removable = next(
            (index for index, group in enumerate(groups)
             if index < current_group and not any(message.get("role") == "system" for message in group)),
            None,
        )
        if removable is None:
            break
        dropped.append(groups.pop(removable))
        current_group -= 1

    fitted = flattened()
    while count_prompt(count, fitted, tools) > max_tokens:
        outputs = [message for message in fitted if message.get("role") == "tool"]
        if not outputs:
            break
        largest = max(outputs, key=lambda message: len(str(message.get("content", ""))))
        if not _trim_tool_output(largest):
            break

    note = digest_turns(dropped) if dropped else ""
    if note and fitted and fitted[0].get("role") == "system":
        original = fitted[0]["content"]
        fitted[0]["content"] = f"{original}\n\n{note}"
        if count_prompt(count, fitted, tools) > max_tokens:
            fitted[0]["content"] = original

    if count_prompt(count, fitted, tools) > max_tokens:
        raise PromptTooLargeError(
            "The current request and required instructions exceed the input token budget. "
            "Shorten the request or reduce the configured system prompt/active skills."
        )
    return fitted
