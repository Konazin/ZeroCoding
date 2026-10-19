"""Slash-command handlers and session-state helpers for the interactive CLI."""
from datetime import datetime
from pathlib import Path

from .core.config import ProviderConfig
from .core.project_context import ProjectContext
from .config_menu import confirm_yolo, pick_effort, pick_model, pick_permission, run_settings
from .core.router import build_provider, build_session_provider
from .core.sessions import Session


def handle_command(command, tui, agent, config, manager, skills, project_context, session_manager, session):
    name, *args = command.strip().split()
    name = name.lower()
    args_text = " ".join(args)

    interactive = hasattr(tui, "run_screen")
    if interactive and (
        (name == "/config" and not args) or (name == "/provider" and not args_text) or (name == "/model" and not args_text)
        or (name == "/effort" and not args_text)
    ):
        state = {"provider": None, "session": session}

        def dispatch(command):
            _, new_provider, new_session = handle_command(
                command, tui, agent, config, manager, skills, project_context, session_manager, state["session"])
            state["session"] = new_session
            if new_provider is not None:
                agent.provider = state["provider"] = new_provider

        if name == "/model":
            pick_model(tui, config, manager, agent, dispatch)
        elif name == "/effort":
            pick_effort(tui, agent, dispatch)
        else:
            run_settings(tui, config, manager, agent, dispatch, tab="Providers" if name == "/provider" else "Config")
        refresh_tui_state(tui, config, agent, session=state["session"])
        return False, state["provider"], state["session"]
    if name == "/permission":
        policy = getattr(agent, "permissions", None)
        if policy is None:
            tui.show_error("Permission modes are not available in this session.")
        else:
            handle_permission(args_text, tui, policy)
            refresh_tui_state(tui, config, agent, session=session)
        return False, None, session

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
    if name == "/instructions":
        handle_instructions(args_text, tui, agent, config)
        return False, None, session
    if name == "/verify":
        handle_verify(args_text, tui, agent)
        return False, None, session
    if name == "/undo":
        handle_undo(args_text, tui, agent)
        return False, None, session
    if name == "/compact":
        before, after = agent.compact_history()
        if after >= before:
            tui.show_info("Nothing to compact yet.")
        else:
            save_session_state(session_manager, session, config, agent, project_context)
            window = agent.window_tokens()
            used = f" ({after} of {window} tokens)" if window else ""
            tui.show_success(f"Conversation compacted: {before} → {after} tokens{used}.")
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
        handle_sessions(args_text, tui, session_manager, session)
        return False, None, session
    if name == "/session":
        handle_session(tui, session, agent, project_context)
        return False, None, session
    if name == "/resume":
        provider, session = handle_resume(
            args_text, tui, agent, config, manager, project_context, session_manager, skills, session,
        )
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
    if name == "/buddy":
        played = tui.play_buddy(args_text.strip().lower() or None)
        tui.show_info(f"Buddy played '{played}'. Try: /buddy work, look, dance, sleep, cheer, shock.")
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


def handle_instructions(args_text, tui, agent, config):
    """/instructions [reload|off]: the project conventions file that is added to the system prompt."""
    from .core.instructions import load_instructions
    argument = args_text.strip().lower()
    if argument == "off":
        agent.instructions = None
        tui.show_success("Project instructions off for this session. /instructions reload brings them back.")
        return
    if argument == "reload":
        agent.instructions = load_instructions(Path.cwd(), config.instructions)
        if agent.instructions is None:
            tui.show_info("No project instructions file found (looked for " + ", ".join(config.instructions.files) + ").")
            return
    elif argument:
        tui.show_error("Usage: /instructions [reload|off]")
        return
    current = agent.instructions
    if current is None:
        tui.show_info("No project instructions loaded. Add ZEROCODING.md, AGENTS.md or CLAUDE.md to the project root.")
        return
    cut = f" · truncated from {current.total_chars}" if current.truncated else ""
    tui.show_info(f"{current.source} · {len(current.text)} characters{cut} · counted in every prompt")
    for line in current.text.splitlines()[:12]:
        tui.show_info("  " + line[:100])


