import argparse
import atexit
import importlib.util
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown

from .core.agent import Agent
from .core.config import ConfigManager, ProviderConfig
from .core.dotenv import load_env
from .core.project_context import ProjectContext
from .core.permissions import review_action
from .core.readiness import check_provider_readiness, readiness_hint
from .core.router import build_provider
from .core.sessions import SessionManager
from .tools.builtin import create_builtin_tools
from .tools.mcp_client import MCPClientManager
from .tools.registry import format_tool_preview
from .tools.registry import ToolRegistry, ToolSpec
from .skills.loader import load_skills
from .tui.app import ZerocodingTUI
from .projects import build_scaffold, create_project, resolve_project_target
from .tools.sandbox import SandboxUnavailable, run_workspace_command, workspace_sandbox_available


def main(argv=None):
    load_env()

    parser = argparse.ArgumentParser(prog="zerocoding")
    parser.add_argument("-m", "--message", help="Mensagem")
    parser.add_argument("--provider", help="Provider configurado para usar")
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("command", nargs="?", choices=("init",), help="Ação: init cria um novo projeto Python, JavaScript ou TypeScript")
    parser.add_argument("target", nargs="?", help="Pasta de destino para `zc init`")
    args = parser.parse_args(argv)

    if args.target and args.command != "init":
        parser.error("informe um destino somente com `zc init <diretório>`")
    if args.command == "init" and not args.target:
        parser.error("uso: zc init <diretório>")
    if args.command == "init" and args.list_skills:
        parser.error("--list-skills não pode ser combinado com init")

    manager = ConfigManager()
    try:
        config = manager.load(override_provider=args.provider)
        provider = build_provider(config)
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    console = Console(force_terminal=True, color_system="truecolor")
    if args.command == "init":
        return run_project_init(
            args.target,
            config,
            manager,
            provider,
            console=console,
            initial_description=args.message,
            provider_override=bool(args.provider),
            prefer_text_tool_calls=config.active_provider.type == "ollama",
        )

    project_root = Path.cwd()
    skills = load_skills(config.skills_path, project_root)
    project_context = ProjectContext(project_root)
    agent = Agent(provider=provider, skills=skills, tools=create_builtin_tools(project_root), permission_mode=config.permission_mode)
    agent.set_mode(config.modes.get(config.mode, config.modes.get("code")))
    if agent.permission_warning:
        console.print(f"[yellow]{agent.permission_warning} Modo efetivo: manual.[/yellow]")
    mcp_manager = MCPClientManager(config.mcp_servers)
    atexit.register(mcp_manager.close)
    if args.list_skills:
        if not skills:
            console.print("[dim]Nenhuma skill.[/dim]")
        else:
            for skill in skills:
                console.print(f"  {skill.name}: {skill.description}")
        return 0

    if args.message:
        try:
            readiness = check_provider_readiness(provider, config.active_provider.type, config.model)
            if not readiness.ready:
                console.print(f"[red]{readiness.message}[/red]")
                console.print(readiness_hint(readiness, config.active_provider.type, config.model))
                return 1
            mcp_manager.register_tools(agent.tools)
            response = agent.ask(args.message, context_text=project_context.build_context(), approve=lambda tool, data: input(f"Allow {tool.name}: {format_tool_preview(tool, data)}? [y/N] ").strip().lower() == "y")
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
            return 1
        finally:
            mcp_manager.close()
        console.print(Markdown(response))
        return 0

    session_manager = SessionManager()
    session = session_manager.create(
        provider=config.provider,
        model=config.model,
        mode=config.mode,
        path=str(Path.cwd()),
    )

    readiness = check_provider_readiness(provider, config.active_provider.type, config.model)
    startup_notice = "\n".join(filter(None, (
        readiness_hint(readiness, config.active_provider.type, config.model),
        agent.permission_warning,
    )))
    tui = ZerocodingTUI(
        provider_name=config.provider,
        model=config.model,
        theme=config.theme,
        mode=config.mode,
        permission_mode=agent.permission_mode,
        session_id=session.id,
        connection_status=readiness.status,
        input_budget_tokens=agent.input_budget_tokens,
        max_tool_steps=agent.max_tool_steps,
        output_budget_tokens=agent.output_budget_tokens,
        startup_notice=startup_notice,
    )
    tui.bind_runtime(agent, project_context, lambda: save_session_state(session_manager, session, config, agent, project_context))
    if config.mcp_servers:
        try:
            mcp_manager.register_tools(agent.tools)
            tui.show_success(f"MCP: {len(config.mcp_servers)} servidor(es) conectado(s).")
        except Exception as exc:
            tui.show_error(f"MCP indisponivel: {exc}")

    def on_submit(prompt):
        nonlocal provider, session
        if prompt.startswith("/"):
            parts = prompt.strip().split()
            provider_add = len(parts) >= 2 and parts[0].lower() == "/provider" and parts[1].lower() == "add"
            if provider_add and len(parts) < 6:
                def question(index, values):
                    if index == 0:
                        return "Nome do provider", "local"
                    if index == 1:
                        return "Tipo (ollama/openai-compatible)", "ollama"
                    provider_type = values[1].lower().replace("-", "_")
                    if index == 2:
                        return "URL base", "https://api.openai.com/v1" if provider_type in {"openai", "openai_compatible"} else "http://localhost:11434"
                    if index == 3:
                        return "Modelo", config.model
                    if index == 4:
                        return "Variável de ambiente da chave API", "OPENAI_API_KEY" if provider_type in {"openai", "openai_compatible"} else ""
                    return "", ""

                def finish_provider(values):
                    name, kind, base_url, model, api_key_env = values
                    provider_type = kind.lower().replace("-", "_")
                    if provider_type in {"openai", "openai_compatible"}:
                        provider_type = "openai_compatible"
                    if provider_type not in {"ollama", "openai_compatible"}:
                        raise ValueError("Tipo inválido. Escolha ollama ou openai-compatible.")
                    if not name or not model or not base_url.startswith(("http://", "https://")):
                        raise ValueError("Informe nome, URL http(s) e modelo.")
                    config.providers[name] = ProviderConfig(name=name, type=provider_type, base_url=base_url, model=model, api_key_env=api_key_env if provider_type == "openai_compatible" else "")
                    config.provider = name
                    manager.save(config)
                    tui.provider_name, tui.model = config.provider, config.model
                    return build_provider(config), f"Provider salvo e ativado: {name}"

                tui.start_wizard(question, finish_provider, answers=parts[2:])
                return
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
                mcp_manager,
            )
            if provider is not None:
                agent.provider = provider
            if should_exit:
                save_session_state(session_manager, session, config, agent, project_context)
                mcp_manager.close()
                tui._exit = True
                tui.goodbye()
            else:
                agent.set_mode(config.modes.get(config.mode, config.modes.get("code")))
            return
        # Chat is handled by the worker in the full-screen host.

    try:
        tui.run(on_submit)
    finally:
        save_session_state(session_manager, session, config, agent, project_context)
        mcp_manager.close()
    return 0


