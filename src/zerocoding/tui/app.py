"""
ZeroCoding TUI.

Interface principal em Rich + prompt_toolkit, com visual de transcript de
terminal: texto contínuo, pouco cromo e acento roxo discreto.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.padding import Padding
    from rich.syntax import Syntax
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from zerocoding import __version__

from .theme import (
    BG as ZERO_BG,
    COMMANDS,
    DARK as ZERO_DARK,
    GHOST_FULL,
    GHOST_SMALL,
    GHOST_TINY,
    GRAY as ZERO_GRAY,
    GREEN as ZERO_GREEN,
    LIGHT as ZERO_LIGHT,
    PURPLE as ZERO_PURPLE,
    PURPLE_LIGHT as ZERO_PURPLE_LIGHT,
    RED as ZERO_RED,
    USER_BG as ZERO_USER_BG,
    YELLOW as ZERO_YELLOW,
)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle

    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


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


class TerminalSize:
    """Detecta tamanho do terminal e adapta pequenos detalhes."""

    @staticmethod
    def get_width() -> int:
        try:
            return shutil.get_terminal_size().columns
        except OSError:
            return 80

    @staticmethod
    def is_small() -> bool:
        return TerminalSize.get_width() < 90

    @staticmethod
    def is_tiny() -> bool:
        return TerminalSize.get_width() < 62


def ellipsize(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


class ThinkingAnimation:
    """Linha transitória para chamadas não-streaming."""

    def __init__(self, console: Console, message: str = "Coding"):
        self.console = console
        self.message = message
        self._live: Optional[Live] = None

    def start(self):
        self._live = Live(
            Text(f"* {self.message}... (esc to interrupt)", style=f"italic {ZERO_PURPLE_LIGHT}"),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        )
        self._live.start()

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None


class StreamingDisplay:
    """Renderiza resposta em streaming como uma entrada de transcript."""

    def __init__(self, console: Console, on_finish: Optional[Callable[[str], None]] = None):
        self.console = console
        self._on_finish = on_finish
        self._live: Optional[Live] = None
        self._buffer = ""
        self._started_at = 0.0
        self._finished = False

    def start(self):
        self._buffer = ""
        self._finished = False
        self._started_at = time.time()
        self._live = Live(
            self._render(live=True),
            console=self.console,
            refresh_per_second=15,
            vertical_overflow="visible",
        )
        self._live.start()

    def _render(self, live: bool = False):
        lines = []
        if live:
            lines.append(Text("* Coding... (esc to interrupt)", style=f"italic {ZERO_PURPLE_LIGHT}"))

        body = self._buffer if self._buffer else " "
        content = Text()
        content.append("• ", style=f"bold {ZERO_PURPLE}")
        content.append(body, style=ZERO_LIGHT)
        lines.append(content)
        return Group(*lines)

    def add_token(self, token: str):
        self._buffer += token
        if self._live:
            self._live.update(self._render(live=True))

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None

        self._print_assistant_response(self._buffer)
        if self._on_finish and not self._finished:
            self._on_finish(self._buffer)
            self._finished = True
        self.console.print()

    def _print_assistant_response(self, content: str):
        try:
            rendered = Markdown(content, code_theme="monokai")
        except Exception:
            rendered = Text(content, style=ZERO_LIGHT)

        self.console.print(Text("• ", style=f"bold {ZERO_PURPLE}"), end="")
        self.console.print(rendered)


class ZerocodingTUI:
    """Terminal UI minimalista e responsiva."""

    def __init__(
        self,
        provider_name: str = "openai",
        model: str = "gpt-4o-mini",
        theme: str = "dark",
        mode: str = "code",
        skills: Optional[list[str]] = None,
        session_id: str = "",
        connection_status: str = "unknown",
    ):
        if not HAS_RICH:
            raise RuntimeError("ZeroCoding TUI requires rich. Install project dependencies before starting the TUI.")

        self.provider_name = provider_name
        self.model = model
        self.theme = theme
        self.mode = mode
        self.skills = skills or []
        self.session_id = session_id
        self.connection_status = connection_status
        self.history: List[Dict[str, Any]] = []
        self.console = Console(force_terminal=True, color_system="truecolor", highlight=False, force_interactive=True)
        self.commands = COMMANDS
        self._turn_count = 0
        self._start_time = time.time()
        self._is_small = TerminalSize.is_small()
        self._is_tiny = TerminalSize.is_tiny()
        self._prompt_session = None

        if HAS_PROMPT_TOOLKIT:
            self._setup_prompt_toolkit()

    def _refresh_size(self):
        self._is_small = TerminalSize.is_small()
        self._is_tiny = TerminalSize.is_tiny()
        return TerminalSize.get_width()

    def _setup_prompt_toolkit(self):
        kb = KeyBindings()

        @kb.add("c-j")
        def insert_newline(event):
            event.current_buffer.insert_text("\n")

        pt_style = PTStyle.from_dict(
            {
                "prompt": f"{ZERO_PURPLE} bold",
                "completion-menu.completion": f"bg:{ZERO_BG} {ZERO_LIGHT}",
                "completion-menu.completion.current": f"bg:{ZERO_USER_BG} {ZERO_LIGHT} bold",
                "completion-menu.meta.completion": f"bg:{ZERO_BG} {ZERO_GRAY}",
                "bottom-toolbar": f"bg:{ZERO_DARK} {ZERO_GRAY}",
            }
        )

        self._prompt_session = PromptSession(
            history=InMemoryHistory(),
            completer=SlashCommandCompleter(self.commands),
            complete_while_typing=True,
            style=pt_style,
            key_bindings=kb,
            multiline=False,
        )

    def header(self):
        """Header inicial simples, sem Header/Footer de framework."""
        self._refresh_size()
        self.console.clear()
        self.console.print()

        ghost = GHOST_TINY if self._is_tiny else GHOST_SMALL if self._is_small else GHOST_FULL.rstrip()
        if not self._is_tiny:
            self.console.print(Text(ghost, style=f"bold {ZERO_PURPLE}"))

        title = Text()
        if self._is_tiny:
            title.append(f"{GHOST_TINY} ", style=f"bold {ZERO_PURPLE}")
        title.append("ZeroCoding", style=f"bold {ZERO_LIGHT}")
        title.append(f" v{__version__}", style=f"dim {ZERO_GRAY}")
        self.console.print(title)

        meta = Text()
        meta.append("provider ", style=f"dim {ZERO_GRAY}")
        meta.append(self.provider_name, style=ZERO_PURPLE_LIGHT)
        meta.append("  model ", style=f"dim {ZERO_GRAY}")
        meta.append(ellipsize(self.model, 36 if self._is_small else 72), style=ZERO_LIGHT)
        meta.append("  mode ", style=f"dim {ZERO_GRAY}")
        meta.append(self.mode, style=ZERO_PURPLE_LIGHT)
        self.console.print(meta)

        state = Text()
        if self.skills:
            state.append("skill ", style=f"dim {ZERO_GRAY}")
            state.append(",".join(self.skills), style=ZERO_LIGHT)
            state.append("  ", style=f"dim {ZERO_GRAY}")
        if self.session_id:
            state.append("session ", style=f"dim {ZERO_GRAY}")
            state.append(self.session_id, style=ZERO_LIGHT)
            state.append("  ", style=f"dim {ZERO_GRAY}")
        state.append(self.connection_status, style=ZERO_GREEN if self.connection_status == "connected" else ZERO_GRAY)
        self.console.print(state)

        cwd = ellipsize(str(Path.cwd()), max(24, TerminalSize.get_width() - 8))
        path = Text()
        path.append("path ", style=f"dim {ZERO_GRAY}")
        path.append(cwd, style=f"dim {ZERO_LIGHT}")
        self.console.print(path)
        self.console.print()

    def show_welcome(self):
        welcome = Text()
        welcome.append("type ", style=f"dim {ZERO_GRAY}")
        welcome.append("/help", style=ZERO_PURPLE_LIGHT)
        welcome.append(" for commands", style=f"dim {ZERO_GRAY}")
        self.console.print(welcome)
        self.console.print()

    def display_message(self, role: str, content: str, is_code: bool = False):
        self.history.append({"role": role, "content": content, "is_code": is_code})

        if role == "user":
            self._render_user_message(content)
        elif role == "assistant":
            self._render_assistant_message(content, is_code)
        elif role == "error":
            self._render_error(content)

    def _render_user_message(self, content: str):
        self.console.print()
        for idx, line in enumerate(content.splitlines() or [""]):
            prefix = "> " if idx == 0 else "  "
            text = Text(prefix + line, style=f"{ZERO_LIGHT} on {ZERO_USER_BG}")
            self.console.print(Padding(text, (0, 1, 0, 0)))

    def _render_assistant_message(self, content: str, is_code: bool = False):
        self.console.print()
        bullet = Text("• ", style=f"bold {ZERO_PURPLE}")
        if is_code:
            try:
                rendered = Syntax(content, "python", theme="monokai", line_numbers=False, word_wrap=True)
            except Exception:
                rendered = Text(content, style=ZERO_LIGHT)
        else:
            try:
                rendered = Markdown(content, code_theme="monokai")
            except Exception:
                rendered = Text(content, style=ZERO_LIGHT)

        self.console.print(bullet, end="")
        self.console.print(rendered)
        self.console.print()
        self._turn_count += 1

    def _render_error(self, message: str):
        self.console.print()
        self.console.print(Text(f"! {message}", style=f"bold {ZERO_RED}"))

    def render_tool_call(self, name: str, target: str = ""):
        suffix = f"({target})" if target else "()"
        self.console.print(Text(f"● {name}{suffix}", style=ZERO_PURPLE_LIGHT))

    def render_tool_done(self, files: int = 0, tokens: int = 0, seconds: float = 0.0):
        self.console.print(Text(f"  └ Done ({files} files · {tokens} tokens · {seconds:.1f}s)", style=f"dim {ZERO_GRAY}"))

    def create_streaming_display(self) -> StreamingDisplay:
        return StreamingDisplay(self.console, on_finish=self._record_assistant_turn)

    def _record_assistant_turn(self, content: str):
        self.history.append({"role": "assistant", "content": content, "is_code": False})
        self._turn_count += 1

    def show_thinking(self, message: str = "Coding") -> ThinkingAnimation:
        anim = ThinkingAnimation(self.console, message)
        anim.start()
        return anim

    def input_prompt(self) -> str:
        self._refresh_size()
        if HAS_PROMPT_TOOLKIT and self._prompt_session is not None:
            try:
                bottom = "/help  /provider  /model  /skill  /clear  /exit"
                return self._prompt_session.prompt(
                    HTML(f'<style color="{ZERO_PURPLE}">› </style>'),
                    bottom_toolbar=HTML(f'<style color="{ZERO_GRAY}">{bottom}</style>'),
                ).strip()
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return "/exit"

        try:
            self.console.print(f"[bold {ZERO_PURPLE}]› [/bold {ZERO_PURPLE}]", end="", highlight=False)
            return input().strip()
        except (KeyboardInterrupt, EOFError):
            return ""

    def show_skills(self, skills: list):
        self.console.print()
        self.console.print(Text("skills", style=f"bold {ZERO_PURPLE_LIGHT}"))
        if not skills:
            self.console.print(Text("  no skills found", style=f"dim {ZERO_GRAY}"))
            return
        for skill in skills:
            description = ellipsize(skill.description, max(24, TerminalSize.get_width() - len(skill.name) - 6))
            self.console.print(Text(f"  • {skill.name}  {description}", style=ZERO_LIGHT))

    def show_help(self):
        self.console.print()
        self.console.print(Text("commands", style=f"bold {ZERO_PURPLE_LIGHT}"))
        for command, description in self.commands:
            line = Text("  ")
            line.append(command.ljust(10), style=f"bold {ZERO_PURPLE}")
            line.append(description, style=ZERO_LIGHT)
            self.console.print(line)

    def show_error(self, message: str):
        self._render_error(message)

    def show_info(self, message: str):
        self.console.print(Text(f"  {message}", style=f"dim {ZERO_GRAY}"))

    def show_success(self, message: str):
        self.console.print(Text(f"✓ {message}", style=ZERO_GREEN))

    def show_warning(self, message: str):
        self.console.print(Text(f"! {message}", style=ZERO_YELLOW))

    def clear(self):
        self.history = []
        self._turn_count = 0
        self._start_time = time.time()
        self.header()
        self.show_welcome()

    def show_status(self):
        elapsed = int(time.time() - self._start_time)
        mins, secs = divmod(elapsed, 60)
        self.console.print()
        self.console.print(Text("status", style=f"bold {ZERO_PURPLE_LIGHT}"))
        self.console.print(Text(f"  provider  {self.provider_name}", style=ZERO_LIGHT))
        self.console.print(Text(f"  model     {self.model}", style=ZERO_LIGHT))
        self.console.print(Text(f"  mode      {self.mode}", style=ZERO_LIGHT))
        self.console.print(Text(f"  skills    {', '.join(self.skills) if self.skills else 'none'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  session   {self.session_id or 'none'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  turns     {self._turn_count}", style=ZERO_LIGHT))
        self.console.print(Text(f"  messages  {len(self.history)}", style=ZERO_LIGHT))
        self.console.print(Text(f"  uptime    {mins}:{secs:02d}", style=ZERO_LIGHT))

    def show_cost(self):
        self.show_status()

    def goodbye(self):
        self.console.print()
        self.console.print(Text("ZeroCoding session ended.", style=f"dim {ZERO_GRAY}"))
        self.console.print()