def handle_verify(args_text, tui, agent):
    """/verify [on|off|set <command>]: the check the agent re-runs after editing files, for this session."""
    verifier = getattr(agent, "verifier", None)
    argument = args_text.strip()
    if verifier is None:
        tui.show_info("Verification is disabled in the config (verify.enabled: false).")
        return
    if not argument:
        tui.show_info(f"Verification: {verifier.status(agent.tools)} · up to {verifier.config.max_attempts} re-run(s) per request")
        return
    word, _, rest = argument.partition(" ")
    if word == "on" and not rest:
        verifier.reset(enabled=True)
        tui.show_success("Verification on. A detected command is asked about once.")
    elif word == "off" and not rest:
        verifier.reset(enabled=False)
        tui.show_success("Verification off for this session.")
    elif word == "set" and rest.strip():
        verifier.reset(enabled=True, command=rest.strip())
        tui.show_success(f"Verification command set (trusted for this session): {rest.strip()}")
    else:
        tui.show_error("Usage: /verify [on|off|set <command>]")


def attach_journal(tools, session, session_manager) -> None:
    """Give the tool registry the journal of this session (kept on disk only when sessions persist)."""
    if tools is None:
        return
    from .core.journal import journal_for
    persist = bool(getattr(session_manager, "persist", True))
    tools.journal = journal_for(session.id, tools.root, persist=persist)


def handle_undo(args_text, tui, agent):
    """/undo [list|<turn>]: restore the files the agent wrote in a turn, after showing the diff."""
    journal = getattr(agent.tools, "journal", None)
    if journal is None:
        tui.show_error("Undo is not available in this session.")
        return
    argument = args_text.strip().lower()
    if argument == "list":
        turns = journal.turns()
        if not turns:
            tui.show_info("Nothing to undo yet.")
        for turn in turns[:10]:
            tui.show_info(f"turn {turn.id} · {len(turn.entries)} file(s) · {turn.label}")
        return
    if argument and not argument.isdigit():
        tui.show_error("Usage: /undo [list|turn-number]")
        return
    turn = journal.get(int(argument)) if argument else journal.latest()
    if turn is None:
        tui.show_info("Nothing to undo yet." if not argument else f"No journaled turn {argument}. Use /undo list.")
        return
    plan = journal.plan_undo(turn)
    if plan.conflicts:
        tui.show_error("Not undone: these files changed after the agent wrote them: " + ", ".join(plan.conflicts)
                       + ". Review them yourself, then retry.")
        return
    if not tui.confirm_action("Undo changes", plan.preview):
        return
    try:
        restored = journal.apply(plan)
    except (OSError, ValueError) as exc:
        tui.show_error(f"Undo failed: {exc}")
        return
    tui.show_success(f"Undid {restored} file(s) from turn {turn.id}. Changes made by commands are not undone.")


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


PROVIDER_TYPES = ("llama_cpp", "openai_compatible", "ollama")


def _warn_if_model_missing(tui, provider, model):
    """A wrong model name makes every later request fail with a bare 400/404; catch it when saving."""
    try:
        available = provider.list_models()
    except Exception:
        return
    if available and model not in available:
        shown = ", ".join(available[:8])
        tui.show_warning(f"Model '{model}' is not served there. Available: {shown}. Fix it with /model.")


