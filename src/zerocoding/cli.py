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
from .core.sessions import SessionManager
from .core.tools import ToolRegistry
from .commands import handle_command, refresh_tui_state, save_session_state, sync_tui_runtime
from .memory.sqlite import SQLiteMemory
from .skills.loader import load_skills
from .tui.app import ZerocodingTUI


def main(argv=None):
    load_env()

    parser = argparse.ArgumentParser(prog="zerocoding")
    parser.add_argument("-m", "--message", help="Prompt to send")
    parser.add_argument("--provider", help="Configured provider to use")
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("--clear-memory", action="store_true")
    args = parser.parse_args(argv)

    manager = ConfigManager()
    try:
        config = manager.load(override_provider=args.provider)
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
        max_output_tokens=config.max_output_tokens,
        max_tool_rounds=config.max_tool_rounds,
        effort_profiles=config.effort_profiles,
        dynamic_context=config.dynamic_context,
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
    session_manager = SessionManager()
    session = session_manager.create(
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

    metrics = MetricsLog(Path.cwd() / ".zerocoding" / "metrics" / "turns.jsonl") if config.metrics_enabled else None
    if metrics:
        agent.metrics_sink = metrics.record

    active_animation = [None]
    tui = ZerocodingTUI(
        provider_name=config.provider,
        model=config.model,
        theme=config.theme,
        mode=config.mode,
        session_id=session.id,
        connection_status="unknown",
        skills=agent.active_skill_names(),
    )

    def approve_action(action, preview):
        animation = active_animation[0]
        if animation:
            animation.pause()
        try:
            return tui.confirm_action(action, preview)
        finally:
            if animation:
                animation.resume()

    agent.tools = ToolRegistry(Path.cwd(), approve=approve_action, policy=config.command_policy)
    extensions = build_extensions(config, agent, Path.cwd(), skills, metrics=metrics)
    refresh_tui_state(tui, config, agent, session=session)
    sync_tui_runtime(tui, agent)
    tui.header()
    tui.show_welcome()
    for warning in startup_warnings(extensions):
        tui.show_warning(warning)

    while True:
        prompt = tui.input_prompt()
        if not prompt:
            continue

        if prompt.startswith("/"):
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
            if provider is not None:
                agent.provider = provider
            refresh_tui_state(tui, config, agent, session=session)
            sync_tui_runtime(tui, agent)
            if should_exit:
                save_session_state(session_manager, session, config, agent, project_context)
                tui.goodbye()
                return 0
            continue

        tui.display_message("user", prompt)
        animation = tui.show_thinking()
        active_animation[0] = animation
        try:
            system_prompt = project_context.build_system_prompt()
            response = agent.ask(
                prompt,
                system_prompt=system_prompt,
                use_tools=True,
                on_event=lambda event: tui.handle_agent_event(event, animation),
            )
            elapsed = animation.stop()
            active_animation[0] = None
            tui.display_message("assistant", response)
            tui.show_info(f"Worked for {elapsed:.0f}s")
            save_session_state(session_manager, session, config, agent, project_context)
        except (KeyboardInterrupt, TurnCancelled):
            elapsed = animation.stop()
            active_animation[0] = None
            tui.show_warning("Turn cancelled. Nothing from this turn was saved to the session.")
            tui.show_info(f"Stopped after {elapsed:.0f}s")
        except Exception as exc:
            elapsed = animation.stop()
            active_animation[0] = None
            tui.show_error(str(exc))
            tui.show_info(f"Worked for {elapsed:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
