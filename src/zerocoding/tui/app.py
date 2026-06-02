"""
ZeroCoding TUI — Claude Code-style terminal interface.
UI compacta e responsiva adaptativa.
"""
import sys
import threading
import time
import itertools
import shutil
import os
from typing import Optional, List, Dict, Any

try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.live import Live
    from rich.rule import Rule
    from rich.padding import Padding
    from rich.table import Table
    from rich.box import SIMPLE, MINIMAL
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.styles import Style as PTStyle
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.filters import Condition
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


# ── Cores Roxo Pastel ────────────────────────────────────────────────────────
CLAUDE_PURPLE = "#B8A9C9"
CLAUDE_PURPLE_LIGHT = "#D4C4E0"
CLAUDE_PURPLE_DARK = "#9B8AA8"
CLAUDE_AMBER = "#C9B8D4"
CLAUDE_BG = "#1A1A1A"
CLAUDE_DARK = "#0D0D0D"
CLAUDE_GRAY = "#6B7280"
CLAUDE_LIGHT = "#F5F5F5"
CLAUDE_GREEN = "#A8D4C4"
CLAUDE_BLUE = "#B8C9D4"
CLAUDE_RED = "#D4B8B8"
CLAUDE_YELLOW = "#D4C9B8"
CLAUDE_USER_BG = "#1E1B2E"
CLAUDE_BORDER = "#3D3652"

COMMANDS = [
    ("/exit", "Sair"), ("/clear", "Limpar"), ("/skills", "Skills"),
    ("/help", "Ajuda"), ("/status", "Status"),
]


# ── Slash Command Completer ──────────────────────────────────────────────────
if HAS_PROMPT_TOOLKIT:
    class SlashCommandCompleter(Completer):
        def __init__(self, commands):
            self.commands = commands

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.lstrip()
            if not text.startswith("/"):
                return
            for command, description in self.commands:
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text), display_meta=description)
else:
    class SlashCommandCompleter:
        def __init__(self, commands):
            self.commands = commands
        def get_completions(self, document, complete_event):
            return


# ── Terminal Size Detector ───────────────────────────────────────────────────
class TerminalSize:
    """Detecta tamanho do terminal e adapta layout."""
    
    @staticmethod
    def get_width():
        try:
            return shutil.get_terminal_size().columns
        except:
            return 80
    
    @staticmethod
    def get_height():
        try:
            return shutil.get_terminal_size().lines
        except:
            return 24
    
    @staticmethod
    def is_small():
        return TerminalSize.get_width() < 80
    
    @staticmethod
    def is_tiny():
        return TerminalSize.get_width() < 60


# ── Compact ASCII Art ────────────────────────────────────────────────────────
GHOST_TINY = "👻"
GHOST_SMALL = "[▄████▄]"
GHOST_FULL = """
 ▄████  
████████ 
██ ██ ██ 
████████ 
████████ 
██ ██ ██ 
▀▀ ▀ ▀▀ 
"""


# ── Thinking Animation Compacta ─────────────────────────────────────────────
class ThinkingAnimation:
    """Animação de thinking compacta."""

    SPINNER = ["⠋", "⠙", "", "⠸", "", "⠴", "", "⠧", "", "⠏"]

    def __init__(self, console: Console, message: str = "Thinking"):
        self.console = console
        self.message = message
        self._stop = False
        self._live: Optional[Live] = None
        self._thread = None
        self._frame_idx = 0
        self._is_small = TerminalSize.is_small()

    def _get_renderable(self):
        if self._is_small:
            spinner = self.SPINNER[self._frame_idx % len(self.SPINNER)]
            msg = self.message[:20] + "..." if len(self.message) > 20 else self.message
            return Text(f"  {spinner} {msg}...", style=f"bold {CLAUDE_PURPLE}")
        else:
            spinner = self.SPINNER[self._frame_idx % len(self.SPINNER)]
            content = Text()
            content.append(f"  {GHOST_TINY} ", style=f"bold {CLAUDE_PURPLE}")
            content.append(f"{spinner} ", style=f"bold {CLAUDE_PURPLE_LIGHT}")
            content.append(f"{self.message}...", style="dim")
            return content

    def start(self):
        self._stop = False
        self._live = Live(
            self._get_renderable(),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        )
        self._live.start()

        def animate():
            while not self._stop:
                self._frame_idx += 1
                if self._live:
                    self._live.update(self._get_renderable())
                time.sleep(0.08)

        self._thread = threading.Thread(target=animate, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=1)
        if self._live:
            self._live.stop()
            self._live = None


