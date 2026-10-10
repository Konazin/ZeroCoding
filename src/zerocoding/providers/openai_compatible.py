
import json
import urllib.error
import urllib.request
from urllib.parse import urljoin

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    supports_tools = True
    def __init__(self, api_key: str, api_url: str, model: str):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model
        self._active_response = None

    def cancel(self):
        if self._active_response:
            self._active_response.close()

    def _post(self, endpoint, payload, stream=False):
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
            if stream:
                self._active_response = urllib.request.urlopen(request, timeout=30)
                return self._active_response
            with urllib.request.urlopen(request, timeout=30) as response:
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
        return self.chat(messages, **kwargs)

    def chat(self, messages, **kwargs):
        endpoint = urljoin(self.api_url + "/", "chat/completions")
        payload = {
            "model": self.model,
            "messages": messages,
            **{k: v for k, v in kwargs.items() if k != "max_output_tokens"},
            "max_tokens": kwargs.get("max_output_tokens", kwargs.get("max_tokens", 512)),
        }
        response = self._post(endpoint, payload)
        choice = response.get("choices", [{}])[0]
        if "message" in choice:
            return choice["message"].get("content", "")
        return choice.get("text", "")

    def chat_with_tools(self, messages, tools, max_output_tokens=512):
        endpoint = urljoin(self.api_url + "/", "chat/completions")
        response = self._post(endpoint, {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": max_output_tokens,
        })
        message = response.get("choices", [{}])[0].get("message", {})
        return {"content": message.get("content") or "", "tool_calls": message.get("tool_calls", [])}

    def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
        endpoint = urljoin(self.api_url + "/", "chat/completions")
        response = self._post(endpoint, {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_output_tokens,
        }, stream=True)
        tool_calls = {}
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if data.get("usage"):
                    yield {"usage": data["usage"]}
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    yield {"content": delta["content"]}
                for item in delta.get("tool_calls", []):
                    index = item.get("index", 0)
                    call = tool_calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if item.get("id"):
                        call["id"] = item["id"]
                    function = item.get("function", {})
                    call["function"]["name"] += function.get("name", "")
                    call["function"]["arguments"] += function.get("arguments", "")
            yield {"tool_calls": [tool_calls[index] for index in sorted(tool_calls)]}
        finally:
            response.close()
            self._active_response = None

    def healthcheck(self) -> bool:
        try:
            self._get(urljoin(self.api_url + "/", "models"))
            return True
        except RuntimeError:
            return False

    def list_models(self) -> list[str]:
        data = self._get(urljoin(self.api_url + "/", "models"))
        return [model.get("id", "") for model in data.get("data", []) if model.get("id")]
