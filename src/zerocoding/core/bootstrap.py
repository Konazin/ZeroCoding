"""Assemble the optional extensions (plugins, hooks, MCP, subagent) around an Agent. Everything is opt-in."""
from __future__ import annotations

from pathlib import Path

from .extensions import Extensions
from .hooks import HookRunner, parse_hooks
from .plugins import load_plugins
from .subagent import make_explorer_tool
from ..mcp.manager import McpManager


def build_extensions(config, agent, root: str | Path, skills: list, metrics=None) -> Extensions:
    root = Path(root)
    policy = config.command_policy
    plugins = load_plugins(config.plugins_path, config.plugins_enabled)
    skills.extend(plugins.skills)
    agent.skills = skills

    hooks, hook_errors = parse_hooks(config.hooks, "config")
    for source, entries in plugins.hook_entries:
        extra, errors = parse_hooks(entries, source)
        hooks.extend(extra)
        hook_errors.extend(errors)
    runner = HookRunner(hooks, root, policy, hook_errors)
    agent.hooks = runner if (hooks or hook_errors) else None

    mcp_config = dict(config.mcp or {})
    mcp_config["servers"] = {**(mcp_config.get("servers") or {}), **plugins.mcp_servers}
    mcp = McpManager(mcp_config, root, policy)
    if mcp.configured and agent.tools is not None:
        for tool in mcp.start_all():
            agent.tools.register_external(tool)

    if config.subagents_enabled and agent.tools is not None:
        agent.tools.register_external(make_explorer_tool(agent))

    extensions = Extensions(metrics=metrics, hooks=runner, mcp=mcp, plugins=plugins.infos,
                            subagents_enabled=bool(config.subagents_enabled))
    agent.extensions = extensions
    return extensions


def startup_warnings(extensions: Extensions) -> list[str]:
    """One-line problems worth showing at launch (everything else lives in /mcp, /hooks, /plugins)."""
    lines = [f"Hook config: {e}" for e in (extensions.hooks.errors if extensions.hooks else [])]
    if extensions.mcp:
        lines += [f"MCP '{s.name}' {s.status}: {s.detail}" for s in extensions.mcp.states.values() if s.status != "ready"]
    for plugin in extensions.plugins:
        lines += [f"Plugin '{plugin.name}': {e}" for e in plugin.errors if plugin.enabled]
    return lines
