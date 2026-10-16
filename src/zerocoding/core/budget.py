"""Prompt budget fitting without breaking tool-call protocol messages."""
from __future__ import annotations

from .tokens import estimate_tokens


class PromptTooLargeError(ValueError):
    """Raised when the system instructions and current request cannot fit intact."""


def _count_prompt(count, messages: list[dict], tools: list[dict] | None) -> int:
    method = getattr(count, "count_prompt", None)
    if callable(method):
        return method(messages, tools)
    if tools:
        return count({"messages": messages, "tools": tools})
    return count(messages)


def _turn_groups(messages: list[dict]) -> list[list[dict]]:
    """Keep each user turn, including its assistant tool calls and results, together."""
    groups: list[list[dict]] = []
    for message in messages:
        role = message.get("role")
        if role in {"system", "user"} or not groups:
            groups.append([message])
        else:
            groups[-1].append(message)
    return groups


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

    groups = _turn_groups(result)
    current_group = max(
        (index for index, group in enumerate(groups)
         if any(message.get("role") == "user" for message in group)),
        default=len(groups) - 1,
    )

    def flattened() -> list[dict]:
        return [message for group in groups for message in group]

    while _count_prompt(count, flattened(), tools) > max_tokens:
        removable = next(
            (index for index, group in enumerate(groups)
             if index < current_group and not any(message.get("role") == "system" for message in group)),
            None,
        )
        if removable is None:
            break
        groups.pop(removable)
        current_group -= 1

    fitted = flattened()
    while _count_prompt(count, fitted, tools) > max_tokens:
        outputs = [message for message in fitted if message.get("role") == "tool"]
        if not outputs:
            break
        largest = max(outputs, key=lambda message: len(str(message.get("content", ""))))
        if not _trim_tool_output(largest):
            break

    if _count_prompt(count, fitted, tools) > max_tokens:
        raise PromptTooLargeError(
            "The current request and required instructions exceed the input token budget. "
            "Shorten the request or reduce the configured system prompt/active skills."
        )
    return fitted