def run_project_init(path, config, manager, provider, *, console=None, input_fn=None, cwd=None, initial_description=None, provider_override=False, prefer_text_tool_calls=False):
    """Guide one new project through a local-model generation and optional verification."""
    console = console or Console(force_terminal=True, color_system="truecolor")
    input_fn = input_fn or input
    root = Path(cwd or Path.cwd()).resolve()
    try:
        target = resolve_project_target(path, cwd=root)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Destino inválido: {exc}[/red]")
        return 1

    original_provider = config.provider
    original_model = config.model
    project_mode = config.modes.get("project")
    if project_mode and not provider_override:
        if project_mode.provider not in config.providers:
            console.print(f"[red]Provider do perfil project não configurado: {project_mode.provider}[/red]")
            return 1
        if config.provider != project_mode.provider:
            config.provider = project_mode.provider
            config.model = project_mode.model
            try:
                provider = build_provider(config)
            except Exception as exc:
                console.print(f"[red]Não foi possível configurar o provider do perfil project: {exc}[/red]")
                return 1
        elif config.model != project_mode.model:
            config.model = project_mode.model
            if hasattr(provider, "model"):
                provider.model = project_mode.model

    readiness = check_provider_readiness(provider, config.active_provider.type, config.model)
    if not readiness.ready:
        console.print(f"[yellow]{readiness.message}[/yellow]")
        console.print(readiness_hint(readiness, config.active_provider.type, config.model))
        if readiness.status == "model-missing":
            for index, model_name in enumerate(readiness.models, 1):
                console.print(f"  {index}. {model_name}")
            try:
                choice = input_fn("Digite o número ou nome do modelo instalado (Enter cancela): ").strip()
            except (EOFError, KeyboardInterrupt):
                return 1
            selected = readiness.models[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(readiness.models) else choice
            if selected not in readiness.models:
                console.print("[red]Nenhum modelo foi selecionado; o projeto não foi criado.[/red]")
                return 1
            config.model = selected
            if hasattr(provider, "model"):
                provider.model = selected
            if project_mode and not provider_override:
                selected_provider = config.provider
                project_mode.model = selected
                config.provider = original_provider
                if selected_provider == original_provider:
                    config.providers[selected_provider].model = original_model
            manager.save(config)
        else:
            return 1

    permission_agent = Agent(provider, permission_mode=config.permission_mode)
    permission_mode = permission_agent.permission_mode
    if permission_agent.permission_warning:
        console.print(f"[yellow]{permission_agent.permission_warning} Modo efetivo: manual.[/yellow]")

    console.print("Linguagem: 1) Python  2) JavaScript  3) TypeScript")
    try:
        language_answer = input_fn("Escolha python, javascript ou typescript: ").strip().lower()
        language = {"1": "python", "2": "javascript", "3": "typescript", "js": "javascript", "ts": "typescript", "py": "python"}.get(language_answer, language_answer)
        if language not in {"python", "javascript", "typescript"}:
            console.print("[red]Linguagem inválida. Escolha python, javascript ou typescript.[/red]")
            return 1
        console.print(f"Perfil {language}: 1) CLI  2) API")
        profile_answer = input_fn("Escolha cli ou api: ").strip().lower()
        profile = {"1": "cli", "2": "api"}.get(profile_answer, profile_answer)
        if profile not in {"cli", "api"}:
            console.print("[red]Perfil inválido. Escolha cli ou api.[/red]")
            return 1
        description = (initial_description or "").strip() or input_fn("Descreva o que o projeto deve fazer: ").strip()
        if not description:
            console.print("[red]A descrição do projeto não pode ficar vazia.[/red]")
            return 1
    except (EOFError, KeyboardInterrupt):
        console.print("Configuração cancelada; nenhum projeto foi criado.")
        return 1

    try:
        scaffold = build_scaffold(profile, target.name, language=language)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"\nDestino: {target}")
    console.print(f"Scaffold {language} {profile}: ")
    for relative in scaffold:
        console.print(f"  - {relative}")
    console.print("A confirmação cobre os arquivos listados e as alterações de código desta execução. Verificações e instalação de dependências têm aprovações próprias.")
    scaffold_action = ToolSpec(
        "create_project", "Create the listed starter files inside the new project directory.", {},
        lambda _: None, confirmation=True, permission_scope="project",
    )
    if permission_mode == "manual":
        try:
            confirmed = input_fn("Criar o scaffold e gerar o projeto? [s/N] ").strip().lower() in {"s", "sim", "y", "yes"}
        except (EOFError, KeyboardInterrupt):
            confirmed = False
    elif permission_mode == "approve_for_me":
        confirmed, reason = review_action(provider, description, scaffold_action, {"path": str(target), "files": sorted(scaffold)})
        console.print(f"Revisor {'aprovou' if confirmed else 'negou'} o scaffold: {reason}")
    else:
        confirmed = True
    if not confirmed:
        console.print("Criação cancelada; nenhum arquivo foi gravado.")
        return 0

    try:
        create_project(target, profile, cwd=root, language=language)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Não foi possível criar o scaffold: {exc}[/red]")
        return 1

    source_file = next(item for item in scaffold if item.startswith("src/") and item.endswith((".py", ".js", ".ts")) and not item.endswith("/__init__.py"))
    test_file = next(item for item in scaffold if item.startswith("tests/"))
    source_module = (
        f"{source_file.removeprefix('src/').removesuffix('.py').replace('/', '.')}"
        if language == "python" else f"../{'dist' if language == 'typescript' else 'src'}/{Path(source_file).stem}.js"
    )

    all_tools = create_builtin_tools(target)
    tools = ToolRegistry()
    writable_paths = {source_file, test_file}
    for tool in all_tools.list():
        if tool.name in {"run_command", "git_status", "git_diff"}:
            continue
        if tool.name == "write_file":
            original_handler = tool.handler

            def write_scaffold_file(arguments, handler=original_handler):
                requested = Path(arguments["path"])
                resolved = (requested if requested.is_absolute() else target / requested).resolve()
                try:
                    relative = resolved.relative_to(target).as_posix()
                except ValueError as exc:
                    raise ValueError("Path must stay inside the project.") from exc
                if relative not in writable_paths:
                    raise ValueError(f"Project generation may edit only {source_file} and {test_file}.")
                return handler(arguments)

            tool.handler = write_scaffold_file
            tool.confirmation = True
        tools.register(tool)

    project_context = ProjectContext(target)
    project_context.add(source_file)
    project_context.add(test_file)
    agent = Agent(provider=provider, tools=tools, prefer_text_tool_calls=prefer_text_tool_calls, permission_mode=permission_mode)
    agent.set_mode(config.modes.get("project", config.modes.get("code")))
    if language == "python" and profile == "cli":
        profile_rules = (
        "For this CLI profile, use the existing argparse entry point and Python's unittest only. Use the standard library; "
        "do not import click, typer, pytest, or add third-party dependencies. Keep main(argv=None) callable and returning exit code 0 on success. "
        "Pass argv directly to argparse (parse_args(argv), without slicing it). "
        f"Keep all logic in the one source module. The only application import in tests must be `from {source_module} import name`; "
        f"never import a top-level module such as `{target.name}` or a package initializer. Do not invent extra modules. "
        "Every function imported by tests must exist in that source module with the exact requested name. "
        "Put core calculations in pure functions with ordinary scalar parameters, not argparse Namespace objects or dictionaries; main() calls those functions. "
        "Tests call each pure function with the same scalar parameters and exact expected values; do not expect main() to return business data. "
        "Test invalid business values with assertRaises(ValueError) on the pure function, not by calling argparse without capturing SystemExit. "
        "Only test behavior explicitly requested by the user; do not invent validation rules or extra features. "
        "Keep tests to a few focused cases and use simple one-line string inputs; avoid multiline string literals."
        )
    elif language == "python":
        profile_rules = (
        "For this API profile, keep the existing FastAPI app and use pytest with FastAPI TestClient/httpx already declared in pyproject.toml. "
        f"Keep routes in the one source module. The only application import in tests must be `from {source_module} import name`; "
        f"never import a top-level module such as `{target.name}` or a package initializer. Do not invent extra modules. "
        "Every function imported by tests must exist in that source module with the exact requested name. "
        "Use the standard library for other needs and do not add dependencies. "
        "Only test behavior explicitly requested by the user; do not invent validation rules or extra features. Keep tests to a few focused cases."
        )
    elif profile == "cli":
        profile_rules = (
            f"Use Node.js ES modules and node:util parseArgs in {source_file}; export a callable main(argv = process.argv.slice(2)). "
            f"Use node:test and node:assert in {test_file}, importing only from {source_module}. "
            "Use Node built-ins, do not add dependencies, and keep behavior in the one source file."
        )
    else:
        profile_rules = (
            f"Keep a Fastify 5 app and routes in {source_file}; write focused node:test tests using app.inject in {test_file}. "
            f"Tests import the app from {source_module}. Use only the scaffold dependencies and do not add packages. "
            + ("Keep TypeScript strict and preserve the provided tsconfig." if language == "typescript" else "")
        )
    generation_metrics = []
    request = (
        f"Complete this new {language.title()} project using the existing scaffold. Implement the requested behavior in {source_file} "
        f"and add focused tests in {test_file}. Modify only those two files. Keep the installed command or API entry point working, "
        f"preserve all other scaffold files and do not create a separate top-level replacement application. {profile_rules} "
        f"Use separate sequential tool calls: write {source_file} first, then read it, then write {test_file}. Keep both files concise. "
        "Use the project file tools only. Do not run commands, install packages, access the network, or write outside this project. "
        "Finish with a short summary of the files. Do not claim checks were run; verification happens after generation.\n\n"
        f"Project request: {description}"
    )

    def on_tool(event, tool, arguments):
        if event == "start":
            console.print(f"  · {tool.name}: {arguments.get('path', '')}")

    try:
        response = agent.ask(request, context_text=project_context.build_context(), approve=lambda *_: True, on_tool=on_tool)
        console.print(Markdown(response or "O scaffold foi criado; o modelo não retornou uma mensagem final."))
        generation_metrics.append(dict(agent.last_metrics))
        project_context.add(source_file)
        project_context.add(test_file)
        files_incomplete = any((target / relative).read_text(encoding="utf-8") == scaffold[relative] for relative in writable_paths)
        if files_incomplete:
            console.print("O modelo não concluiu as alterações nos arquivos de código e teste; vou tentar uma vez com uma instrução direta para usar write_file.")
            retry_request = (
                f"The previous reply did not change the project files. Use write_file now to implement the request in {source_file} "
                f"and add tests in {test_file}. {profile_rules} Call the tools; do not answer with a plan, a code block, or a claim that files changed. "
                "Do not edit any other path, run commands, install packages, or access the network.\n\n"
                f"Project request: {description}"
            )
            response = agent.ask(retry_request, context_text=project_context.build_context(), approve=lambda *_: True, on_tool=on_tool)
            console.print(Markdown(response or "O modelo não retornou um resumo após a segunda tentativa."))
            generation_metrics.append(dict(agent.last_metrics))
            project_context.add(source_file)
            project_context.add(test_file)
            files_incomplete = any((target / relative).read_text(encoding="utf-8") == scaffold[relative] for relative in writable_paths)
    except Exception as exc:
        console.print(f"[red]Falha na geração: {exc}[/red]")
        console.print(f"O scaffold inicial permanece em {target}.")
        return 1

    metrics = _merge_project_metrics(generation_metrics)
    usage = metrics.get("provider_usage", {})
    provider_output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    output_summary = (
        f"saída {provider_output_tokens} tokens (provider)"
        if provider_output_tokens is not None
        else f"saída textual ~{metrics.get('output_tokens_estimated', '?')} tokens"
    )
    console.print(
        f"[dim]Perfil project · entrada ~{metrics.get('input_tokens_estimated', '?')} tokens · "
        f"{output_summary} · {metrics.get('tool_calls', 0)} ferramentas · "
        f"{metrics.get('duration_ms', '?')} ms[/dim]"
    )
    if files_incomplete:
        console.print("[yellow]O scaffold ainda está genérico em pelo menos um arquivo de código ou teste; a aprovação dos testes verifica apenas o conteúdo atual.[/yellow]")

    def repair_generation(diagnostics):
        project_context.add(source_file)
        project_context.add(test_file)
        repair_request = (
            f"The approved verification command failed for this {language} {profile} project. Fix the failure in {source_file} and {test_file} only. "
            f"Keep application code only in {source_file} and tests only in {test_file}; never place test code in the application module. "
            f"Test imports must use {source_module}; define every imported name in that module and do not invent submodules. "
            "Treat the failing assertion as the repair contract: when a test calls a pure helper directly and expects ValueError, "
            "put that validation in the helper itself; validation in main() does not satisfy the test. Preserve passing tests. "
            f"Keep the existing dependencies and entry point. {profile_rules} Do not run commands, install packages, or access the network.\n\n"
            f"Verification output:\n{diagnostics[-5000:]}"
        )
        repaired = agent.ask(repair_request, context_text=project_context.build_context(), approve=lambda *_: True, on_tool=on_tool)
        console.print(Markdown(repaired or "O modelo não retornou um resumo da correção."))
        fix_metrics = agent.last_metrics
        console.print(
            f"[dim]Correção · saída textual ~{fix_metrics.get('output_tokens_estimated', '?')} tokens · "
            f"{fix_metrics.get('tool_calls', 0)} ferramentas · {fix_metrics.get('duration_ms', '?')} ms[/dim]"
        )

    verification_status = _verify_new_project(profile, target, console, input_fn, repair=repair_generation, language=language, permission_mode=permission_mode, provider=provider, objective=description)
    console.print(f"\nVerificação: {verification_status}.")
    console.print("Arquivos do scaffold:")
    for relative in sorted(scaffold):
        console.print(f"  - {relative}")
    if language == "python":
        if profile == "cli":
            next_steps = f"python -m pip install -e .; depois {source_module.split('.')[0]} --help"
        else:
            next_steps = f"python -m pip install -e '.[dev]'; depois fastapi dev {source_file}"
    else:
        next_steps = "npm install; depois npm start"
    console.print(f"Para continuar: cd {target} && {next_steps}")
    return 0


