from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentEvent:
    type: Literal["token", "tool_start", "tool_result", "approval_request", "approval_result", "done", "cancelled", "error", "metrics"]
    data: dict[str, Any] = field(default_factory=dict)