# ── Streaming Display Compacto ──────────────────────────────────────────────
class StreamingDisplay:
    """Display streaming compacto."""

    def __init__(self, console: Console):
        self.console = console
        self._live: Optional[Live] = None
        self._buffer = ""

    def start(self):
        self._buffer = ""
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=15,
            vertical_overflow="visible",
        )
        self._live.start()

    def _render(self):
        header = Text()
        header.append(f"  {GHOST_TINY} ", style=f"bold {CLAUDE_PURPLE}")
        header.append("ZeroCoding", style=f"bold {CLAUDE_PURPLE}")
        content = Text()
        content.append("\n")
        content.append(self._buffer, style="white")
        return Group(header, content)

    def add_token(self, token: str):
        self._buffer += token
        if self._live:
            self._live.update(self._render())

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None
        self.console.print()
        header = Text()
        header.append(f"  {GHOST_TINY} ", style=f"bold {CLAUDE_PURPLE}")
        header.append("ZeroCoding", style=f"bold {CLAUDE_PURPLE}")
        self.console.print(header)
        self.console.print()
        
        try:
            md = Markdown(self._buffer, code_theme="monokai")
            self.console.print(Padding(md, (0, 0, 0, 2)))
        except Exception:
            self.console.print(Padding(Text(self._buffer, style="white"), (0, 0, 0, 2)))
        self.console.print(Rule(style=f"dim {CLAUDE_BORDER}"))


