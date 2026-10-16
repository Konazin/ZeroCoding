"""Prompt budget fitting: trim history and tool output so a request fits the input window."""
from __future__ import annotations

from .tokens import estimate_tokens


def fit_messages(messages: list[dict], max_tokens: int, count=estimate_tokens) -> list[dict]:
    """Fit a prompt while keeping the current request and its tool results.

    ``count`` maps a message list to a token count (heuristic by default).
    """
    result = [dict(message) for message in messages]
    while count(result) > max_tokens:
        latest_user = max((i for i, msg in enumerate(result) if msg.get("role") == "user"), default=-1)
        removable = next((i for i, msg in enumerate(result)
                          if msg.get("role") != "system" and i != latest_user and i < latest_user), None)
        if removable is None:
            break
        result.pop(removable)
    if count(result) > max_tokens:
        # Tool outputs are expendable once they have been returned to the model.
        outputs = [msg for msg in result if msg.get("role") == "tool"]
        while outputs and count(result) > max_tokens:
            largest = max(outputs, key=lambda msg: len(str(msg.get("content", ""))))
            content = str(largest.get("content", ""))
            if len(content) <= 80:
                outputs.remove(largest)
                result.remove(largest)
            else:
                largest["content"] = content[: max(80, len(content) // 2)]
    if count(result) > max_tokens and result:
        system = next((m for m in result if m.get("role") == "system"), {"role": "system", "content": ""})
        current = next((m for m in reversed(result) if m.get("role") == "user"), result[-1])
        available_chars = max(80, (max_tokens - 80) * 3)
        current["content"] = str(current.get("content", ""))[-max(80, available_chars // 2):]
        system["content"] = str(system.get("content", ""))[:available_chars // 2]
        result = [system, current]
    return result
