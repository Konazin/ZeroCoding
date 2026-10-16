"""Runtime extension state shared with the slash commands (metrics, hooks, MCP, plugins, subagents)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Extensions:
    metrics: object = None          # MetricsLog | None
    hooks: object = None            # HookRunner | None
    mcp: object = None              # McpManager | None
    plugins: list = field(default_factory=list)  # list[PluginInfo]
    subagents_enabled: bool = False
