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
    finish_reason: str = ""  # "stop", "length", "tool_calls"... as the backend reports it; "" when unknown
    reasoning_tokens: int = 0  # tokens the backend says went to private reasoning; 0 when not reported


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a backend can do, declared by the provider so the agent never has to guess."""
    context_window: int | None = None  # total tokens served; None when it cannot be detected
    exact_token_count: bool = False  # server-side tokenization of the real chat template
    native_tools: bool = True
    streaming: bool = False
    reasoning_control: str = "none"  # none | toggle (on/off) | budget (on/off and a token cap)

    def summary(self) -> str:
        window = f"{self.context_window} tokens" if self.context_window else "unknown"
        return (f"context window {window}; token count {'exact' if self.exact_token_count else 'estimated'}; "
                f"tools {'native' if self.native_tools else 'text fallback'}; streaming {'yes' if self.streaming else 'no'}; "
                f"reasoning control {self.reasoning_control}")


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
        finish_reason=str(response.get("finish_reason", "") or ""),
        reasoning_tokens=int(response.get("reasoning_tokens", 0) or 0),
        content=str(response.get("content", "") or ""),
        tool_calls=calls,
        usage=response.get("usage", {}) or {},
        thinking_present=bool(response.get("thinking_present", response.get("thinking")) or reasoning_content),
        reasoning_content=reasoning_content,
    )


class BaseProvider(ABC):
    EXACT_TOKEN_COUNT = False
    NATIVE_TOOLS = True
    STREAMING = False
    REASONING_CONTROL = "none"

    def capabilities(self, detect_window: bool = True) -> ProviderCapabilities:
        window = None
        if detect_window:  # may make a network call; `zc doctor` probes the server itself and passes False
            try:
                window = self.context_window()
            except Exception:
                window = None
        return ProviderCapabilities(window, self.EXACT_TOKEN_COUNT, self.NATIVE_TOOLS, self.STREAMING,
                                    self.REASONING_CONTROL)

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
