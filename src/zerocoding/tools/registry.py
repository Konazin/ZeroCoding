from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]
    confirmation: bool = False
    permission_scope: str = "external"
    sandbox_handler: Callable[[dict[str, Any]], Any] | None = None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        schemas = []
        used = 0
        for tool in self.list():
            schema = {"type": "function", "function": {
                "name": tool.name,
                "description": tool.description[:240],
                "parameters": tool.input_schema,
            }}
            cost = max(1, len(json.dumps(schema, ensure_ascii=False)) // 4)
            if len(schemas) >= 24 or used + cost > 1024:
                continue
            schemas.append(schema)
            used += cost
        return schemas


def format_tool_preview(tool: ToolSpec, arguments: dict[str, Any]) -> str:
    if tool.name == "write_file":
        content = arguments.get("content", "")
        return f"{arguments.get('path', '?')} ({len(content)} chars): {content[:180]!r}"
    value = json.dumps(arguments, ensure_ascii=False)
    return value if len(value) <= 320 else value[:317] + "..."
