from abc import ABC, abstractmethod
from typing import Generator


class BaseProvider(ABC):
    supports_tools = False
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError

    @abstractmethod
    def chat(self, messages, **kwargs):
        raise NotImplementedError

    def chat_stream(self, messages, **kwargs) -> Generator[str, None, None]:
        """Streaming opcional - providers podem implementar."""
        # Fallback: usa chat normal e retorna tudo de uma vez
        result = self.chat(messages, **kwargs)
        yield result

    def chat_with_tools(self, messages, tools, max_output_tokens=512):
        """Fallback for providers without native tool support."""
        return {"content": self.chat(messages, max_output_tokens=max_output_tokens), "tool_calls": []}

    def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
        result = self.chat_with_tools(messages, tools, max_output_tokens=max_output_tokens)
        if result.get("content"):
            yield {"content": result["content"]}
        yield {"tool_calls": result.get("tool_calls", [])}

    def healthcheck(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return []
