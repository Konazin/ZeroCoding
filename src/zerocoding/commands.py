"""Slash-command handlers and session-state helpers for the interactive CLI."""
from pathlib import Path

from .core.config import ProviderConfig
from .core.router import build_provider, build_session_provider


def handle_command(command, tui, agent, config, manager, skills, project_context, session_manager, session):
    name, *args = command.strip().split()
    name = name.lower()
    args_text = " ".join(args)

    if name in {"/exit", "/quit", "/q"}:
        return True, None, session
    if name == "/clear":
        tui.clear()
        return False, None, session
    if name == "/help":
        tui.show_help()
        return False, None, session
    if name in {"/skills", "/skill"}:
        handle_skill(name, args_text, tui, agent, skills)
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, None, session
    if name in {"/plan", "/ultrathink"}:
        attribute = "plan_mode" if name == "/plan" else "ultrathink"
        label = "Plan" if name == "/plan" else "Ultra"
        current = getattr(agent, attribute)
        requested = args[0].lower() if args else "toggle"
        if len(args) > 1 or requested not in {"toggle", "on", "off"}:
            tui.show_error(f"Usage: {name} [on|off]")
            return False, None, session
        enabled = not current if requested == "toggle" else requested == "on"
        agent.set_session_controls(**{attribute: enabled})
        session.plan_mode = agent.plan_mode
        session.ultrathink = agent.ultrathink
        save_session_state(session_manager, session, config, agent, project_context)
        refresh_tui_state(tui, config, agent, session=session)
        sync_tui_runtime(tui, agent)
        tui.show_success(f"{label} mode {'enabled' if enabled else 'disabled'}.")
        return False, None, session
    if name == "/effort":
        if not args:
            tui.show_info(f"Effort: {agent.effort.title()} (use /effort low|medium|high)")
            return False, None, session
        effort = args[0].lower()
        if effort not in {"low", "medium", "high"} or len(args) > 1:
            tui.show_error("Usage: /effort [low|medium|high]")
            return False, None, session
        agent.set_session_controls(effort=effort)
        session.effort = effort
        save_session_state(session_manager, session, config, agent, project_context)
        refresh_tui_state(tui, config, agent, session=session)
        sync_tui_runtime(tui, agent)
        tui.show_success(f"Effort set to {effort.title()}.")
        return False, None, session
    if name == "/provider":
        if args_text.strip() == "test":
            ok = agent.provider.healthcheck()
            if ok:
                tui.connection_status = "connected"
                tui.show_success(f"Provider {session.provider} is connected.")
            else:
                tui.connection_status = "offline"
                tui.show_error(f"Provider {session.provider} is offline.")
            return False, None, session
        provider = handle_provider(args_text, tui, config, manager, active_provider=session.provider)
        if provider is not None:
            session.provider = config.provider
            session.model = config.model
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, provider, session
    if name == "/model":
        provider = handle_model(args_text, tui, config, agent, session)
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, provider, session
    if name == "/mode":
        provider = handle_mode(args_text, tui, config, agent, session)
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, provider, session
    if name == "/context":
        handle_context(args, tui, project_context)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, None, session
    if name == "/read":
        handle_read(args_text, tui, project_context)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, None, session
    if name == "/tree":
        handle_tree(tui, project_context)
        return False, None, session
    if name == "/grep":
        handle_grep(args_text, tui, project_context)
        return False, None, session
    if name == "/sessions":
        handle_sessions(tui, session_manager)
        return False, None, session
    if name == "/session":
        handle_session(tui, session, agent, project_context)
        return False, None, session
    if name == "/resume":
        provider, session = handle_resume(args_text, tui, agent, config, manager, project_context, session_manager, skills)
        refresh_tui_state(tui, config, agent, session=session)
        return False, provider, session
    if name == "/new":
        session, provider = handle_new(tui, agent, config, project_context, session_manager)
        refresh_tui_state(tui, config, agent, session=session)
        sync_tui_runtime(tui, agent)
        tui.clear()
        tui.show_success(f"New session: {session.id}")
        return False, provider, session
    if name == "/config":
        provider = handle_config(args, tui, config, manager)
        if provider is not None:
            session.provider = config.provider
            session.model = config.model
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, provider, session
    if name == "/health":
        ok = agent.provider.healthcheck()
        if ok:
            tui.show_success(f"Provider {session.provider} is connected.")
            tui.connection_status = "connected"
        else:
            tui.show_error(f"Provider {session.provider} is offline.")
            tui.connection_status = "offline"
        return False, None, session
    if name == "/status":
        tui.show_status()
        return False, None, session
    if name == "/metrics":
        handle_metrics(tui, agent)
        return False, None, session
    if name in {"/mcp", "/hooks", "/plugins"}:
        handle_extension_info(name, tui, agent)
        return False, None, session

    tui.show_error(f"Comando desconhecido: {command}")
    return False, None, session


