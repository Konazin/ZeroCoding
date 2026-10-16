"""Read-only explorer subagent (M6.3): a fresh context that investigates the project and returns a short summary.

Sequential (one model, one slot), no nesting, no writes/commands/MCP, own small budgets. It saves the main
conversation's context, not time. Disabled by default (`subagents.enabled`).
"""
from __future__ import annotations

from .external import ExternalTool
from .tools import ToolRegistry

EXPLORER_NAME = "explore"
MAX_SUMMARY_CHARS = 1200
EXPLORER_PROMPT = (
    "You are an exploration helper for a coding agent. Investigate the project with the read-only tools and "
    "reply with a concise summary (under 150 words): relevant file paths with line numbers and the facts asked. "
    "Do not propose edits and do not ask questions."
)
SPEC = {"type": "function", "function": {
    "name": EXPLORER_NAME,
    "description": "Delegate a read-only investigation of the project to a helper with its own context; returns a short summary.",
    "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"], "additionalProperties": False},
}}


def make_explorer_tool(agent) -> ExternalTool:
    def explore(arguments: dict) -> str:
        from .agent import Agent  # local import: Agent imports tools, tools must not import Agent

        task = str(arguments.get("task", "")).strip()
        if not task:
            raise ValueError("task must not be empty")
        registry = ToolRegistry(agent.tools.root, approve=None, policy=agent.tools.policy)  # built-in tools only: no explore inside explore
        sub = Agent(agent.provider, max_input_tokens=agent.max_input_tokens, max_output_tokens=1024,
                    max_tool_rounds=4, tools=registry, plan_mode=True)
        answer = sub.ask(task, system_prompt=EXPLORER_PROMPT, use_tools=True).strip()
        for key in ("llm_calls", "prompt_tokens", "completion_tokens"):
            agent._stats[key] += sub.last_turn.get(key, 0)
        agent._stats["subagent_runs"] = agent._stats.get("subagent_runs", 0) + 1
        if len(answer) > MAX_SUMMARY_CHARS:
            answer = answer[:MAX_SUMMARY_CHARS] + "…"
        return f"[Explorer summary]\n{answer}"

    return ExternalTool(name=EXPLORER_NAME, server="subagent", tool=EXPLORER_NAME, spec=SPEC, read_only=True, handler=explore)
