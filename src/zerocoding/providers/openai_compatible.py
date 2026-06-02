
import json
import urllib.error
import urllib.request
from urllib.parse import urljoin

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, api_key: str, api_url: str, model: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI-compatible provider")
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model

    def _post(self, endpoint, payload):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI request failed: {exc.code} {exc.reason}: {message}") from exc

    def chat(self, messages, **kwargs):
        endpoint = urljoin(self.api_url + "/", "chat/completions")
        payload = {
            "model": self.model,
            "messages": messages,
            **kwargs,
        }
        response = self._post(endpoint, payload)
        choice = response.get("choices", [{}])[0]
        if "message" in choice:
            return choice["message"].get("content", "")
        return choice.get("text", "")
