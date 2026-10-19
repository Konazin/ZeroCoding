
import json
import urllib.error
import urllib.request
from urllib.parse import urljoin

from .base import BaseProvider
from .base import ProviderTurn, ToolCall


def _strip_inline_thinking(content: str) -> tuple[str, str]:
    """Remove DeepSeek-style inline thinking blocks from text returned as public content."""
    visible: list[str] = []
    private: list[str] = []
    cursor = 0
    while True:
        start = content.find("<think>", cursor)
        if start < 0:
            visible.append(content[cursor:])
            break
        visible.append(content[cursor:start])
        end = content.find("</think>", start + len("<think>"))
        if end < 0:
            private.append(content[start + len("<think>"):])
            break
        private.append(content[start + len("<think>"):end])
        cursor = end + len("</think>")
    return "".join(visible), "".join(private)


class _InlineThinkingFilter:
    """Stream-safe filter for inline ``<think>`` tags, including markers split across chunks."""

    START = "<think>"
    END = "</think>"

    def __init__(self):
        self.pending = ""
        self.private = False

    def feed(self, fragment: str) -> tuple[str, str]:
        data = self.pending + fragment
        self.pending = ""
        public: list[str] = []
        private: list[str] = []
        while data:
            marker = self.END if self.private else self.START
            marker_index = data.find(marker)
            if marker_index >= 0:
                segment = data[:marker_index]
                (private if self.private else public).append(segment)
                data = data[marker_index + len(marker):]
                self.private = not self.private
                continue
            hold = 0
            for size in range(min(len(marker) - 1, len(data)), 0, -1):
                if data.endswith(marker[:size]):
                    hold = size
                    break
            segment = data[:-hold] if hold else data
            (private if self.private else public).append(segment)
            self.pending = data[-hold:] if hold else ""
            break
        return "".join(public), "".join(private)

    def finish(self) -> tuple[str, str]:
        pending, self.pending = self.pending, ""
        return ("", pending) if self.private else (pending, "")


def _reasoning_tokens(usage) -> int:
    details = usage.get("completion_tokens_details") if isinstance(usage, dict) else None
    value = details.get("reasoning_tokens") if isinstance(details, dict) else 0
    return int(value) if isinstance(value, (int, float)) else 0


class OpenAICompatibleProvider(BaseProvider):
    STREAMING = True

    def __init__(self, api_key: str, api_url: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _wire_messages(self, messages):
        """Messages as sent on the wire. The OpenAI spec wants tool-call arguments as a JSON string;
        strict servers (Ollama) answer 400 to an object. LlamaCppProvider keeps objects because its
        chat templates read them as dicts."""
        wired = []
        for message in messages:
            calls = message.get("tool_calls")
            if calls:
                message = {**message, "tool_calls": [
                    {**call, "function": {**call.get("function", {}), "arguments": json.dumps(
                        call.get("function", {}).get("arguments", {}), ensure_ascii=False)
                        if not isinstance(call.get("function", {}).get("arguments"), str)
                        else call["function"]["arguments"]}}
                    for call in calls
                ]}
            wired.append(message)
        return wired

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
            "messages": self._wire_messages(messages),
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
            content, inline_reasoning = _strip_inline_thinking(str(message.get("content", "") or ""))
            reasoning_content = str(message.get("reasoning_content", "") or "")
            if inline_reasoning:
                reasoning_content += inline_reasoning
            usage = response.get("usage", {}) or {}
            return ProviderTurn(
                content=content,
                tool_calls=calls,
                usage=usage,
                thinking_present=bool(reasoning_content),
                reasoning_content=reasoning_content,
                finish_reason=str(choice.get("finish_reason") or ""),
                reasoning_tokens=_reasoning_tokens(usage),
            )
        return choice.get("text", "")

    def chat_stream_turn(self, messages, on_delta=None, cancel=None, **kwargs):
        """Read an OpenAI-compatible SSE turn and assemble text and fragmented tool calls."""
        endpoint = urljoin(self.api_url + "/", "chat/completions")
        payload = {"model": self.model, "messages": self._wire_messages(messages), "stream": True,
                   "stream_options": {"include_usage": True}}
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
            payload["tool_choice"] = "auto"
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]
        payload.update(self._request_parameters(kwargs))
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(
                {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            )},
            method="POST",
        )

        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI stream failed: {exc.code} {exc.reason}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI-compatible stream connection failed: {exc.reason}") from exc

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        thinking_filter = _InlineThinkingFilter()
        tool_parts: dict[int, dict[str, str]] = {}
        usage = {}
        finish_reason = ""
        try:
            for raw_line in response:
                if cancel:
                    cancel.check()
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage.update(chunk["usage"])
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                if choices[0].get("finish_reason"):
                    finish_reason = str(choices[0]["finish_reason"])
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    public, private = thinking_filter.feed(content)
                    if private:
                        reasoning_parts.append(private)
                    if public:
                        content_parts.append(public)
                        if on_delta:
                            on_delta(public)
                reasoning = delta.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    reasoning_parts.append(reasoning)
                for item in delta.get("tool_calls") or []:
                    if not isinstance(item, dict):
                        continue
                    index = int(item.get("index", 0))
                    current = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if item.get("id") and not current["id"]:
                        current["id"] = str(item["id"])
                    function = item.get("function") or {}
                    if isinstance(function.get("name"), str):
                        current["name"] += function["name"]
                    arguments = function.get("arguments")
                    if isinstance(arguments, str):
                        current["arguments"] += arguments
                    elif isinstance(arguments, dict):
                        current["arguments"] += json.dumps(arguments, ensure_ascii=False)
        finally:
            response.close()

        public, private = thinking_filter.finish()
        if private:
            reasoning_parts.append(private)
        if public:
            content_parts.append(public)
            if on_delta:
                on_delta(public)

        calls = []
        for index in sorted(tool_parts):
            part = tool_parts[index]
            try:
                arguments = json.loads(part["arguments"] or "{}")
            except ValueError:
                # Fragments that do not assemble into JSON must not run as an empty call; the agent
                # catches this, drops the partial text and repeats the turn without streaming.
                raise RuntimeError(f"stream produced malformed arguments for tool call {part['name']!r}")
            calls.append(ToolCall(part["name"], arguments if isinstance(arguments, dict) else {}, part["id"]))
        reasoning_content = "".join(reasoning_parts)
        return ProviderTurn(
            content="".join(content_parts),
            tool_calls=calls,
            usage=usage,
            thinking_present=bool(reasoning_content),
            reasoning_content=reasoning_content,
            finish_reason=finish_reason,
            reasoning_tokens=_reasoning_tokens(usage),
        )

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
