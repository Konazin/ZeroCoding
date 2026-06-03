from abc import ABC, abstractmethod
from typing import Generator


class BaseProvider(ABC):
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

    def healthcheck(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return []
