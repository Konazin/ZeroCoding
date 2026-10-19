from .openai_compatible import OpenAICompatibleProvider


class LlamaCppProvider(OpenAICompatibleProvider):
    """OpenAI-compatible client for llama.cpp's local HTTP server."""

    EFFORT_LEVELS = {"low", "medium", "high"}
    EXACT_TOKEN_COUNT = True
    REASONING_CONTROL = "budget"  # chat_template_kwargs.enable_thinking and reasoning_budget_tokens, per request

    def __init__(self, api_key: str, api_url: str, model: str, timeout: int = 300):
        super().__init__(api_key=api_key, api_url=api_url, model=model, timeout=timeout)

    def _wire_messages(self, messages):
        return messages

    def native_effort_kwargs(self, level: str) -> dict | None:
        level = str(level).lower()
        if level not in self.EFFORT_LEVELS:
            return None
        return {"reasoning_effort": level}

    def native_effort_status(self, level: str) -> str:
        if self.native_effort_kwargs(level):
            return "reasoning_effort sent; template-dependent, not validated (budgets are the real control)"
        return "budget only"

    def _request_parameters(self, kwargs) -> dict:
        # An explicit `thinking` setting wins over the effort level: both would steer the same template switch.
        setting = self._thinking(kwargs)
        if setting == "off":
            return {"chat_template_kwargs": {"enable_thinking": False}}
        if setting == "on":
            return {"chat_template_kwargs": {"enable_thinking": True}}
        if self.thinking_budget(setting) is not None:
            return {"reasoning_budget_tokens": self.thinking_budget(setting)}
        effort = kwargs.get("reasoning_effort")
        if effort in self.EFFORT_LEVELS:
            return {"reasoning_effort": effort}
        return {}

    def count_tokens(self, text: str) -> int | None:
        """Exact token count from the server's /tokenize endpoint, or None if unavailable."""
        root = self.api_url[:-3] if self.api_url.endswith("/v1") else self.api_url
        try:
            response = self._post(root.rstrip("/") + "/tokenize", {"content": text})
        except RuntimeError:
            return None
        tokens = response.get("tokens") if isinstance(response, dict) else None
        return len(tokens) if isinstance(tokens, list) else None

    def render_prompt(self, messages: list[dict], tools: list[dict] | None = None) -> str | None:
        """Render the same messages and tool schemas with the server's active chat template."""
        root = self.api_url[:-3] if self.api_url.endswith("/v1") else self.api_url
        payload = {"messages": messages, "add_generation_prompt": True}
        if tools:
            payload["tools"] = tools
        try:
            rendered = self._post(root.rstrip("/") + "/apply-template", payload)
        except RuntimeError:
            return None
        prompt = rendered.get("prompt") if isinstance(rendered, dict) else None
        return prompt if isinstance(prompt, str) else None

    def count_prompt(self, messages: list[dict], tools: list[dict] | None = None) -> int | None:
        """Count tokens after applying the server's chat template, including native tools."""
        prompt = self.render_prompt(messages, tools)
        return self.count_tokens(prompt) if prompt is not None else None
