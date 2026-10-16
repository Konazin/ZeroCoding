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
        self._cache: dict[str, int] = {}
        self.server_enabled = callable(self._tokenize)

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