def handle_skill(name, args_text, tui, agent, skills):
    parts = args_text.split()
    action = parts[0].lower() if parts else ""
    value = " ".join(parts[1:])

    if name == "/skills" or not args_text:
        tui.show_skills(skills)
        return

    if action == "add" and value:
        if agent.add_skill(value):
            tui.show_success(f"Skill activated: {value}")
        else:
            tui.show_error(f"Skill not found: {value}")
        return
    if action == "remove" and value:
        if agent.remove_skill(value):
            tui.show_success(f"Skill removida: {value}")
        else:
            tui.show_error(f"Skill was not active: {value}")
        return
    if action == "active":
        active = agent.active_skill_names()
        tui.show_info("Active skills: " + (", ".join(active) if active else "none"))
        return
    if action == "clear":
        agent.clear_skills()
        tui.show_success("Active skills cleared.")
        return

    if agent.add_skill(args_text):
        tui.show_success(f"Skill activated: {args_text}")
    else:
        tui.show_error(f"Skill not found: {args_text}")


def handle_provider(args_text, tui, config, manager, active_provider=None):
    parts = args_text.split()
    action = parts[0].lower() if parts else ""

    if not args_text:
        tui.show_info("Configured providers:")
        for name, provider in config.providers.items():
            marker = "*" if name == (active_provider or config.provider) else " "
            tui.show_info(f"{marker} {name} ({provider.type}) {provider.base_url} / {provider.model}")
        tui.show_info("Use /provider use name or /provider add name type base_url model")
        return None

    if action == "use" and len(parts) >= 2:
        args_text = parts[1]
    elif action == "add" and len(parts) >= 5:
        name, provider_type, base_url, model = parts[1], parts[2], parts[3], " ".join(parts[4:])
        config.providers[name] = ProviderConfig(name=name, type=provider_type, base_url=base_url, model=model)
        config.provider = name
        manager.save(config)
        tui.provider_name = config.provider
        tui.model = config.model
        tui.show_success(f"Provider saved: {name}")
        return build_provider(config)
    elif action == "remove" and len(parts) >= 2:
        provider_name = parts[1]
        if provider_name in {config.provider, active_provider}:
            tui.show_error("Switch to another provider before removing an active provider.")
            return None
        if config.providers.pop(provider_name, None):
            manager.save(config)
            tui.show_success(f"Provider removed: {provider_name}")
        else:
            tui.show_error(f"Provider not found: {provider_name}")
        return None
    if args_text not in config.providers:
        tui.show_error(f"Provider not found: {args_text}")
        return None

    config.provider = args_text
    manager.save(config)
    tui.provider_name = config.provider
    tui.model = config.model
    tui.show_success(f"Provider set to {config.provider}.")
    return build_provider(config)


def handle_model(args_text, tui, config, agent, session):
    parts = args_text.split()
    action = parts[0].lower() if parts else ""
    if not args_text or action == "list":
        try:
            models = agent.provider.list_models()
        except Exception as exc:
            tui.show_error(str(exc))
            return
        if not models:
            tui.show_info("The provider returned no models.")
            return
        tui.show_info("Available models:")
        for model in models:
            tui.show_info(f"- {model}")
        return None

    if action == "use" and len(parts) >= 2:
        args_text = " ".join(parts[1:])
    elif action == "use":
        tui.show_error("Usage: /model use model-name")
        return None

    session.model = args_text
    tui.model = args_text
    tui.show_success(f"Session model set to {args_text}.")
    return build_session_provider(config, session.provider, session.model)


def handle_mode(args_text, tui, config, agent, session):
    if not args_text:
        tui.show_info("Configured modes:")
        for name, mode in config.modes.items():
            marker = "*" if name == session.mode else " "
            tui.show_info(f"{marker} {name}: {mode.provider} / {mode.model}")
        return None

    if args_text not in config.modes:
        tui.show_error(f"Mode not found: {args_text}")
        return None

    mode = config.modes[args_text]
    if mode.provider not in config.providers:
        tui.show_error(f"Mode provider not found: {mode.provider}")
        return None

    session.mode = args_text
    session.provider = mode.provider
    session.model = mode.model
    agent.set_active_skills(mode.skills)
    effort_by_builtin_mode = {"code": "medium", "fast": "low", "reason": "high", "smart": "high"}
    if args_text in effort_by_builtin_mode:
        agent.set_session_controls(effort=effort_by_builtin_mode[args_text])
        session.effort = agent.effort
    session.skills = agent.active_skill_names()
    tui.show_success(f"Mode set to {args_text} for this session.")
    return build_session_provider(config, session.provider, session.model)