def _merge_project_metrics(samples):
    if not samples:
        return {}
    merged = dict(samples[-1])
    for key in ("request_build_ms", "input_tokens_estimated", "output_tokens_estimated", "tool_calls", "duration_ms"):
        values = [sample.get(key) for sample in samples if isinstance(sample.get(key), (int, float))]
        if values:
            merged[key] = round(sum(values), 1) if key.endswith("_ms") else sum(values)
    first_token = next((sample.get("first_token_ms") for sample in samples if sample.get("first_token_ms") is not None), None)
    if first_token is not None:
        merged["first_token_ms"] = first_token
    usage = {}
    for sample in samples:
        for key, value in sample.get("provider_usage", {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = usage.get(key, 0) + value
            else:
                usage[key] = value
    if usage:
        merged["provider_usage"] = usage
    return merged


def _verify_new_project(profile, target, console, input_fn, repair=None, *, language="python", permission_mode="manual", provider=None, objective=""):
    """Offer explicit installs and run local checks under the selected permission mode."""
    if language == "python":
        python = sys.executable
        if profile == "api":
            missing = [name for name in ("fastapi", "pytest", "httpx") if importlib.util.find_spec(name) is None]
            if missing:
                console.print(f"Não verificado: dependências ausentes ({', '.join(missing)}).")
                venv_python = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
                console.print(f"Instalação em ambiente virtual: python -m venv .venv; depois {venv_python} -m pip install -e '.[dev]'.")
                try:
                    install = input_fn("Deseja criar .venv e instalar as dependências agora? [s/N] ").strip().lower() in {"s", "sim", "y", "yes"}
                except (EOFError, KeyboardInterrupt):
                    install = False
                if not install:
                    return "não verificada"
                try:
                    venv.EnvBuilder(with_pip=True).create(target / ".venv")
                    python_path = target / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
                    installed = subprocess.run(
                        [str(python_path), "-m", "pip", "install", "-e", ".[dev]"],
                        cwd=target, capture_output=True, text=True, timeout=300, shell=False,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    console.print(f"Instalação não concluída: {exc}")
                    return "não verificada"
                if installed.returncode:
                    console.print(installed.stdout + installed.stderr)
                    console.print("Não verificado: a instalação falhou.")
                    return "não verificada"
                python = str(python_path)
            argv = [python, "-m", "pytest"]
        else:
            argv = [python, "-m", "unittest", "discover", "-s", "tests", "-v"]
    else:
        node = shutil.which("node")
        npm = shutil.which("npm")
        if not node or ((profile == "api" or language == "typescript") and not npm):
            console.print("Não verificado: instale Node.js 24 LTS e npm para executar este projeto.")
            return "não verificada"
        packages = []
        if profile == "api":
            packages.append("fastify")
        if language == "typescript":
            packages.extend(("typescript", "@types/node"))
        missing = [name for name in packages if not (target / "node_modules" / name / "package.json").is_file()]
        if missing:
            console.print(f"Não verificado: dependências ausentes ({', '.join(missing)}).")
            console.print("Instalação: npm install")
            try:
                install = input_fn("Deseja executar npm install agora? [s/N] ").strip().lower() in {"s", "sim", "y", "yes"}
            except (EOFError, KeyboardInterrupt):
                install = False
            if not install:
                return "não verificada"
            try:
                installed = subprocess.run([npm, "install"], cwd=target, capture_output=True, text=True, timeout=300, shell=False)
            except (OSError, subprocess.SubprocessError) as exc:
                console.print(f"Instalação não concluída: {exc}")
                return "não verificada"
            if installed.returncode:
                console.print((installed.stdout or "") + (installed.stderr or ""))
                console.print("Não verificado: a instalação falhou.")
                return "não verificada"
        argv = [node, "--test"] if profile == "cli" and language == "javascript" else [npm, "test"]

    environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(target), "PYTHONPATH": str(target / "src"), "CI": "1"}
    tool = ToolSpec("run_command", "Run the generated project's test command.", {}, lambda _: None, confirmation=True, permission_scope="command")

    def run_check():
        nonlocal permission_mode
        approved = permission_mode == "full_access"
        sandboxed = permission_mode == "full_access"
        if permission_mode == "approve_for_me":
            if not workspace_sandbox_available():
                console.print("Sandbox indisponível; esta verificação precisa de aprovação manual.")
            else:
                approved, reason = review_action(provider, objective, tool, {"argv": argv, "network_access": False})
                console.print(f"Revisor {'aprovou' if approved else 'negou'} a verificação: {reason}")
                if not approved:
                    status["value"] = "negada pelo revisor"
                    return None
                sandboxed = True
        if permission_mode == "manual" or (permission_mode == "approve_for_me" and not workspace_sandbox_available()):
            console.print("Verificação disponível: " + " ".join(argv))
            try:
                approved = input_fn("Executar a verificação agora? [s/N] ").strip().lower() in {"s", "sim", "y", "yes"}
            except (EOFError, KeyboardInterrupt):
                approved = False
        if not approved:
            status["value"] = "pendente"
            console.print("Verificação pendente; nenhum comando foi executado.")
            return None
        try:
            if sandboxed:
                if not workspace_sandbox_available():
                    raise SandboxUnavailable("O sandbox não está disponível; o comando foi bloqueado.")
                return run_workspace_command(argv, cwd=target, timeout=180, env=environment)
            return subprocess.run(argv, cwd=target, env=environment, capture_output=True, text=True, timeout=180, shell=False)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            status["value"] = "não verificada"
            console.print(f"Verificação não concluída: {exc}")
            return None

    status = {"value": "pendente"}
    result = run_check()
    if result is None:
        return status["value"]
    if result.stdout:
        console.print(result.stdout.rstrip())
    if result.stderr:
        console.print(result.stderr.rstrip())
    if result.returncode == 0:
        console.print("Verificação aprovada.")
        return "aprovada"

    console.print(f"Verificação falhou (código {result.returncode}).")
    if repair is None:
        return "falhou"
    try:
        repair((result.stdout or "") + "\n" + (result.stderr or ""))
    except Exception as exc:
        console.print(f"O modelo não conseguiu corrigir o projeto: {exc}")
        return "falhou"
    retry = run_check()
    if retry is None:
        return status["value"]
    if retry.stdout:
        console.print(retry.stdout.rstrip())
    if retry.stderr:
        console.print(retry.stderr.rstrip())
    if retry.returncode == 0:
        console.print("Verificação aprovada após correção.")
        return "aprovada após correção"
    console.print(f"Verificação ainda falhou (código {retry.returncode}).")
    return "falhou após correção"


def handle_command(command, tui, agent, config, manager, skills, project_context, session_manager, session, mcp_manager=None):
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
            readiness = check_provider_readiness(agent.provider, config.active_provider.type, config.model)
            tui.connection_status = readiness.status
            if readiness.ready:
                tui.show_success(f"Provider {config.provider} conectado.")
            else:
                tui.show_error(readiness.message)
                tui.show_info(readiness_hint(readiness, config.active_provider.type, config.model))
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
    if name == "/permissions":
        value = args_text.strip().lower().replace("_", "-")
        aliases = {"approve-for-me": "approve_for_me", "approve for me": "approve_for_me", "full-access": "full_access"}
        requested = aliases.get(value, value)
        if not value:
            tui.show_info(f"Modo de permissão ativo: {agent.permission_mode}")
            tui.show_info("Opções: manual, approve-for-me, full-access")
            return False, None, session
        if requested not in {"manual", "approve_for_me", "full_access"}:
            tui.show_error("Use /permissions manual, /permissions approve-for-me ou /permissions full-access.")
            return False, None, session
        try:
            agent.set_permission_mode(requested)
        except SandboxUnavailable as exc:
            tui.show_error(str(exc))
            return False, None, session
        config.permission_mode = agent.permission_mode
        tui.permission_mode = agent.permission_mode
        manager.save(config)
        tui.show_success(f"Modo de permissão ativo: {agent.permission_mode}")
        return False, None, session
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
        readiness = check_provider_readiness(agent.provider, config.active_provider.type, config.model)
        tui.connection_status = readiness.status
        if readiness.ready:
            tui.show_success(f"Provider {config.provider} conectado.")
        else:
            tui.show_error(readiness.message)
            tui.show_info(readiness_hint(readiness, config.active_provider.type, config.model))
        return False, None, session
    if name == "/mcp":
        handle_mcp(args, tui, mcp_manager)
        return False, None, session
    if name == "/status":
        tui.show_status()
        return False, None, session

    tui.show_error(f"Comando desconhecido: {command}")
    return False, None, session


def handle_mcp(args, tui, manager):
    if manager is None or not manager.servers:
        tui.show_info("Nenhum servidor MCP configurado em mcp_servers.")
        return
    action = args[0].lower() if args else "servers"
    try:
        if action == "servers":
            for name, config in manager.servers.items():
                tui.show_info(f"{name}: {config.get('command', '?')} ({config.get('transport', 'stdio')})")
            return
        if action == "tools":
            for tool in manager.tool_names:
                tui.show_info(tool)
            return
        if action == "resources" and len(args) >= 2:
            for item in manager.list_resources(args[1]):
                tui.show_info(f"{item.uri}  {item.name}")
            return
        if action == "read" and len(args) >= 3:
            tui.show_info(manager.read_resource(args[1], " ".join(args[2:])))
            return
        if action == "prompts" and len(args) >= 2:
            for item in manager.list_prompts(args[1]):
                tui.show_info(f"{item.name}  {item.description or ''}")
            return
        if action == "prompt" and len(args) >= 3:
            tui.show_info(manager.get_prompt(args[1], " ".join(args[2:])))
            return
        tui.show_error("Uso: /mcp [servers|tools|resources SERVER|read SERVER URI|prompts SERVER|prompt SERVER NAME]")
    except Exception as exc:
        tui.show_error(str(exc))


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
        tui.show_info("Use /provider use nome ou /provider add para configurar passo a passo.")
        return None

    if action == "use" and len(parts) >= 2:
        args_text = parts[1]
    elif action == "add":
        values = parts[1:]
        # Preserve the old one-line form; incomplete forms open the guided setup.
        if len(values) >= 4:
            name, provider_type, base_url, model = values[0], values[1], values[2], " ".join(values[3:])
            api_key_env = "OPENAI_API_KEY" if provider_type != "ollama" else ""
        else:
            first = values[0] if values else ""
            default_name = "local" if not first.startswith(("http://", "https://")) else "ollama_local"
            name = tui.ask_value("Nome do provider", default_name)
            if name is None:
                return None
            provider_type = tui.ask_value("Tipo (ollama/openai-compatible)", "ollama")
            if provider_type is None:
                return None
            provider_type = provider_type.lower().replace("-", "_")
            if provider_type in {"openai", "openai_compatible"}:
                provider_type = "openai_compatible"
            elif provider_type != "ollama":
                tui.show_error("Tipo inválido. Escolha ollama ou openai-compatible.")
                return None
            default_url = "https://api.openai.com/v1" if provider_type == "openai_compatible" else "http://localhost:11434"
            base_url = tui.ask_value("URL base", first if first.startswith(("http://", "https://")) else default_url)
            if base_url is None:
                return None
            if not base_url.startswith(("http://", "https://")):
                tui.show_error("A URL base precisa começar com http:// ou https://.")
                return None
            model_default = values[1] if len(values) > 1 else (first if first and not first.startswith(("http://", "https://")) and first != default_name else "")
            model = tui.ask_value("Modelo", model_default)
            if model is None or not model:
                if model == "":
                    tui.show_error("Informe o nome do modelo.")
                return None
            api_key_env = tui.ask_value("Variável de ambiente da chave API", "OPENAI_API_KEY") if provider_type == "openai_compatible" else ""
            if api_key_env is None:
                return None
        if provider_type not in {"ollama", "openai", "openai_compatible", "openai-compatible"}:
            tui.show_error("Tipo inválido. Escolha ollama ou openai-compatible.")
            return None
        provider_type = "openai_compatible" if provider_type != "ollama" else "ollama"
        config.providers[name] = ProviderConfig(name=name, type=provider_type, base_url=base_url, model=model, api_key_env=api_key_env)
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
    readiness = check_provider_readiness(agent.provider, config.active_provider.type, config.model)
    tui.connection_status = readiness.status
    tui.show_success(f"Modelo ativo: {args_text}")
    if not readiness.ready:
        tui.show_info(readiness_hint(readiness, config.active_provider.type, config.model))


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
    agent.set_mode(mode)
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
    agent.set_mode(config.modes.get(config.mode, config.modes.get("code")))
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
    tui.input_budget_tokens = agent.input_budget_tokens
    tui.max_tool_steps = agent.max_tool_steps
    tui.output_budget_tokens = agent.output_budget_tokens
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
