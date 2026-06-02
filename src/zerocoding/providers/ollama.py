import json
import urllib.error
import urllib.request
from urllib.parse import urljoin
from typing import Generator

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    def __init__(self, url: str, model: str, timeout: int = 300):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = 2

    def _post(self, endpoint, payload, stream=False):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            if stream:
                # Streaming response - retorna um generator
                return urllib.request.urlopen(request, timeout=self.timeout)
            else:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Ollama request failed: {exc.code} {exc.reason}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama connection failed: {exc.reason}\n\n"
                f"Verifique se o Ollama está rodando:\n  ollama serve"
            ) from exc

    def chat(self, messages, **kwargs):
        """Chat não-streaming (compatibilidade)."""
        endpoint = urljoin(self.url + "/", "v1/chat/completions")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": 4096,
                **kwargs.get("options", {}),
            },
        }
        response = self._post(endpoint, payload, stream=False)
        choice = response.get("choices", [{}])[0]
        if "message" in choice:
            return choice["message"].get("content", "")
        return choice.get("text", "")

    def chat_stream(self, messages, **kwargs) -> Generator[str, None, None]:
        """Chat com streaming - gera tokens um por um."""
        # Usa a API nativa do Ollama (/api/chat) para streaming
        endpoint = urljoin(self.url + "/", "api/chat")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": 4096,
                **kwargs.get("options", {}),
            },
        }

        response = self._post(endpoint, payload, stream=True)

        for line in response:
            line = line.decode("utf-8").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if "message" in data:
                    content = data["message"].get("content", "")
                    if content:
                        yield content
                # Verifica se terminou
                if data.get("done", False):
                    break
            except json.JSONDecodeError:
                continue