# ── Main TUI Class ───────────────────────────────────────────────────────────
class ZerocodingTUI:
    """Terminal UI compacta e responsiva."""

    def __init__(self, provider_name: str = "openai", model: str = "gpt-4o-mini", theme: str = "dark"):
        self.provider_name = provider_name
        self.model = model
        self.theme = theme
        self.history: List[Dict[str, Any]] = []
        self.console = Console(force_terminal=True, color_system="truecolor", highlight=False, force_interactive=True)
        self.commands = COMMANDS
        self._total_tokens = 0
        self._turn_count = 0
        self._start_time = time.time()
        self._is_small = TerminalSize.is_small()
        self._is_tiny = TerminalSize.is_tiny()
        self._prompt_session = None

        if HAS_PROMPT_TOOLKIT:
            self._setup_prompt_toolkit()
        else:
            self._prompt_session = None

    def _setup_prompt_toolkit(self):
        """Configura o Prompt Toolkit separadamente."""
        kb = KeyBindings()
        @kb.add('c-j')
        def insert_newline(event):
            event.current_buffer.insert_text('\n')
        @kb.add('enter', filter=~Condition(lambda: False))
        def submit_or_newline(event):
            event.current_buffer.validate_and_handle()

        pt_style = PTStyle.from_dict({
            "prompt": f"{CLAUDE_PURPLE} bold",
            "completion-menu.completion": "bg:#1A1A1A #F5F5F5",
            "completion-menu.completion.current": f"bg:{CLAUDE_PURPLE} #0D0D0D bold",
            "bottom-toolbar": "bg:#0D0D0D #6B7280",
            "bottom-toolbar.text": "#6B7280",
        })

        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            completer=SlashCommandCompleter(self.commands),
            complete_while_typing=True,
            style=pt_style,
            key_bindings=kb,
            multiline=False,
        )

    # ── Status Bar Responsiva ────────────────────────────────────────────────
    def _render_status_bar(self) -> Panel:
        """Status bar adaptativa."""
        elapsed = int(time.time() - self._start_time)
        mins, secs = divmod(elapsed, 60)

        if self._is_tiny:
            bar = Text()
            bar.append(f"{self.provider_name}/{self.model}", style="bold white")
            bar.append(" │ ", style="dim")
            bar.append(f"{self._turn_count}t", style=f"dim {CLAUDE_GRAY}")
            bar.append(" │ ", style="dim")
            bar.append(f"{mins}:{secs:02d}", style=f"dim {CLAUDE_GRAY}")
        elif self._is_small:
            bar = Text()
            bar.append(f"{self.provider_name}", style="bold white")
            bar.append("/", style="dim")
            bar.append(f"{self.model[:15]}", style=f"dim {CLAUDE_GRAY}")
            bar.append(" │ ", style="dim")
            bar.append(f"{self._turn_count} turns", style=f"dim {CLAUDE_GRAY}")
            bar.append(" │ ", style="dim")
            bar.append(f"{len(self.history)} msgs", style=f"dim {CLAUDE_GRAY}")
        else:
            bar = Text()
            bar.append(" ● ", style=f"bold {CLAUDE_GREEN}")
            bar.append(f"{self.provider_name}", style="bold white")
            bar.append(" / ", style=f"dim {CLAUDE_GRAY}")
            bar.append(f"{self.model}", style=f"dim {CLAUDE_GRAY}")
            bar.append("  │  ", style=f"dim {CLAUDE_BORDER}")
            bar.append(f"{self._turn_count} turns", style=f"dim {CLAUDE_GRAY}")
            bar.append("  │  ", style=f"dim {CLAUDE_BORDER}")
            bar.append(f"{mins}:{secs:02d}", style=f"dim {CLAUDE_GRAY}")
            bar.append("  │  ", style=f"dim {CLAUDE_BORDER}")
            bar.append(f"{len(self.history)} msgs", style=f"dim {CLAUDE_GRAY}")

        return Panel(bar, border_style=f"bold {CLAUDE_PURPLE}", padding=(0, 1) if not self._is_tiny else (0, 0), style=f"{CLAUDE_DARK}")

    # ── Header Responsivo ────────────────────────────────────────────────────
    def header(self):
        """Header adaptativo ao tamanho da tela."""
        # Limpa tela de forma segura
        self.console.clear()
        self.console.print()
        
        # Status bar sempre visível
        self.console.print(self._render_status_bar())
        self.console.print()
        
        if self._is_tiny:
            header = Text()
            header.append(f"  {GHOST_TINY} ", style=f"bold {CLAUDE_PURPLE}")
            header.append("ZeroCoding", style="bold white")
            self.console.print(header)
        elif self._is_small:
            header = Text()
            header.append(f"  {GHOST_SMALL} ", style=f"bold {CLAUDE_PURPLE}")
            header.append("ZeroCoding", style="bold white")
            header.append(" — ", style="dim")
            header.append("Coding Assistant", style=f"dim {CLAUDE_GRAY}")
            self.console.print(header)
        else:
            self.console.print(Text(GHOST_FULL, style=f"bold {CLAUDE_PURPLE}"))
            info = Text()
            info.append("  ZeroCoding", style="bold white")
            info.append("\n  Personal Coding Assistant", style=f"dim {CLAUDE_GRAY}")
            self.console.print(info)
        
        if not self._is_tiny:
            self.console.print()
            self.console.print(Rule(style=f"dim {CLAUDE_BORDER}"))
            self.console.print()

    # ── Welcome Compacto ─────────────────────────────────────────────────────
    def show_welcome(self):
        """Boas-vindas compacta."""
        if self._is_tiny:
            welcome = Text()
            welcome.append(f"  {GHOST_TINY} ZeroCoding\n", style=f"bold {CLAUDE_PURPLE}")
            welcome.append("  /help para comandos", style="dim")
        elif self._is_small:
            welcome = Text()
            welcome.append(f"  {GHOST_SMALL} ZeroCoding\n\n", style=f"bold {CLAUDE_PURPLE}")
            welcome.append("  Digite /help para ver comandos\n", style="dim")
            welcome.append("  Ctrl+J = nova linha | Enter = enviar", style="dim")
        else:
            welcome = Text()
            welcome.append(f"  {GHOST_TINY} Bem-vindo ao ", style="dim")
            welcome.append("ZeroCoding", style=f"bold {CLAUDE_PURPLE}")
            welcome.append("\n  Digite /help para comandos | Ctrl+J = nova linha | Enter = enviar\n", style="dim")
        self.console.print(welcome)
        self.console.print()

    # ── Render Messages Compactas ────────────────────────────────────────────
    def display_message(self, role: str, content: str, is_code: bool = False):
        """Mensagens compactas."""
        self.history.append({"role": role, "content": content, "is_code": is_code})

        if role == "user":
            self._render_user_message(content)
        elif role == "assistant":
            self._render_assistant_message(content, is_code)
        elif role == "error":
            self._render_error(content)

    def _render_user_message(self, content: str):
        """Mensagem do usuário compacta."""
        self.console.print()
        label = Text()
        label.append("  You", style=f"bold {CLAUDE_BLUE}")
        self.console.print(label)
        
        width = TerminalSize.get_width()
        if len(content) > width - 4 and not self._is_tiny:
            content = content[:width-7] + "..."
        
        if self._is_tiny:
            self.console.print(f"  {content}", style="white")
        else:
            panel = Panel(Text(content, style="white"), border_style=f"dim {CLAUDE_BORDER}", padding=(0, 1), style=f"{CLAUDE_USER_BG}")
            self.console.print(Padding(panel, (0, 0, 0, 2)))

    def _render_assistant_message(self, content: str, is_code: bool = False):
        """Mensagem do assistente compacta."""
        self.console.print()
        header = Text()
        header.append(f"  {GHOST_TINY} ", style=f"bold {CLAUDE_PURPLE}")
        header.append("ZeroCoding", style=f"bold {CLAUDE_PURPLE}")
        self.console.print(header)
        
        if is_code:
            try:
                syntax = Syntax(content, "python", theme="monokai", line_numbers=False, word_wrap=True)
                self.console.print(Padding(syntax, (0, 0, 0, 2)))
            except Exception:
                self.console.print(Padding(Text(content, style="white"), (0, 0, 0, 2)))
        else:
            try:
                md = Markdown(content, code_theme="monokai")
                self.console.print(Padding(md, (0, 0, 0, 2)))
            except Exception:
                self.console.print(Padding(Text(content, style="white"), (0, 0, 0, 2)))
        
        if not self._is_tiny:
            self.console.print(Rule(style=f"dim {CLAUDE_BORDER}"))
        self._turn_count += 1

    def _render_error(self, message: str):
        """Erro compacto."""
        self.console.print()
        error_text = Text()
        error_text.append("  ⚠ ", style=f"bold {CLAUDE_RED}")
        error_text.append(message, style=CLAUDE_RED)
        self.console.print(error_text)

    # ── Streaming Display ────────────────────────────────────────────────────
    def create_streaming_display(self) -> StreamingDisplay:
        return StreamingDisplay(self.console)

    # ── Thinking ──────────────────────────────────────────────────────────────
    def show_thinking(self, message: str = "Thinking") -> ThinkingAnimation:
        anim = ThinkingAnimation(self.console, message)
        anim.start()
        return anim

    # ── Input Prompt Compacto ────────────────────────────────────────────────
    def input_prompt(self) -> str:
        """Prompt compacto."""
        if HAS_PROMPT_TOOLKIT and self._prompt_session is not None:
            try:
                bottom = "Ctrl+J=nova | Enter=enviar | /help" if self._is_small else "Ctrl+J=nova linha | Enter=enviar | /help /clear /exit | ↑↓ histórico"
                result = self._prompt_session.prompt(
                    HTML(f'<style color="{CLAUDE_PURPLE}">  ❯ </style>'),
                    bottom_toolbar=HTML(f'<style color="{CLAUDE_GRAY}">{bottom}</style>'),
                )
                return result.strip()
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return "/exit"

        try:
            self.console.print(f"  [bold {CLAUDE_PURPLE}]❯ [/bold {CLAUDE_PURPLE}]", end="", highlight=False)
            result = input()
            return result.strip()
        except (KeyboardInterrupt, EOFError):
            return ""

    # ── Skills Compacto ──────────────────────────────────────────────────────
    def show_skills(self, skills: list):
        """Skills compactas."""
        self.console.print()
        header = Text()
        header.append(f"  📚 ", style=f"bold {CLAUDE_PURPLE}")
        header.append("Skills", style="bold white")
        self.console.print(header)

        if not skills:
            self.console.print("    [dim]Nenhuma skill.[/dim]")
            return

        if self._is_tiny:
            for skill in skills:
                self.console.print(f"  • {skill.name}: {skill.description[:40]}")
        else:
            table = Table(box=MINIMAL, border_style=f"dim {CLAUDE_BORDER}", show_header=False, padding=(0, 1))
            table.add_column("Nome", style=f"bold {CLAUDE_AMBER}")
            table.add_column("Descrição", style="white")
            for skill in skills:
                table.add_row(f"  {skill.name}", skill.description[:60] if self._is_small else skill.description)
            self.console.print(Padding(table, (0, 0, 0, 2)))

    # ── Help Compacto ────────────────────────────────────────────────────────
    def show_help(self):
        """Help compacto."""
        self.console.print()
        header = Text()
        header.append(f"  📖 ", style=f"bold {CLAUDE_PURPLE}")
        header.append("Comandos", style="bold white")
        self.console.print(header)

        if self._is_tiny:
            for cmd, desc in self.commands:
                self.console.print(f"  {cmd} - {desc}")
        else:
            table = Table(box=MINIMAL, show_header=False, padding=(0, 1))
            table.add_column("Comando", style=f"bold {CLAUDE_PURPLE}", width=10)
            table.add_column("Descrição", style="white")
            for cmd, desc in self.commands:
                table.add_row(f"  {cmd}", desc)
            self.console.print(Padding(table, (0, 0, 0, 2)))

    # ── Error / Info / Success / Warning ──────────────────────────────────────
    def show_error(self, message: str):
        self._render_error(message)

    def show_info(self, message: str):
        self.console.print()
        info = Text()
        info.append("  ℹ ", style=f"bold {CLAUDE_BLUE}")
        info.append(message, style="dim")
        self.console.print(info)

    def show_success(self, message: str):
        self.console.print()
        success = Text()
        success.append("  ✓ ", style=f"bold {CLAUDE_GREEN}")
        success.append(message, style=CLAUDE_GREEN)
        self.console.print(success)

    def show_warning(self, message: str):
        self.console.print()
        warn = Text()
        warn.append("  ⚠ ", style=f"bold {CLAUDE_YELLOW}")
        warn.append(message, style=CLAUDE_YELLOW)
        self.console.print(warn)

    # ── Clear (CORRIGIDO) ─────────────────────────────────────────────────────
    def clear(self):
        """Limpa tela corretamente."""
        self.history = []
        self._turn_count = 0
        self._start_time = time.time()
        self._is_small = TerminalSize.is_small()
        self._is_tiny = TerminalSize.is_tiny()
        
        # Limpeza segura do terminal
        self.console.clear()
        self.console.print()
        
        # Redesenha tudo do zero
        self.header()
        self.show_welcome()

    # ── Status ──────────────────────────────────────────────────────────────
    def show_status(self):
        """Status compacto."""
        elapsed = int(time.time() - self._start_time)
        mins, secs = divmod(elapsed, 60)

        if self._is_tiny:
            self.console.print(f"\n  Provider: {self.provider_name}")
            self.console.print(f"  Model: {self.model}")
            self.console.print(f"  Turns: {self._turn_count} | Msgs: {len(self.history)}")
            self.console.print(f"  Uptime: {mins}:{secs:02d}")
        else:
            table = Table(box=MINIMAL, show_header=False, padding=(0, 1))
            table.add_column(style=f"bold {CLAUDE_GRAY}")
            table.add_column(style="white")
            table.add_row("  Provider", self.provider_name)
            table.add_row("  Model", self.model)
            table.add_row("  Turns", str(self._turn_count))
            table.add_row("  Messages", str(len(self.history)))
            table.add_row("  Uptime", f"{mins}:{secs:02d}")
            self.console.print(Panel(table, border_style=f"dim {CLAUDE_PURPLE}", title=f"[{CLAUDE_PURPLE}]📊 Status[/]", title_align="left"))

    # ── Cost ─────────────────────────────────────────────────────────────────
    def show_cost(self):
        """Custo compacto."""
        if self._is_tiny:
            self.console.print(f"\n  Turns: {self._turn_count}")
            self.console.print(f"  Messages: {len(self.history)}")
            self.console.print(f"  Provider: {self.provider_name}")
        else:
            self.console.print(Panel(
                f"[dim]Turnos:[/dim] [bold]{self._turn_count}[/bold]\n"
                f"[dim]Mensagens:[/dim] [bold]{len(self.history)}[/bold]\n"
                f"[dim]Provider:[/dim] [bold]{self.provider_name}[/bold]",
                border_style=f"dim {CLAUDE_PURPLE}",
                title=f"[{CLAUDE_PURPLE}]💰 Custo[/]",
                title_align="left",
            ))

    # ── Goodbye ───────────────────────────────────────────────────────────────
    def goodbye(self):
        """Despedida compacta."""
        self.console.print()
        if self._is_tiny:
            bye = Text()
            bye.append(f"  {GHOST_TINY} Até logo!", style=f"bold {CLAUDE_PURPLE}")
        else:
            bye = Text()
            bye.append(f"  {GHOST_TINY} Até logo!", style=f"bold {CLAUDE_PURPLE}")
            bye.append(" ▄████", style="dim")
        self.console.print(bye)
        self.console.print()