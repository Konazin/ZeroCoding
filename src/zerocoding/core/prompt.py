from math import ceil

SYSTEM_PROMPT = "You are ZeroCoding, a concise coding assistant. Use tools when useful; report completed actions."
PROMPT_BUDGET_TOKENS = 3072
OUTPUT_RESERVE_TOKENS = 512


def estimate_tokens(text: str) -> int:
    """Conservative, provider-independent estimate; providers may report exact usage."""
    return ceil(len(text) / 4) if text else 0


def _clip(text: str, tokens: int) -> str:
    if tokens <= 0:
        return ""
    if estimate_tokens(text) <= tokens:
        return text
    return text[: tokens * 4]


def build_messages(
    user_text: str,
    system_prompt: str | None = None,
    history: list | None = None,
    skills: list | None = None,
    context_text: str = "",
    budget_tokens: int = PROMPT_BUDGET_TOKENS,
):
    """Keep a tiny fixed system prompt; fit newest conversation and current request first."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    remaining = max(0, budget_tokens - estimate_tokens(SYSTEM_PROMPT))

    # Tool schemas are deducted by Agent before this function. Keep the current request intact first.
    request_cap = max(128, budget_tokens // 2 - (64 if budget_tokens <= 1024 else 0))
    request = _clip(user_text, min(remaining, request_cap))
    remaining -= estimate_tokens(request)
    extras = []
    if system_prompt:
        extras.append("Additional instructions:\n" + system_prompt)
    skill_text = "\n\n".join(f"Skill: {skill.name}\n{skill.content}" for skill in (skills or []))
    if skill_text:
        extras.append("Active skills:\n" + skill_text)
    if context_text:
        extras.append("Project context:\n" + context_text)
    extra = _clip("\n\n".join(extras), min(remaining, 768))
    remaining -= estimate_tokens(extra)

    selected = []
    for item in reversed((history or [])[-10:]):
        content = _clip(str(item.get("content", "")), remaining)
        if not content:
            break
        selected.append({"role": item["role"], "content": content})
        remaining -= estimate_tokens(content)
    messages.extend(reversed(selected))
    messages.append({"role": "user", "content": (extra + "\n\nUser request:\n" if extra else "") + request})

    # Make the final estimate authoritative, trimming old history before the request.
    while sum(estimate_tokens(m["content"]) for m in messages) > budget_tokens and len(messages) > 2:
        del messages[1]
    if sum(estimate_tokens(m["content"]) for m in messages) > budget_tokens:
        prefix, separator, request = messages[-1]["content"].rpartition("\n\nUser request:\n")
        if not separator:
            prefix, request = "", messages[-1]["content"]
        available = max(0, budget_tokens - sum(estimate_tokens(m["content"]) for m in messages[:-1]))
        request = _clip(request, available)
        extra_budget = max(0, available - estimate_tokens(request))
        prefix = _clip(prefix, extra_budget)
        messages[-1]["content"] = (prefix + separator if prefix and separator else "") + request
    return messages
