import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from .core.agent import Agent
from .core.config import ConfigManager, ProviderConfig
from .core.dotenv import load_env
from .core.project_context import ProjectContext
from .core.router import build_provider
from .core.sessions import SessionManager
from .memory.sqlite import SQLiteMemory
from .skills.loader import load_skills
from .tui.app import ZerocodingTUI


def main(argv=None):
    load_env()

    parser = argparse.ArgumentParser(prog="zerocoding")
    parser.add_argument("-m", "--message", help="Mensagem")
    parser.add_argument("--provider", help="Provider configurado para usar")
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("--clear-memory", action="store_true")
    args = parser.parse_args(argv)

    manager = ConfigManager()
    try:
        config = manager.load(override_provider=args.provider)
        provider = build_provider(config)
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    memory_path = Path(config.memory_path).expanduser()
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory = SQLiteMemory(str(memory_path))
    if args.clear_memory:
        memory.clear()

    skills = load_skills(config.skills_path)
    agent = Agent(provider=provider, memory=memory, skills=skills)
    console = Console(force_terminal=True, color_system="truecolor")

    if args.list_skills:
        if not skills:
            console.print("[dim]Nenhuma skill.[/dim]")
        else:
            for skill in skills:
                console.print(f"  {skill.name}: {skill.description}")
        return 0

    if args.message:
        try:
            response = agent.ask(args.message)
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
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

    tui = ZerocodingTUI(
        provider_name=config.provider,
        model=config.model,
        theme=config.theme,
        mode=config.mode,
        session_id=session.id,
        connection_status="unknown",
    )
    tui.header()
    tui.show_welcome()

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
            if should_exit:
                save_session_state(session_manager, session, config, agent, project_context)
                tui.goodbye()
                return 0
            continue

        tui.display_message("user", prompt)
        stream = tui.create_streaming_display()
        try:
            stream.start()
            system_prompt = project_context.build_system_prompt()
            for token in agent.ask_stream(prompt, system_prompt=system_prompt):
                stream.add_token(token)
            stream.stop()
            save_session_state(session_manager, session, config, agent, project_context)
        except Exception as exc:
            stream.stop()
            tui.show_error(str(exc))


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
    if name == "/provider":
        if args_text.strip() == "test":
            ok = agent.provider.healthcheck()
            if ok:
                tui.connection_status = "connected"
                tui.show_success(f"Provider {config.provider} conectado.")
            else:
                tui.connection_status = "offline"
                tui.show_error(f"Provider {config.provider} desconectado.")
            return False, None, session
        provider = handle_provider(args_text, tui, config, manager)
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, provider, session
    if name == "/model":
        handle_model(args_text, tui, config, manager, agent)
        refresh_tui_state(tui, config, agent, session=session)
        save_session_state(session_manager, session, config, agent, project_context)
        return False, None, session
    if name == "/mode":
        provider = handle_mode(args_text, tui, config, manager, agent)
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
        session = handle_new(tui, agent, config, project_context, session_manager)
        refresh_tui_state(tui, config, agent, session=session)
        tui.clear()
        tui.show_success(f"Nova sessao: {session.id}")
        return False, None, session
    if name == "/config":
        provider = handle_config(args, tui, config, manager)
        refresh_tui_state(tui, config, agent, session=session)
        return False, provider, session
    if name == "/health":
        ok = agent.provider.healthcheck()
        if ok:
            tui.show_success(f"Provider {config.provider} conectado.")
            tui.connection_status = "connected"
        else:
            tui.show_error(f"Provider {config.provider} desconectado.")
            tui.connection_status = "offline"
        return False, None, session
    if name == "/status":
        tui.show_status()
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
            tui.show_success(f"Skill ativa: {value}")
        else:
            tui.show_error(f"Skill nao encontrada: {value}")
        return
    if action == "remove" and value:
        if agent.remove_skill(value):
            tui.show_success(f"Skill removida: {value}")
        else:
            tui.show_error(f"Skill nao estava ativa: {value}")
        return
    if action == "active":
        active = agent.active_skill_names()
        tui.show_info("Skills ativas: " + (", ".join(active) if active else "nenhuma"))
        return
    if action == "clear":
        agent.clear_skills()
        tui.show_success("Skills ativas limpas.")
        return

    if agent.add_skill(args_text):
        tui.show_success(f"Skill ativa: {args_text}")
    else:
        tui.show_error(f"Skill nao encontrada: {args_text}")


