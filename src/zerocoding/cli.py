import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from .core.agent import Agent
from .core.config import ConfigManager
from .core.dotenv import load_env
from .core.cancel import TurnCancelled
from .core.bootstrap import build_extensions, startup_warnings
from .core.metrics import MetricsLog
from .core.project_context import ProjectContext
from .core.router import build_provider
from .core.sessions import Session, SessionManager
from .core.tools import ToolRegistry
from .commands import attach_journal, handle_command, refresh_tui_state, save_session_state, sync_tui_runtime
from .memory.sqlite import SQLiteMemory
from .skills.loader import load_skills
from .tui.app import ZerocodingTUI
from .core.cancel import CancelToken
from .core.permissions import PermissionPolicy
from .core.verify import Verifier


def main(argv=None):
    load_env()

    parser = argparse.ArgumentParser(prog="zerocoding")
    parser.add_argument("command", nargs="?", choices={"doctor"}, help="Run environment diagnostics")
    parser.add_argument("-m", "--message", help="Prompt to send")
    parser.add_argument("--provider", help="Configured provider to use")
    parser.add_argument("--no-session-save", action="store_true", help="Do not save this interactive session")
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("--clear-memory", action="store_true")
    args = parser.parse_args(argv)

    manager = ConfigManager()
    try:
        config = manager.load(override_provider=args.provider)
    except Exception as exc:
        if args.command == "doctor":
            from .core.doctor import Check, print_report
            return print_report([Check("Config", "fail", str(exc),
                                       "Fix ~/.zerocoding/config.yaml and run zc doctor again.")])
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.command == "doctor":
        from .core.doctor import print_report, run_doctor
        return print_report(run_doctor(config, manager, Path.cwd()))

    try:
        provider = build_provider(config)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    memory_path = Path(config.memory_path).expanduser()
    if args.clear_memory:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        SQLiteMemory(str(memory_path)).clear()

    skills = load_skills(config.skills_path)
    agent = Agent(
        provider=provider,
        skills=skills,
        max_input_tokens=config.max_input_tokens,
        context_window=config.context_window,
        max_output_tokens=config.max_output_tokens,
        max_tool_rounds=config.max_tool_rounds,
        effort_profiles=config.effort_profiles,
        dynamic_context=config.dynamic_context,
        streaming_enabled=config.streaming_enabled,
        shell_block_fallback=config.shell_block_fallback,
    )
    console = Console(force_terminal=True, color_system="truecolor")

    if args.list_skills:
        if not skills:
            console.print("[dim]No skills found.[/dim]")
        else:
            for skill in skills:
                console.print(f"  {skill.name}: {skill.description}")
        return 0

    if args.message:
        try:
            response = agent.ask(args.message)
        except KeyboardInterrupt:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            return 1
        console.print(Markdown(response))
        return 0

    project_context = ProjectContext(Path.cwd())
    session_manager = SessionManager(persist=config.session_persistence and not args.no_session_save)
    try:
        session = Session.new(
            provider=config.provider,
            model=config.model,
            mode=config.mode,
            path=str(Path.cwd()),
        )
        default_mode = config.modes.get(config.mode)
        if default_mode:
            agent.set_active_skills(default_mode.skills)
        session.skills = agent.active_skill_names()
        session_manager.save(session)
    except (OSError, ValueError) as exc:
        print(f"Error: Could not create a private session: {exc}", file=sys.stderr)
        return 1

    metrics = MetricsLog(Path.cwd() / ".zerocoding" / "metrics" / "turns.jsonl") if config.metrics_enabled else None
    if metrics:
        agent.metrics_sink = metrics.record

    active_animation = [None]
    use_fullscreen = config.fullscreen and sys.stdin.isatty() and sys.stdout.isatty()
    if use_fullscreen:
        from .tui.fullscreen import FullscreenTUI
    tui = (FullscreenTUI if use_fullscreen else ZerocodingTUI)(
        provider_name=config.provider,
        model=config.model,
        theme=config.theme,
        mode=config.mode,
        session_id=session.id,
        connection_status="unknown",
        skills=agent.active_skill_names(),
    )
    tui.mouse_enabled = config.mouse_support

    permissions = PermissionPolicy(Path.cwd(), "ask", config.auto_packs)
    agent.permissions = permissions

    def approve_action(action, preview):
        decision = permissions.decide(action, preview)
        if decision is not None:  # auto or yolo: approved by code, still shown in the transcript
            tui.note_auto_approval(action, preview, decision.note)
            return True
        animation = active_animation[0]
        if animation:
            animation.pause()
        try:
            return tui.confirm_action(action, preview)
        finally:
            if animation:
                animation.resume()

    agent.tools = ToolRegistry(Path.cwd(), approve=approve_action, policy=config.command_policy)
    attach_journal(agent.tools, session, session_manager)
    agent.verifier = Verifier(Path.cwd(), config.verify) if config.verify.enabled else None
    extensions = build_extensions(config, agent, Path.cwd(), skills, metrics=metrics)
    def interactive_loop():
        nonlocal session
        refresh_tui_state(tui, config, agent, session=session)
        sync_tui_runtime(tui, agent)
        tui.header()
        tui.show_welcome()
        for warning in startup_warnings(extensions):
            tui.show_warning(warning)
        if not agent.window_tokens():
            tui.show_warning(
                f"Could not detect the context window of {config.provider}. Using {config.max_input_tokens} prompt tokens; "
                "set context_window in ~/.zerocoding/config.yaml to use more.")

        while True:
            prompt = tui.input_prompt()
            if not prompt:
                continue

            if prompt.startswith("/"):
                try:
                    should_exit, provider, session = handle_command(
                        prompt,
                        tui,
                        agent,
                        config,
                        manager,
                        skills,
                        project_context,
                        session_manager,
                        session,
                    )
                except (OSError, ValueError) as exc:
                    tui.show_error(f"Command could not be completed: {exc}")
                    continue
                if provider is not None:
                    agent.provider = provider
                refresh_tui_state(tui, config, agent, session=session)
                sync_tui_runtime(tui, agent)
                if should_exit:
                    try:
                        save_session_state(session_manager, session, config, agent, project_context)
                    except (OSError, ValueError) as exc:
                        tui.show_error(f"Could not save the session: {exc}")
                        tui.goodbye()
                        return 1
                    tui.goodbye()
                    return 0
                continue

            tui.display_message("user", prompt)
            cancel = CancelToken()
            tui.set_cancel(cancel)
            animation = tui.show_thinking(tokens=agent.turn_tokens)
            active_animation[0] = animation
            try:
                system_prompt = project_context.build_system_prompt()
                response = agent.ask(
                    prompt,
                    system_prompt=system_prompt,
                    use_tools=True,
                    on_event=lambda event: tui.handle_agent_event(event, animation),
                cancel=cancel,
                )
                elapsed = animation.stop()
                active_animation[0] = None
                tui.display_message("assistant", response)
                tui.show_done(elapsed, tokens=agent.turn_tokens())
                save_session_state(session_manager, session, config, agent, project_context)
            except (KeyboardInterrupt, TurnCancelled):
                elapsed = animation.stop()
                active_animation[0] = None
                tui.show_warning("Turn cancelled. Nothing from this turn was saved to the session.")
                tui.show_done(elapsed, stopped=True, tokens=agent.turn_tokens())
            except Exception as exc:
                elapsed = animation.stop()
                active_animation[0] = None
                tui.show_error(str(exc))
                tui.show_done(elapsed, tokens=agent.turn_tokens())


    return tui.run(interactive_loop) if use_fullscreen else interactive_loop()

if __name__ == "__main__":
    sys.exit(main())