def handle_permission(args_text, tui, policy):
    """/permission [ask|auto|yolo|packs]. The mode applies to this session only."""
    from .core.command_packs import PACK_SUMMARY
    from .core.permissions import MODE_SUMMARY, MODES

    choice = args_text.strip().lower()
    if choice == "packs":
        for pack in policy.packs:
            tui.show_info(f"{pack}: {PACK_SUMMARY.get(pack, '')}")
        return
    if not choice:
        if hasattr(tui, "run_screen"):
            pick_permission(tui, policy)
            return
        tui.show_info(f"Permission mode: {policy.mode}. Use /permission ask|auto|yolo|packs.")
        for mode in MODES:
            tui.show_info(f"{'*' if mode == policy.mode else ' '} {mode}: {MODE_SUMMARY[mode]}")
        return
    if choice not in MODES:
        tui.show_error("Usage: /permission [ask|auto|yolo|packs]")
        return
    if choice == "yolo" and not confirm_yolo(tui):
        tui.show_info("YOLO mode not enabled.")
        return
    policy.set_mode(choice)
    tui.show_success(f"Permission mode: {choice}.")


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
        if provider_type not in PROVIDER_TYPES:
            tui.show_error(
                f"Unknown provider type '{provider_type}'. Use one of: {', '.join(PROVIDER_TYPES)}. "
                "Order is: /provider add name type base_url model. Ollama and most local servers use openai_compatible."
            )
            return None
        config.providers[name] = ProviderConfig(name=name, type=provider_type, base_url=base_url, model=model)
        config.provider = name
        manager.save(config)
        tui.provider_name = config.provider
        tui.model = config.model
        tui.show_success(f"Provider saved: {name}")
        provider = build_provider(config)
        _warn_if_model_missing(tui, provider, model)
        return provider
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


def handle_sessions(args_text, tui, session_manager, current_session=None):
    args = args_text.split()
    action = args[0].lower() if args else "list"
    if action == "list" and len(args) <= 1:
        if not session_manager.persist:
            tui.show_info("Session persistence is disabled for this run.")
            return
        try:
            sessions, invalid = session_manager.list_recent_with_errors(limit=None)
            rows = [
                (session, session_manager.size_bytes(session.id))
                for session in sessions
            ]
        except (OSError, ValueError) as exc:
            tui.show_error(f"Could not read saved sessions: {exc}")
            return
        if not rows and not invalid:
            tui.show_info("No saved sessions.")
            return
        for saved, size in rows:
            try:
                updated = datetime.fromtimestamp(saved.updated_at).astimezone().strftime("%Y-%m-%d %H:%M")
            except (OverflowError, OSError, ValueError):
                updated = "unknown date"
            tui.show_info(
                f"{saved.id}  {saved.provider}/{saved.model}  {updated}  "
                f"{len(saved.history)} messages  {size} bytes  {saved.path}"
            )
        if invalid:
            tui.show_warning(
                f"Ignored {len(invalid)} unreadable session file(s): "
                + ", ".join(session_id for session_id, _ in invalid)
                + ". Use /sessions delete <full-id> to remove an invalid file."
            )
        return

    if action == "delete" and len(args) == 2:
        session_id = args[1]
        if not session_manager.persist:
            tui.show_error("Session persistence is disabled for this run.")
            return
        if current_session is not None and session_id == current_session.id:
            tui.show_error("The active session cannot be deleted. Start a new session first.")
            return
        try:
            size = session_manager.size_bytes(session_id)
        except (OSError, ValueError) as exc:
            tui.show_error(f"Could not inspect session: {exc}")
            return
        if not _confirm_session_action(tui, "Delete session", f"ID: {session_id}\nStored size: {size} bytes"):
            tui.show_info("Session deletion cancelled.")
            return
        try:
            session_manager.delete(session_id)
        except (OSError, ValueError) as exc:
            tui.show_error(f"Could not delete session: {exc}")
            return
        tui.show_success(f"Deleted session {session_id}.")
        return

    if action == "clear" and len(args) == 1:
        if not session_manager.persist:
            tui.show_error("Session persistence is disabled for this run.")
            return
        try:
            session_ids = session_manager.saved_ids()
        except (OSError, ValueError) as exc:
            tui.show_error(f"Could not inspect saved sessions: {exc}")
            return
        if current_session is not None:
            session_ids = [session_id for session_id in session_ids if session_id != current_session.id]
        if not session_ids:
            tui.show_info("No inactive saved sessions to delete.")
            return
        active = f"\nActive session {current_session.id} will be kept." if current_session else ""
        preview = f"Delete {len(session_ids)} saved session(s)?{active}\nOnly session JSON files will be removed."
        if not _confirm_session_action(tui, "Delete saved sessions", preview):
            tui.show_info("Session cleanup cancelled.")
            return
        try:
            deleted = session_manager.delete_many(session_ids)
        except (OSError, ValueError) as exc:
            tui.show_error(f"Could not finish deleting sessions: {exc}")
            return
        tui.show_success(f"Deleted {len(deleted)} saved session(s).")
        return

    tui.show_error("Usage: /sessions [list|delete <full-id>|clear]")


