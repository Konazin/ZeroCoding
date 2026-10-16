"""Token counting for prompt budgets: server-side when available, heuristic otherwise."""
from __future__ import annotations

import json

MESSAGE_OVERHEAD = 8  # chat-template markers added around each message
_CACHE_LIMIT = 1024


def estimate_tokens(value) -> int:
    """Heuristic fallback: ~4 characters per token over the JSON form."""
    return max(1, (len(json.dumps(value, ensure_ascii=False)) + 3) // 4)


class TokenCounter:
    """Callable counter that prefers the provider's tokenizer and falls back to the heuristic.

    The provider may expose ``count_tokens(text) -> int | None``. The first failure disables
    the server path for this counter so an unreachable server cannot slow every request.
    """

    def __init__(self, provider=None):
        self._tokenize = getattr(provider, "count_tokens", None)
        self._count_prompt = getattr(provider, "count_prompt", None)
        self._cache: dict[str, int] = {}
        self.server_enabled = callable(self._tokenize)
        self.template_enabled = callable(self._count_prompt)

    def _text(self, text: str) -> int:
        if not self.server_enabled:
            return estimate_tokens(text)
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        try:
            count = self._tokenize(text)
        except Exception:
            count = None
        if not isinstance(count, int) or count < 0:
            self.server_enabled = False
            return estimate_tokens(text)
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[text] = count
        return count

    def __call__(self, value) -> int:
        if isinstance(value, list) and value and all(isinstance(m, dict) and "role" in m for m in value):
            return max(1, sum(self._text(json.dumps(m.get("content", ""), ensure_ascii=False)) + MESSAGE_OVERHEAD
                              for m in value))
        return self._text(json.dumps(value, ensure_ascii=False)) if self.server_enabled else estimate_tokens(value)

    def count_prompt(self, messages: list[dict], tools: list[dict] | None = None) -> int:
        """Count the rendered chat prompt, including tool schemas, when the provider supports it."""
        payload = {"messages": messages, "tools": tools or None}
        key = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if self.template_enabled:
            try:
                count = self._count_prompt(messages, tools or None)
            except Exception:
                count = None
            if isinstance(count, int) and count >= 0:
                self._remember(key, count)
                return count
            # Avoid adding two failing HTTP requests to every fit attempt.
            self.template_enabled = False

        if tools:
            # The legacy tokenizer cannot see the rendered tool block or non-content fields.
            count = estimate_tokens(payload)
        else:
            count = self(messages)
        self._remember(key, count)
        return count

    def _remember(self, key: str, count: int) -> None:
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = count
