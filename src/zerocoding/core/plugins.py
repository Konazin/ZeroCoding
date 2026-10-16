"""Declarative plugins (M6.4): a folder of skills + hooks + MCP server config. No plugin Python code is ever run.

Layout: <plugins_path>/<name>/{plugin.yaml, skills/*.md, hooks.yaml, mcp.yaml}. A plugin does nothing until its name
is listed in `plugins.enabled`. Enabling trusts its hooks and MCP servers exactly as if the user wrote them in the
config: they run under the same policies (CommandPolicy, allowlist, caps, approval).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..skills.loader import load_skills

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass
class PluginInfo:
    name: str
    path: Path
    description: str = ""
    version: str = ""
    enabled: bool = False
    skills: int = 0
    hooks: int = 0
    mcp_servers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class LoadedPlugins:
    infos: list[PluginInfo] = field(default_factory=list)
    skills: list = field(default_factory=list)
    hook_entries: list[tuple[str, list]] = field(default_factory=list)  # (source label, raw entries)
    mcp_servers: dict = field(default_factory=dict)


def _read_yaml(path: Path, errors: list[str]) -> dict:
    if not path.exists():
        return {}
    if yaml is None:
        errors.append(f"{path.name}: PyYAML is not installed")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{path.name}: {str(exc).splitlines()[0][:150]}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.name}: must be a mapping")
        return {}
    return data


def _substitute(value, plugin_dir: str):
    if isinstance(value, str):
        return value.replace("{plugin_dir}", plugin_dir)
    if isinstance(value, list):
        return [_substitute(v, plugin_dir) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, plugin_dir) for k, v in value.items()}
    return value


def load_plugins(plugins_path: str | Path, enabled: list[str]) -> LoadedPlugins:
    root = Path(plugins_path).expanduser()
    loaded = LoadedPlugins()
    wanted = {str(n) for n in enabled or []}
    found = set()
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            info = PluginInfo(name=folder.name, path=folder, enabled=folder.name in wanted)
            found.add(folder.name)
            if not NAME.match(folder.name):
                info.errors.append("folder name must match [a-z0-9_-] and be at most 40 characters")
                loaded.infos.append(info)
                continue
            meta = _read_yaml(folder / "plugin.yaml", info.errors)
            info.description, info.version = str(meta.get("description", "")), str(meta.get("version", ""))
            hooks_raw = _read_yaml(folder / "hooks.yaml", info.errors).get("hooks") or []
            mcp_raw = _read_yaml(folder / "mcp.yaml", info.errors).get("servers") or {}
            skills = load_skills(folder / "skills") if (folder / "skills").is_dir() else []
            info.skills, info.hooks = len(skills), len(hooks_raw) if isinstance(hooks_raw, list) else 0
            info.mcp_servers = sorted(mcp_raw) if isinstance(mcp_raw, dict) else []
            if info.enabled and not info.errors:
                for skill in skills:
                    skill.name = f"{folder.name}:{skill.name}"
                loaded.skills.extend(skills)
                if isinstance(hooks_raw, list) and hooks_raw:
                    loaded.hook_entries.append((f"plugin:{folder.name}", _substitute(hooks_raw, str(folder))))
                if isinstance(mcp_raw, dict):
                    for server, cfg in mcp_raw.items():
                        loaded.mcp_servers[f"{folder.name}_{server}"] = _substitute(cfg, str(folder))
            loaded.infos.append(info)
    for name in sorted(wanted - found):
        loaded.infos.append(PluginInfo(name=name, path=root / name, enabled=True,
                                       errors=[f"enabled but not found in {root}"]))
    return loaded
