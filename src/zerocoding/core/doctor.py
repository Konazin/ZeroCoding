"""Read-only environment diagnostics for ``zc doctor``."""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .hooks import parse_hooks
from .plugins import load_plugins
from ..mcp.manager import McpManager


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str
    remedy: str = ""


def _root_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value[:-3] if value.endswith("/v1") else value


def _request_json(url: str, *, method="GET", payload=None, api_key="", timeout=3):
    headers = {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _writable_directory(path: Path) -> bool:
    candidate = path.expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def run_doctor(config, config_manager, workspace: str | Path | None = None,
               request: Callable = _request_json) -> list[Check]:
    """Inspect configuration and runtime dependencies without sending a model prompt."""
    root = Path(workspace or Path.cwd()).resolve()
    checks: list[Check] = []
    provider = config.active_provider
    provider_type = provider.type
    known_types = {"llama_cpp", "openai_compatible", "openai", "ollama"}

    if provider_type not in known_types:
        checks.append(Check("Provider config", "fail", f"Unknown provider type '{provider_type}'.",
                            "Set providers.<name>.type to llama_cpp, openai_compatible or ollama."))
    elif not provider.model.strip():
        checks.append(Check("Provider config", "fail", "Model name is empty.",
                            "Set providers.<name>.model in ~/.zerocoding/config.yaml."))
    else:
        checks.append(Check("Provider config", "ok", f"{config.provider} · {provider_type} · {provider.model}"))

    config_parent = config_manager.user_config_path.expanduser().parent
    checks.append(Check(
        "Config directory", "ok" if _writable_directory(config_parent) else "fail",
        f"Writable: {config_parent}" if _writable_directory(config_parent) else f"Not writable: {config_parent}",
        "Create the directory and grant the current user write access." if not _writable_directory(config_parent) else "",
    ))
    memory_path = Path(config.memory_path).expanduser()
    if not memory_path.is_absolute():
        memory_path = root / memory_path
    for label, directory in (("Workspace", root), ("Memory", memory_path.parent),
                             ("Metrics", root / ".zerocoding" / "metrics")):
        writable = _writable_directory(directory)
        checks.append(Check(label + " directory", "ok" if writable else "fail",
                            f"Writable: {directory}" if writable else f"Not writable: {directory}",
                            "Grant the current user write and execute access to this directory." if not writable else ""))

    skills_path = Path(config.skills_path).expanduser()
    if not skills_path.is_absolute():
        skills_path = root / skills_path
    if skills_path.is_dir() and os.access(skills_path, os.R_OK):
        checks.append(Check("Skills", "ok", f"Readable: {skills_path}"))
    else:
        checks.append(Check("Skills", "warn", f"Skills directory is missing or unreadable: {skills_path}",
                            "Set skills_path to an existing readable directory."))

    _, hook_errors = parse_hooks(config.hooks, "config")
    checks.append(Check("Hooks", "fail" if hook_errors else "ok",
                        "; ".join(hook_errors) if hook_errors else f"{len(config.hooks)} configured hook(s) valid.",
                        "Fix the listed hook entries in ~/.zerocoding/config.yaml." if hook_errors else ""))

    plugins = load_plugins(config.plugins_path, config.plugins_enabled)
    plugin_errors = [f"{plugin.name}: {error}" for plugin in plugins.infos if plugin.enabled for error in plugin.errors]
    checks.append(Check("Plugins", "fail" if plugin_errors else "ok",
                        "; ".join(plugin_errors) if plugin_errors else
                        f"{len(config.plugins_enabled)} enabled plugin(s) valid.",
                        "Fix or disable the listed plugins." if plugin_errors else ""))

    if provider_type == "llama_cpp":
        root_url = _root_url(provider.base_url)
        try:
            health = request(root_url + "/health", api_key=provider.resolved_api_key())
            healthy = health == "ok" or (isinstance(health, dict) and health.get("status") in {"ok", "ready"})
            checks.append(Check("Server health", "ok" if healthy else "fail", str(health)[:200],
                                "Start llama-server and check the configured base_url." if not healthy else ""))
        except Exception as exc:
            checks.append(Check("Server health", "fail", str(exc)[:240],
                                f"Start llama-server at {root_url} and confirm /health responds."))

        try:
            value = request(root_url + "/props", api_key=provider.resolved_api_key())
            if isinstance(value, dict):
                settings = value.get("default_generation_settings") or {}
                n_ctx = settings.get("n_ctx")
                total_slots = value.get("total_slots")
                alias = value.get("model_alias")
                if alias is None:
                    alias = value.get("model_path")
                checks.append(Check("Server properties", "ok", "Received /props."))
                if alias and str(alias) != provider.model:
                    checks.append(Check("Model alias", "warn", f"Server reports '{alias}', config expects '{provider.model}'.",
                                        "Start llama-server with --alias matching providers.<name>.model."))
                else:
                    checks.append(Check("Model alias", "ok", str(alias or provider.model)))
                if total_slots is None:
                    checks.append(Check("Slots", "warn", "Server did not report total_slots.",
                                        "Check the llama-server startup configuration; use -np 1 for the target machine."))
                elif int(total_slots) != 1:
                    checks.append(Check("Slots", "warn", f"Server has {total_slots} slots.",
                                        "Use -np 1 for the single-user target configuration."))
                else:
                    checks.append(Check("Slots", "ok", "1 slot."))
                if n_ctx is None:
                    checks.append(Check("Context size", "warn", "Server did not report n_ctx.",
                                        "Check the llama-server context setting."))
                elif int(n_ctx) < config.max_input_tokens + config.max_output_tokens:
                    checks.append(Check("Context size", "fail",
                                        f"n_ctx={n_ctx}, below input+output budget {config.max_input_tokens + config.max_output_tokens}.",
                                        "Raise the server context or reduce the configured input/output budgets."))
                else:
                    checks.append(Check("Context size", "ok", f"n_ctx={n_ctx}."))
                caps = value.get("chat_template_caps") or {}
                supported = caps.get("supports_reasoning_effort")
                if supported is False:
                    checks.append(Check("Reasoning effort", "warn", "Template does not declare native reasoning_effort support.",
                                        "Effort currently changes local output and tool-round budgets only."))
                elif supported is True:
                    checks.append(Check("Reasoning effort", "ok", "Template declares native support."))
                else:
                    checks.append(Check("Reasoning effort", "warn", "Server did not report native reasoning_effort support.",
                                        "Treat Effort as local budgets until the template declares support."))
            else:
                checks.append(Check("Server properties", "warn", "Unexpected /props response.",
                                    "Update llama.cpp or check the configured server endpoint."))
        except Exception as exc:
            checks.append(Check("Server properties", "warn", str(exc)[:240],
                                "Update llama.cpp and confirm GET /props is available."))

        try:
            tokenized = request(root_url + "/tokenize", method="POST", payload={"content": "zc doctor token check"},
                                api_key=provider.resolved_api_key())
            ok = isinstance(tokenized, dict) and isinstance(tokenized.get("tokens"), list)
            checks.append(Check("Tokenizer", "ok" if ok else "warn",
                                f"/tokenize returned {len(tokenized['tokens'])} token(s)." if ok else "Unexpected /tokenize response.",
                                "Check llama.cpp /tokenize; ZeroCoding will use its heuristic fallback." if not ok else ""))
        except Exception as exc:
            checks.append(Check("Tokenizer", "warn", str(exc)[:240],
                                "Enable/update llama.cpp /tokenize; ZeroCoding will use its heuristic fallback."))

        template_messages = [{"role": "user", "content": "zc doctor template check"}]
        try:
            rendered = request(root_url + "/apply-template", method="POST",
                               payload={"messages": template_messages, "add_generation_prompt": True,
                                        "tools": [{"type": "function", "function": {"name": "zc_doctor_probe",
                                                  "description": "Check template tool rendering", "parameters": {"type": "object", "properties": {}}}}]},
                               api_key=provider.resolved_api_key())
            ok = isinstance(rendered, dict) and isinstance(rendered.get("prompt"), str)
            checks.append(Check("Chat template", "ok" if ok else "warn",
                                "Rendered a message with a tool schema." if ok else "Unexpected /apply-template response.",
                                "Update llama.cpp; exact prompt-token accounting will be unavailable." if not ok else ""))
        except Exception as exc:
            checks.append(Check("Chat template", "warn", str(exc)[:240],
                                "Update llama.cpp and confirm POST /apply-template is available."))
    elif provider_type in known_types:
        try:
            from ..core.router import build_provider
            healthy = build_provider(config).healthcheck()
            checks.append(Check("Provider health", "ok" if healthy else "fail",
                                "Provider responded." if healthy else "Provider did not respond.",
                                "Check provider URL, credentials and service status." if not healthy else ""))
        except Exception as exc:
            checks.append(Check("Provider health", "fail", str(exc)[:240],
                                "Check provider type, URL, credentials and service status."))

    if provider_type in known_types:
        try:
            from ..core.router import build_provider
            capabilities = build_provider(config).capabilities(detect_window=False)
            checks.append(Check("Provider capabilities", "ok", capabilities.summary()))
            built = build_provider(config)
            problem = built.thinking_support_problem()
            if built.thinking != "auto":
                checks.append(Check("Thinking", "warn" if problem else "ok",
                                    f"thinking: {built.thinking}" + (f" — {problem}." if problem else ""),
                                    "Use a provider type that controls reasoning, or set thinking: auto." if problem else ""))
            if provider_type != "ollama" and ":11434" in str(provider.base_url):
                checks.append(Check("Ollama endpoint", "warn",
                                    "Ollama's /v1 endpoint ignores the context size ZeroCoding requests.",
                                    "Set providers.<name>.type to ollama (native API) or set context_window explicitly."))
        except Exception as exc:
            checks.append(Check("Provider capabilities", "warn", str(exc)[:240]))

    mcp_config = dict(config.mcp or {})
    mcp = McpManager(mcp_config, root, config.command_policy)
    if not mcp.configured:
        checks.append(Check("MCP", "skip", "No MCP servers configured."))
    else:
        try:
            mcp.start_all()
            failed = [state for state in mcp.states.values() if state.status in {"failed", "refused"}]
            detail = "; ".join(f"{state.name}: {state.status} — {state.detail}" for state in failed)
            checks.append(Check("MCP", "warn" if failed else "ok",
                                detail or f"{len(mcp.tools)} allowlisted tool(s) available.",
                                "Fix server command, allowlist or schema caps in the MCP config." if failed else ""))
        finally:
            mcp.close()
    return checks


def print_report(checks, console=None) -> int:
    if console is None:
        from rich.console import Console
        console = Console()
    symbols = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "–"}
    colors = {"ok": "green", "warn": "yellow", "fail": "red", "skip": "dim"}
    for check in checks:
        console.print(f"[{colors[check.status]}]{symbols[check.status]} {check.name}[/]: {check.detail}")
        if check.remedy:
            console.print(f"  Fix: {check.remedy}", style="dim")
    failures = sum(check.status == "fail" for check in checks)
    warnings = sum(check.status == "warn" for check in checks)
    console.print(f"\n{len(checks)} checks · {failures} blocking · {warnings} warning(s)")
    return 1 if failures else 0
