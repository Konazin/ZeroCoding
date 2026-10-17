"""Token counting for prompt budgets: server-side when available, heuristic otherwise."""
from __future__ import annotations

import json
import re

MESSAGE_OVERHEAD = 8  # chat-template markers added around each message
_CACHE_LIMIT = 1024


def estimate_tokens(value) -> int:
    """Heuristic fallback: ~4 characters per token over the JSON form."""
    return max(1, (len(json.dumps(value, ensure_ascii=False)) + 3) // 4)


_PIECE = re.compile(r"\w+|[^\w\s]")
# Least-squares fit against llama-server /apply-template + /tokenize on 160 varied prompts built from this
# repository (code, docs, config; 1-14 messages; with and without tool schemas). See docs/m7-token-fallback.md.
_PER_PIECE = 0.998
_PER_MESSAGE = 3.826
_PER_TOOL_PIECE = 0.506
_TOOLS_FIXED = 272.344


def _pieces(value) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    # Long unbroken runs (hashes, minified text) split into several tokens, so weigh by length.
    return sum(max(1, -(-len(piece) // 6)) for piece in _PIECE.findall(text))


def estimate_prompt_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    """Calibrated fallback for the rendered chat prompt when the server cannot count it.

    Counts word and punctuation pieces rather than characters, which tracks BPE tokenizers across
    code and prose, plus per-message template markers and the tool-instruction block.
    """
    pieces = sum(_pieces(m.get("content", "")) + _pieces(m["tool_calls"]) if m.get("tool_calls")
                 else _pieces(m.get("content", "")) for m in messages)
    total = _PER_PIECE * pieces + _PER_MESSAGE * len(messages)
    if tools:
        total += _PER_TOOL_PIECE * _pieces(tools) + _TOOLS_FIXED
    return max(1, round(total))


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

        if self.server_enabled and not tools:
            count = self(messages)  # tokenizer-only servers still count message text exactly
        else:
            count = estimate_prompt_tokens(messages, tools)
        self._remember(key, count)
        return count

    def _remember(self, key: str, count: int) -> None:
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = count