def handle_provider(args_text, tui, config, manager):
    parts = args_text.split()
    action = parts[0].lower() if parts else ""

    if not args_text:
        tui.show_info("Providers configurados:")
        for name, provider in config.providers.items():
            marker = "*" if name == config.provider else " "
            tui.show_info(f"{marker} {name} ({provider.type}) {provider.base_url} / {provider.model}")
        tui.show_info("Use /provider use nome ou /provider add nome tipo base_url modelo")
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
        tui.show_success(f"Provider salvo: {name}")
        return build_provider(config)
    elif action == "remove" and len(parts) >= 2:
        provider_name = parts[1]
        if provider_name == config.provider:
            tui.show_error("Nao remova o provider ativo antes de trocar para outro.")
            return None
        if config.providers.pop(provider_name, None):
            manager.save(config)
            tui.show_success(f"Provider removido: {provider_name}")
        else:
            tui.show_error(f"Provider nao encontrado: {provider_name}")
        return None
    if args_text not in config.providers:
        tui.show_error(f"Provider nao encontrado: {args_text}")
        return None

    config.provider = args_text
    manager.save(config)
    tui.provider_name = config.provider
    tui.model = config.model
    tui.show_success(f"Provider ativo: {config.provider}")
    return build_provider(config)


def handle_model(args_text, tui, config, manager, agent):
    parts = args_text.split()
    action = parts[0].lower() if parts else ""
    if not args_text or action == "list":
        try:
            models = agent.provider.list_models()
        except Exception as exc:
            tui.show_error(str(exc))
            return
        if not models:
            tui.show_info("Nenhum modelo retornado pelo provider.")
            return
        tui.show_info("Modelos disponiveis:")
        for model in models:
            tui.show_info(f"- {model}")
        return

    if action == "use" and len(parts) >= 2:
        args_text = " ".join(parts[1:])

    config.model = args_text
    manager.save(config)
    tui.model = args_text
    if hasattr(agent.provider, "model"):
        agent.provider.model = args_text
    tui.show_success(f"Modelo ativo: {args_text}")


def handle_mode(args_text, tui, config, manager, agent):
    if not args_text:
        tui.show_info("Modos configurados:")
        for name, mode in config.modes.items():
            marker = "*" if name == config.mode else " "
            tui.show_info(f"{marker} {name}: {mode.provider} / {mode.model}")
        return None

    if args_text not in config.modes:
        tui.show_error(f"Modo nao encontrado: {args_text}")
        return None

    mode = config.modes[args_text]
    config.mode = args_text
    config.provider = mode.provider
    if config.provider not in config.providers:
        tui.show_error(f"Provider do modo nao encontrado: {mode.provider}")
        manager.save(config)
        return None
    config.model = mode.model
    manager.save(config)
    agent.set_active_skills(mode.skills)
    tui.show_success(f"Modo ativo: {args_text}")
    return build_provider(config)


def handle_context(args, tui, project_context):
    if not args:
        paths = project_context.tree()
        tui.show_info("Contexto: " + (", ".join(paths) if paths else "vazio"))
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
                tui.show_success(f"Removido do contexto: {value}")
            else:
                tui.show_error(f"Arquivo nao estava no contexto: {value}")
            return
        if action == "clear":
            project_context.clear()
            tui.show_success("Contexto limpo.")
            return
        if action == "tree":
            paths = project_context.tree()
            if not paths:
                tui.show_info("Contexto vazio.")
            for path in paths:
                tui.show_info(f"- {path}")
            return
    except Exception as exc:
        tui.show_error(str(exc))
        return

    tui.show_error("Uso: /context | /context add path | /context remove path | /context clear | /context tree")


def handle_read(args_text, tui, project_context):
    if not args_text:
        tui.show_error("Uso: /read path")
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
        tui.show_info("Nenhum arquivo encontrado.")
    for path in files:
        tui.show_info(path)


