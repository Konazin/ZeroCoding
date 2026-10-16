
import json
import urllib.error
import urllib.request
from urllib.parse import urljoin

from .base import BaseProvider
from .base import ProviderTurn, ToolCall


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, api_key: str, api_url: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _post(self, endpoint, payload):
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI request failed: {exc.code} {exc.reason}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI-compatible connection failed: {exc.reason}") from exc

    def _get(self, endpoint):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI-compatible request failed: {exc.code} {exc.reason}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI-compatible connection failed: {exc.reason}") from exc

    def generate(self, prompt: str, **kwargs) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = self.chat(messages, **kwargs)
        return result.content if isinstance(result, ProviderTurn) else result

    def chat(self, messages, **kwargs):
        endpoint = urljoin(self.api_url + "/", "chat/completions")
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
            payload["tool_choice"] = "auto"
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]
        payload.update(self._request_parameters(kwargs))
        response = self._post(endpoint, payload)
        choice = response.get("choices", [{}])[0]
        if "message" in choice:
            message = choice["message"]
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
            reasoning_content = str(message.get("reasoning_content", "") or "")
            return ProviderTurn(
                content=message.get("content", "") or "",
                tool_calls=calls,
                usage=response.get("usage", {}),
                thinking_present=bool(reasoning_content),
                reasoning_content=reasoning_content,
            )
        return choice.get("text", "")

    def _request_parameters(self, kwargs) -> dict:
        """Provider-specific fields for compatible chat-completion APIs."""
        return {}

    def healthcheck(self) -> bool:
        try:
            self._get(urljoin(self.api_url + "/", "models"))
            return True
        except RuntimeError:
            return False

    def list_models(self) -> list[str]:
        data = self._get(urljoin(self.api_url + "/", "models"))
        return [model.get("id", "") for model in data.get("data", []) if model.get("id")]
