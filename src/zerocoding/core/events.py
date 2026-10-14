"""Small UI-facing events emitted by the agent's tool loop."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    tool_name: str = ""
    target: str = ""
    summary: str = ""
    duration_seconds: float = 0.0

