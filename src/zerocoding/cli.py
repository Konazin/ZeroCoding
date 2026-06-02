import argparse
import sys
from pathlib import Path
import time

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.rule import Rule
from rich.padding import Padding

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style
    HAS_PT = True
except ImportError:
    HAS_PT = False

from .core.agent import Agent
from .core.config import Config
from .core.dotenv import load_env
from .core.router import build_provider
from .memory.sqlite import SQLiteMemory
from .skills.loader import load_skills


# ── Cores Roxo Pastel ────────────────────────────────────────────────────────
PURPLE = "#B8A9C9"
PURPLE_LIGHT = "#D4C4E0"
PURPLE_DARK = "#9B8AA8"
GRAY = "#6B7280"
BG = "#0D0D0D"

# ── Fantasminha ASCII ───────────────────────────────────────────────────────
GHOST = """
 ▄████  
████████ 
██ ██ ██ 
████████ 
████████ 
██ ██ ██ 
▀▀ ▀ ▀▀ 
"""

COMMANDS = {
    "/exit": "Sair",
    "/clear": "Limpar",
    "/help": "Ajuda",
    "/skills": "Skills",
}


def main(argv=None):
    load_env()

    parser = argparse.ArgumentParser(prog="zerocoding")
    parser.add_argument("-m", "--message", help="Mensagem")
    parser.add_argument("--provider", choices=["openai", "ollama"])
    parser.add_argument("--list-skills", action="store_true")
    parser.add_argument("--clear-memory", action="store_true")
    args = parser.parse_args(argv)

    # Config
    try:
        config = Config.load(override_provider=args.provider)
        provider = build_provider(config)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1

    # Memory
    memory_path = Path(config.memory_path).expanduser()
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory = SQLiteMemory(str(memory_path))
    if args.clear_memory:
        memory.clear()

    # Skills
    skills = load_skills(config.skills_path)
    agent = Agent(provider=provider, memory=memory, skills=skills)

    # Console Rich
    console = Console(force_terminal=True, color_system="truecolor")

    # ── List skills ─────────────────────────────────────────────────────
    if args.list_skills:
        if not skills:
            console.print("[dim]Nenhuma skill.[/dim]")
        else:
            for s in skills:
                console.print(f"  {s.name}: {s.description}")
        return 0

    # ── Single message ──────────────────────────────────────────────────
    if args.message:
        print_header(console, config)
        console.print(f"[bold {PURPLE}]You[/bold {PURPLE}]: {args.message}\n")
        
        console.print(f"[bold {PURPLE}]✻ Pensando...[/bold {PURPLE}]", end="\r")
        try:
            response = agent.ask(args.message)
            console.print(" " * 60, end="\r")  # Limpa "pensando"
            console.print(f"[bold {PURPLE}]✻ ZeroCoding[/bold {PURPLE}]\n")
            console.print(Markdown(response))
            console.print(Rule(style=f"dim {GRAY}"))
        except Exception as e:
            console.print(" " * 60, end="\r")
            console.print(f"[red]Erro: {e}[/red]")
        return 0

    # ── Interactive mode ────────────────────────────────────────────────
    print_header(console, config)
    print_welcome(console)

    # Setup prompt toolkit
    if HAS_PT:
        style = Style.from_dict({"prompt": PURPLE})
        session = PromptSession(
            history=InMemoryHistory(),
            style=style,
        )
    else:
        session = None

    turn_count = 0

    while True:
        try:
            if HAS_PT:
                prompt = session.prompt(f"[{PURPLE}]  ❯ [/{PURPLE}]")
            else:
                console.print(f"[bold {PURPLE}]  ❯ [/bold {PURPLE}]", end="")
                prompt = input()
        except (EOFError, KeyboardInterrupt):
            console.print()
            print_goodbye(console)
            return 0

        prompt = prompt.strip()
        if not prompt:
            continue

        # Comandos
        if prompt.startswith("/"):
            cmd = prompt[1:].lower()
            if cmd in {"exit", "quit", "q"}:
                print_goodbye(console)
                return 0
            elif cmd == "clear":
                console.clear()
                print_header(console, config)
                print_welcome(console)
                continue
            elif cmd == "help":
                console.print("\n[bold]Comandos:[/bold]")
                for c, desc in COMMANDS.items():
                    console.print(f"  [bold {PURPLE}]{c}[/bold {PURPLE}] - {desc}")
                continue
            elif cmd == "skills":
                if not skills:
                    console.print("[dim]Nenhuma skill.[/dim]")
                else:
                    console.print("\n[bold]Skills:[/bold]")
                    for s in skills:
                        console.print(f"  [bold {PURPLE}]{s.name}[/bold {PURPLE}]: {s.description}")
                continue
            else:
                console.print(f"[red]Comando desconhecido: {prompt}[/red]")
                continue

        # Mensagem normal
        console.print(f"[bold {PURPLE}]You[/bold {PURPLE}]: {prompt}\n")
        
        # Thinking
        console.print(f"[bold {PURPLE}]✻ Pensando...[/bold {PURPLE}]", end="\r")
        
        try:
            start = time.time()
            response = agent.ask(prompt)
            elapsed = time.time() - start
            
            # Limpa "pensando"
            console.print(" " * 60, end="\r")
            
            # Header da resposta
            console.print(f"[bold {PURPLE}]✻ ZeroCoding[/bold {PURPLE}]\n")
            
            # Resposta
            console.print(Markdown(response))
            console.print(Rule(style=f"dim {GRAY}"))
            
            turn_count += 1
            
        except Exception as e:
            console.print(" " * 60, end="\r")
            console.print(f"[red]⚠ Erro: {e}[/red]\n")

    return 0


def print_header(console: Console, config):
    """Imprime header com fantasminha."""
    console.print()
    
    # Fantasminha ASCII
    for line in GHOST.split("\n"):
        if line.strip():
            console.print(f"[bold {PURPLE}]{line}[/bold {PURPLE}]")
    
    console.print(f"[bold white]  ZeroCoding[/bold white]")
    console.print(f"[dim]  {config.provider}/{config.model}[/dim]")
    console.print()
    console.print(Rule(style=f"dim {GRAY}"))
    console.print()


def print_welcome(console: Console):
    """Imprime mensagem de boas-vindas."""
    console.print(f"  [dim]Bem-vindo! Digite [/dim][bold {PURPLE}]/help[/bold {PURPLE}][dim] para comandos.[/dim]")
    console.print(f"  [dim]Use [/dim][bold {PURPLE}]/clear[/bold {PURPLE}][dim] para limpar a tela.[/dim]\n")


def print_goodbye(console: Console):
    """Imprime despedida."""
    console.print()
    console.print(f"  [bold {PURPLE}]✻ Até logo![/bold {PURPLE}] [dim]▄████[/dim]")
    console.print()


if __name__ == "__main__":
    sys.exit(main())