def handle_context(args, tui, project_context):
    if not args:
        paths = project_context.tree()
        tui.show_info("Context: " + (", ".join(paths) if paths else "empty"))
        return

    action = args[0].lower()
    value = " ".join(args[1:])
    try:
        if action == "add" and value:
            item = project_context.add(value)
            tui.render_tool_call("Read", item.path)
            tui.render_tool_done(1, item.tokens, 0.0)
            return
        if action == "remove" and value:
            if project_context.remove(value):
                tui.show_success(f"Removed from context: {value}")
            else:
                tui.show_error(f"File was not in context: {value}")
            return
        if action == "clear":
            project_context.clear()
            tui.show_success("Context cleared.")
            return
        if action == "tree":
            paths = project_context.tree()
            if not paths:
                tui.show_info("Context is empty.")
            for path in paths:
                tui.show_info(f"- {path}")
            return
    except Exception as exc:
        tui.show_error(str(exc))
        return

    tui.show_error("Usage: /context | /context add path | /context remove path | /context clear | /context tree")


def handle_read(args_text, tui, project_context):
    if not args_text:
        tui.show_error("Usage: /read path")
        return
    try:
        item = project_context.add(args_text)
    except Exception as exc:
        tui.show_error(str(exc))
        return
    tui.render_tool_call("Read", item.path)
    tui.show_info(item.content)
    tui.render_tool_done(1, item.lines, 0.0)


def handle_tree(tui, project_context):
    files = project_context.list_project_files()
    if not files:
        tui.show_info("No files found.")
    for path in files:
        tui.show_info(path)


def handle_grep(args_text, tui, project_context):
    if not args_text:
        tui.show_error("Usage: /grep pattern")
        return
    try:
        results = project_context.grep(args_text)
    except Exception as exc:
        tui.show_error(str(exc))
        return
    if not results:
        tui.show_info("No results.")
    for path, lineno, line in results:
        tui.show_info(f"{path}:{lineno}: {line}")


def handle_sessions(tui, session_manager):
    sessions = session_manager.list_recent()
    if not sessions:
        tui.show_info("No saved sessions.")
        return
    for session in sessions:
        tui.show_info(f"{session.id}  {session.provider}/{session.model}  mode:{session.mode}  {session.path}")


def handle_session(tui, session, agent, project_context):
    tui.show_info(f"Session: {session.id}")
    tui.show_info(f"Provider/model: {session.provider}/{session.model}")
    tui.show_info(f"Mode: {session.mode}")
    tui.show_info("Skills: " + (", ".join(agent.active_skill_names()) if agent.active_skill_names() else "none"))
    tui.show_info("Context: " + (", ".join(project_context.tree()) if project_context.tree() else "empty"))


def handle_resume(args_text, tui, agent, config, manager, project_context, session_manager, skills):
    if not args_text:
        tui.show_error("Usage: /resume session-id")
        session = handle_new(tui, agent, config, project_context, session_manager)[0]
        return build_provider(config), session
    try:
        session = session_manager.load(args_text)
    except Exception as exc:
        tui.show_error(str(exc))
        session = handle_new(tui, agent, config, project_context, session_manager)[0]
        return build_provider(config), session

    agent.context.history = list(session.history)
    agent.set_active_skills(session.skills)
    agent.set_session_controls(
        plan_mode=session.plan_mode,
        ultrathink=session.ultrathink,
        effort=session.effort,
    )
    if agent.tools is not None:
        agent.tools = agent.tools.clone_for(session.path)
    project_context.restore(session.context_files)
    tui.show_success(f"Session resumed: {session.id}")
    return build_session_provider(config, session.provider, session.model), session


def handle_new(tui, agent, config, project_context, session_manager):
    agent.context.history = []
    project_context.clear()
    agent.set_session_controls(plan_mode=False, ultrathink=False, effort="medium")
    mode = config.modes.get(config.mode)
    agent.set_active_skills(mode.skills if mode else [])
    session = session_manager.create(config.provider, config.model, config.mode, str(Path.cwd()))
    session.skills = agent.active_skill_names()
    session.plan_mode = False
    session.ultrathink = False
    session.effort = "medium"
    session_manager.save(session)
    return session, build_provider(config)


def refresh_tui_state(tui, config, agent, session=None):
    tui.provider_name = session.provider if session is not None else config.provider
    tui.model = session.model if session is not None else config.model
    tui.mode = session.mode if session is not None else config.mode
    tui.skills = agent.active_skill_names()
    if session is not None:
        tui.session_id = session.id
        tui.plan_mode = session.plan_mode
        tui.ultrathink = session.ultrathink
        tui.effort = session.effort


