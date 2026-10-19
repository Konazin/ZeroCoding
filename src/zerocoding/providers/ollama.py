"""LEGACY provider for native Ollama endpoints.

Kept for compatibility with existing configs only. The supported runtime is llama.cpp
(`llama_cpp.py`); this module is not exercised against a real Ollama server and receives
no new features. Known limitation: when the caller omits `num_ctx`/`max_tokens` it falls
back to its own defaults instead of the agent budgets.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urljoin
from typing import Generator

from .base import BaseProvider
from .base import ProviderTurn, ToolCall


class OllamaProvider(BaseProvider):
    REASONING_CONTROL = "toggle"  # the native `think` boolean
    def __init__(self, url: str, model: str, timeout: int = 300):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = 2

    def tool_result_message(self, call_id: str, name: str, content: str) -> dict:
        return {"role": "tool", "content": content}

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
            "tools": kwargs.get("tools"),
            "options": {
                "num_ctx": kwargs.get("num_ctx", 5120),
                "num_predict": kwargs.get("max_tokens", 1024),
                **kwargs.get("options", {}),
            },
        }
        if kwargs.get("think") is not None:
            payload["think"] = kwargs["think"]
        if not payload["tools"]:
            payload.pop("tools")
        response = self._post(endpoint, payload, stream=False)
        if "message" in response:
            message = response["message"]
            calls = []
            for item in message.get("tool_calls", []) or []:
                fn = item.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                calls.append(ToolCall(fn.get("name", ""), args if isinstance(args, dict) else {}, item.get("id", "")))
            usage = {}
            for source_key, usage_key in (
                ("prompt_eval_count", "prompt_tokens"),
                ("eval_count", "completion_tokens"),
                ("prompt_eval_duration", "prompt_eval_duration_ns"),
                ("eval_duration", "eval_duration_ns"),
                ("total_duration", "total_duration_ns"),
                ("load_duration", "load_duration_ns"),
            ):
                value = response.get(source_key)
                if isinstance(value, (int, float)):
                    usage[usage_key] = value
            done_reason = response.get("done_reason")
            if isinstance(done_reason, str):
                usage["done_reason"] = done_reason
            return ProviderTurn(
                content=message.get("content", ""),
                tool_calls=calls,
                usage=usage,
                thinking_present=bool(message.get("thinking")),
                finish_reason=done_reason if isinstance(done_reason, str) else "",
            )
        return response.get("response", "")

    def chat_stream(self, messages, **kwargs) -> Generator[str, None, None]:
        """Chat com streaming - gera tokens um por um."""
        # Usa a API nativa do Ollama (/api/chat) para streaming
        endpoint = urljoin(self.url + "/", "api/chat")
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "num_ctx": kwargs.get("num_ctx", 5120),
                "num_predict": kwargs.get("max_tokens", 1024),
                **kwargs.get("options", {}),
            },
        }
        if kwargs.get("think") is not None:
            payload["think"] = kwargs["think"]

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
