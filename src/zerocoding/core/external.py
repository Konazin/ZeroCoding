"""Shape of an extension tool registered in ToolRegistry (MCP tools, subagent tools)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ExternalTool:
    name: str            # name exposed to the model
    server: str          # origin label shown in approval previews (MCP server name, "subagent")
    tool: str            # origin tool name
    spec: dict           # OpenAI-style function spec (kept compact)
    read_only: bool      # read-only tools skip the approval prompt and stay available in Plan mode
    handler: Callable[[dict], str]