def handle_grep(args_text, tui, project_context):
    if not args_text:
        tui.show_error("Uso: /grep pattern")
        return
    try:
        results = project_context.grep(args_text)
    except Exception as exc:
        tui.show_error(str(exc))
        return
    if not results:
        tui.show_info("Nenhum resultado.")
    for path, lineno, line in results:
        tui.show_info(f"{path}:{lineno}: {line}")


def handle_sessions(tui, session_manager):
    sessions = session_manager.list_recent()
    if not sessions:
        tui.show_info("Nenhuma sessao salva.")
        return
    for session in sessions:
        tui.show_info(f"{session.id}  {session.provider}/{session.model}  mode:{session.mode}  {session.path}")


def handle_session(tui, session, agent, project_context):
    tui.show_info(f"Session: {session.id}")
    tui.show_info(f"Provider/model: {session.provider}/{session.model}")
    tui.show_info(f"Mode: {session.mode}")
    tui.show_info("Skills: " + (", ".join(agent.active_skill_names()) if agent.active_skill_names() else "nenhuma"))
    tui.show_info("Context: " + (", ".join(project_context.tree()) if project_context.tree() else "vazio"))


def handle_resume(args_text, tui, agent, config, manager, project_context, session_manager, skills):
    if not args_text:
        tui.show_error("Uso: /resume id")
        return None, session_manager.create(config.provider, config.model, config.mode, str(Path.cwd()))
    try:
        session = session_manager.load(args_text)
    except Exception as exc:
        tui.show_error(str(exc))
        return None, session_manager.create(config.provider, config.model, config.mode, str(Path.cwd()))

    config.provider = session.provider
    if config.provider not in config.providers:
        config.providers[config.provider] = ProviderConfig(name=config.provider)
    config.model = session.model
    config.mode = session.mode
    manager.save(config)
    agent.context.history = list(session.history)
    agent.set_active_skills(session.skills)
    project_context.restore(session.context_files)
    tui.show_success(f"Sessao retomada: {session.id}")
    return build_provider(config), session


def handle_new(tui, agent, config, project_context, session_manager):
    agent.context.history = []
    project_context.clear()
    session = session_manager.create(config.provider, config.model, config.mode, str(Path.cwd()))
    return session


def refresh_tui_state(tui, config, agent, session=None):
    tui.provider_name = config.provider
    tui.model = config.model
    tui.mode = config.mode
    tui.skills = agent.active_skill_names()
    if session is not None:
        tui.session_id = session.id


def save_session_state(session_manager, session, config, agent, project_context):
    session.provider = config.provider
    session.model = config.model
    session.mode = config.mode
    session.skills = agent.active_skill_names()
    session.path = str(Path.cwd())
    session.history = list(agent.context.history)
    session.context_files = project_context.snapshot()
    session_manager.save(session)


def handle_config(args, tui, config, manager):
    if not args:
        active = config.active_provider
        tui.show_info(f"Config: {manager.user_config_path}")
        tui.show_info(f"Provider: {config.provider} ({active.type})")
        tui.show_info(f"Base URL: {active.base_url}")
        tui.show_info(f"Modelo: {active.model}")
        return None

    action = args[0].lower()
    if action == "add" and len(args) >= 5:
        name, provider_type, base_url, model = args[1], args[2], args[3], " ".join(args[4:])
        config.providers[name] = ProviderConfig(name=name, type=provider_type, base_url=base_url, model=model)
        config.provider = name
        manager.save(config)
        tui.provider_name = config.provider
        tui.model = config.model
        tui.show_success(f"Provider salvo: {name}")
        return build_provider(config)

    if action in {"base_url", "url"} and len(args) >= 2:
        config.active_provider.base_url = args[1]
        manager.save(config)
        tui.show_success(f"Base URL salva: {args[1]}")
        return build_provider(config)

    if action == "api_key_env" and len(args) >= 2:
        config.active_provider.api_key_env = args[1]
        manager.save(config)
        tui.show_success(f"Variavel de API key salva: {args[1]}")
        return build_provider(config)

    tui.show_error("Uso: /config | /config add nome tipo base_url modelo | /config base_url URL | /config api_key_env ENV")
    return None


if __name__ == "__main__":
    sys.exit(main())
