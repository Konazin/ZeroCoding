from .openai_compatible import OpenAICompatibleProvider


class LlamaCppProvider(OpenAICompatibleProvider):
    """OpenAI-compatible client for llama.cpp's local HTTP server."""

    EFFORT_LEVELS = {"low", "medium", "high"}

    def __init__(self, api_key: str, api_url: str, model: str, timeout: int = 300):
        super().__init__(api_key=api_key, api_url=api_url, model=model, timeout=timeout)

    def native_effort_kwargs(self, level: str) -> dict | None:
        level = str(level).lower()
        if level not in self.EFFORT_LEVELS:
            return None
        return {"reasoning_effort": level}

    def native_effort_status(self, level: str) -> str:
        if self.native_effort_kwargs(level):
            return "llama.cpp API; model template-dependent"
        return "budget only"

    def _request_parameters(self, kwargs) -> dict:
        effort = kwargs.get("reasoning_effort")
        if effort in self.EFFORT_LEVELS:
            return {"reasoning_effort": effort}
        return {}