def sync_tui_runtime(tui, agent):
    output_tokens, tool_rounds = agent.effective_budgets()
    tui.set_runtime_state(
        plan_mode=agent.plan_mode,
        ultrathink=agent.ultrathink,
        effort=agent.effort,
        max_output_tokens=output_tokens,
        max_tool_rounds=tool_rounds,
        native_effort_supported=agent.native_effort_supported(),
        native_effort_status=agent.native_effort_status(),
    )


def save_session_state(session_manager, session, config, agent, project_context):
    session.skills = agent.active_skill_names()
    session.path = str(Path.cwd())
    session.history = list(agent.context.history)
    session.context_files = project_context.snapshot()
    session.plan_mode = agent.plan_mode
    session.ultrathink = agent.ultrathink
    session.effort = agent.effort
    session_manager.save(session)


def handle_config(args, tui, config, manager):
    if not args:
        active = config.active_provider
        tui.show_info(f"Config: {manager.user_config_path}")
        tui.show_info(f"Provider: {config.provider} ({active.type})")
        tui.show_info(f"Base URL: {active.base_url}")
        tui.show_info(f"Model: {active.model}")
        return None

    action = args[0].lower()
    if action == "add" and len(args) >= 5:
        name, provider_type, base_url, model = args[1], args[2], args[3], " ".join(args[4:])
        config.providers[name] = ProviderConfig(name=name, type=provider_type, base_url=base_url, model=model)
        config.provider = name
        manager.save(config)
        tui.provider_name = config.provider
        tui.model = config.model
        tui.show_success(f"Provider saved: {name}")
        return build_provider(config)

    if action in {"base_url", "url"} and len(args) >= 2:
        config.active_provider.base_url = args[1]
        manager.save(config)
        tui.show_success(f"Base URL saved: {args[1]}")
        return build_provider(config)

    if action == "api_key_env" and len(args) >= 2:
        config.active_provider.api_key_env = args[1]
        manager.save(config)
        tui.show_success(f"API key environment variable saved: {args[1]}")
        return build_provider(config)

    tui.show_error("Usage: /config | /config add name type base_url model | /config base_url URL | /config api_key_env ENV")
    return None


def handle_metrics(tui, agent):
    extensions = getattr(agent, "extensions", None)
    log = getattr(extensions, "metrics", None)
    if log is None:
        tui.show_info("Metrics are disabled (metrics_enabled: false).")
        return
    from .core.metrics import summarize

    summary = summarize(log.recent(100))
    if not summary["turns"]:
        tui.show_info(f"No turns recorded yet ({log.path}).")
        return

    def pair(item):
        return f"{item['median']} / {item['worst']}" if item else "n/a"

    tui.show_info(f"Last {summary['turns']} turns · {log.path}")
    tui.show_info(f"  Outcomes: {', '.join(f'{k} {v}' for k, v in sorted(summary['outcomes'].items()))}")
    tui.show_info(f"  Duration s (median / worst): {pair(summary['duration_s'])}")
    tui.show_info(f"  Prompt tokens (median / worst): {pair(summary['prompt_tokens'])}")
    tui.show_info(f"  Completion tokens (median / worst): {pair(summary['completion_tokens'])}")
    tui.show_info(f"  Tool calls: {summary['tool_calls']} · error rate {summary['tool_error_rate']:.1%}")
    tui.show_info(f"  Turns that trimmed history: {summary['turns_with_trimmed_history']} ({summary['trimmed_turn_rate']:.1%})")


def handle_extension_info(name, tui, agent):
    extensions = getattr(agent, "extensions", None)
    if name == "/mcp":
        lines = extensions.mcp.describe() if extensions and extensions.mcp else ["MCP is not configured."]
    elif name == "/hooks":
        runner = extensions.hooks if extensions else None
        lines = (runner.describe() + [f"config error: {e}" for e in runner.errors]
                 + [f"recent non-blocking failure: {f}" for f in runner.last_failures[-3:]]) if runner else []
        lines = lines or ["No hooks configured (add `hooks:` to your config)."]
    else:
        plugins = extensions.plugins if extensions else []
        lines = [
            f"{p.name} [{'enabled' if p.enabled else 'disabled'}] {p.description or ''} · {p.skills} skills, {p.hooks} hooks, "
            f"{len(p.mcp_servers)} MCP servers" + "".join(f" · ERROR {e}" for e in p.errors)
            for p in plugins
        ] or ["No plugins found (put folders in the plugins path and list them under `plugins.enabled`)."]
        if extensions and extensions.subagents_enabled:
            lines.append("Subagent: explore (read-only) is enabled.")
    for line in lines:
        tui.show_info(line)
