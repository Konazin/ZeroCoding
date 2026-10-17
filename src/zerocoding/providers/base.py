from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)
    call_id: str = ""


@dataclass
class ProviderTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    thinking_present: bool = False
    reasoning_content: str = ""


def normalize_turn(response) -> ProviderTurn:
    if isinstance(response, ProviderTurn):
        return response
    if isinstance(response, str):
        return ProviderTurn(content=response)
    if not isinstance(response, dict):
        return ProviderTurn(content=str(response or ""))
    calls = []
    for item in response.get("tool_calls", []) or []:
        function = item.get("function", item) if isinstance(item, dict) else {}
        args = function.get("arguments", {})
        if isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except (TypeError, ValueError):
                args = {}
        calls.append(ToolCall(str(function.get("name", "")), args if isinstance(args, dict) else {}, str(item.get("id", ""))))
    reasoning_content = str(response.get("reasoning_content", "") or "")
    return ProviderTurn(
        content=str(response.get("content", "") or ""),
        tool_calls=calls,
        usage=response.get("usage", {}) or {},
        thinking_present=bool(response.get("thinking_present", response.get("thinking")) or reasoning_content),
        reasoning_content=reasoning_content,
    )


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
        turn = normalize_turn(result)
        yield turn.content

    def tool_result_message(self, call_id: str, name: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}

    def healthcheck(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return []

    def context_window(self) -> int | None:
        """Total context tokens the backend serves, or None when it cannot be detected."""
        return None

    def native_effort_kwargs(self, level: str) -> dict | None:
        """Return request fields only when this provider explicitly supports effort."""
        return None
