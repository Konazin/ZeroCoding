import json
import urllib.error
import urllib.request
from urllib.parse import urljoin
from typing import Generator

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    supports_tools = True
    def __init__(self, url: str, model: str, timeout: int = 300):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = 2
        self._active_response = None
        self.last_usage = None

    def cancel(self):
        if self._active_response:
            self._active_response.close()

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
                self._active_response = urllib.request.urlopen(request, timeout=self.timeout)
                return self._active_response
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

    def _get(self, endpoint):
        request = urllib.request.Request(endpoint, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Ollama request failed: {exc.code} {exc.reason}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama connection failed: {exc.reason}") from exc

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text with Ollama's native /api/generate endpoint."""
        endpoint = urljoin(self.url + "/", "api/generate")
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": 4096,
                "num_predict": kwargs.get("max_output_tokens", 512),
                **kwargs.get("options", {}),
            },
        }
        response = self._post(endpoint, payload, stream=False)
        return response.get("response", "")

    def healthcheck(self) -> bool:
        try:
            self._get(urljoin(self.url + "/", "api/tags"))
            return True
        except RuntimeError:
            return False

    def list_models(self) -> list[str]:
        data = self._get(urljoin(self.url + "/", "api/tags"))
        return [model.get("name", "") for model in data.get("models", []) if model.get("name")]

    def chat(self, messages, **kwargs):
        """Chat não-streaming usando a API nativa do Ollama."""
        endpoint = urljoin(self.url + "/", "api/chat")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": 4096,
                "num_predict": kwargs.get("max_output_tokens", 512),
                **kwargs.get("options", {}),
            },
        }
        response = self._post(endpoint, payload, stream=False)
        if "message" in response:
            return response["message"].get("content", "")
        return response.get("response", "")

    def chat_with_tools(self, messages, tools, max_output_tokens=512):
        endpoint = urljoin(self.url + "/", "api/chat")
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"num_ctx": 4096, "num_predict": max_output_tokens},
        }
        response = self._post(endpoint, payload, stream=False)
        message = response.get("message", {})
        return {"content": message.get("content", ""), "tool_calls": message.get("tool_calls", [])}

    def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
        endpoint = urljoin(self.url + "/", "api/chat")
        response = self._post(endpoint, {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": True,
            "options": {"num_ctx": 4096, "num_predict": max_output_tokens},
        }, stream=True)
        tool_calls = []
        try:
            for line in response:
                if not line.strip():
                    continue
                data = json.loads(line.decode("utf-8"))
                message = data.get("message", {})
                if message.get("content"):
                    yield {"content": message["content"]}
                if message.get("tool_calls"):
                    tool_calls = message["tool_calls"]
                if data.get("done"):
                    usage = {
                        "input_tokens": data.get("prompt_eval_count"),
                        "prefill_ms": round(data["prompt_eval_duration"] / 1_000_000, 1) if data.get("prompt_eval_duration") else None,
                        "output_tokens": data.get("eval_count"),
                        "generation_ms": round(data["eval_duration"] / 1_000_000, 1) if data.get("eval_duration") else None,
                        "total_ms": round(data["total_duration"] / 1_000_000, 1) if data.get("total_duration") else None,
                    }
                    usage = {key: value for key, value in usage.items() if value is not None}
                    if usage:
                        yield {"usage": usage}
                    break
            yield {"tool_calls": tool_calls}
        finally:
            response.close()
            self._active_response = None

    def chat_stream(self, messages, **kwargs) -> Generator[str, None, None]:
        """Chat com streaming - gera tokens um por um."""
        self.last_usage = None
        # Usa a API nativa do Ollama (/api/chat) para streaming
        endpoint = urljoin(self.url + "/", "api/chat")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": 4096,
                "num_predict": kwargs.get("max_output_tokens", 512),
                **kwargs.get("options", {}),
            },
        }

        response = self._post(endpoint, payload, stream=True)

        try:
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
                    if data.get("done", False):
                        usage = {
                            "input_tokens": data.get("prompt_eval_count"),
                            "prefill_ms": round(data["prompt_eval_duration"] / 1_000_000, 1) if data.get("prompt_eval_duration") else None,
                            "output_tokens": data.get("eval_count"),
                            "generation_ms": round(data["eval_duration"] / 1_000_000, 1) if data.get("eval_duration") else None,
                            "total_ms": round(data["total_duration"] / 1_000_000, 1) if data.get("total_duration") else None,
                        }
                        self.last_usage = {key: value for key, value in usage.items() if value is not None}
                        break
                except json.JSONDecodeError:
                    continue
        finally:
            response.close()
            self._active_response = None