def _confirm_session_action(tui, action, preview):
    confirm = getattr(tui, "confirm_action", None)
    if not callable(confirm):
        tui.show_error("This action requires an interactive confirmation prompt.")
        return False
    return confirm(action, preview)


def handle_session(tui, session, agent, project_context):
    tui.show_info(f"Session: {session.id}")
    tui.show_info(f"Provider/model: {session.provider}/{session.model}")
    tui.show_info(f"Mode: {session.mode}")
    tui.show_info("Skills: " + (", ".join(agent.active_skill_names()) if agent.active_skill_names() else "none"))
    tui.show_info("Context: " + (", ".join(project_context.tree()) if project_context.tree() else "empty"))


def handle_resume(args_text, tui, agent, config, manager, project_context, session_manager, skills,
                  current_session=None):
    if not args_text:
        tui.show_error("Usage: /resume session-id")
        return None, current_session
    try:
        session = session_manager.load(args_text)
    except FileNotFoundError as exc:
        tui.show_error(str(exc))
        return None, current_session
    except (OSError, ValueError) as exc:
        tui.show_error(str(exc))
        return None, current_session

    try:
        provider = build_session_provider(config, session.provider, session.model)
        tools = agent.tools.clone_for(session.path) if agent.tools is not None else None
        attach_journal(tools, session, session_manager)
        restored_context = ProjectContext(
            project_context.root,
            max_file_chars=project_context.max_file_chars,
            max_total_chars=project_context.max_total_chars,
        )
        restored_context.restore(session.context_files)
    except Exception as exc:
        tui.show_error(f"Could not prepare session: {exc}")
        return None, current_session

    agent.context.history = list(session.history)
    agent.set_active_skills(session.skills)
    agent.set_session_controls(
        plan_mode=session.plan_mode,
        ultrathink=session.ultrathink,
        effort=session.effort,
    )
    agent.tools = tools
    project_context.files = restored_context.files
    tui.show_success(f"Session resumed: {session.id}")
    return provider, session


def handle_new(tui, agent, config, project_context, session_manager):
    mode = config.modes.get(config.mode)
    requested_skills = mode.skills if mode else []
    active_skills = []
    for name in requested_skills:
        skill = next((item for item in agent.skills if item.name == name), None)
        if skill is not None and skill not in active_skills:
            active_skills.append(skill)

    session = Session.new(config.provider, config.model, config.mode, str(Path.cwd()))
    session.skills = [skill.name for skill in active_skills]
    session.plan_mode = False
    session.ultrathink = False
    session.effort = "medium"
    provider = build_provider(config)
    tools = agent.tools.clone_for(Path.cwd()) if agent.tools is not None else None
    attach_journal(tools, session, session_manager)
    session_manager.save(session)

    agent.context.history = []
    project_context.clear()
    agent.active_skills = active_skills
    agent.set_session_controls(plan_mode=False, ultrathink=False, effort="medium")
    agent.tools = tools
    return session, provider


def refresh_tui_state(tui, config, agent, session=None):
    tui.permission_mode = getattr(getattr(agent, "permissions", None), "mode", "ask")
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
    tui.show_info(f"  TTFT ms (median / worst): {pair(summary['ttft_ms'])}")
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
