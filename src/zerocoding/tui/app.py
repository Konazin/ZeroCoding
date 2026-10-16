"""
ZeroCoding TUI.

Interface principal em Rich + prompt_toolkit, com visual de transcript de
terminal: texto contínuo, pouco cromo e acento roxo discreto.
"""
from __future__ import annotations

import shutil
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
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
    GHOST_ASCII_FULL,
    GHOST_ASCII_WORK_FRAMES,
    GHOST_FULL,
    GHOST_SMALL,
    GHOST_SMALL_STATES,
    GHOST_TINY,
    GHOST_WORK_FRAMES,
    GRAY as ZERO_GRAY,
    GREEN as ZERO_GREEN,
    LIGHT as ZERO_LIGHT,
    PURPLE as ZERO_PURPLE,
    PURPLE_LIGHT as ZERO_PURPLE_LIGHT,
    RED as ZERO_RED,
    USER_BG as ZERO_USER_BG,
    WORK_PHRASES,
    YELLOW as ZERO_YELLOW,
)

from .history import ProjectPromptHistory

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.filters import to_filter
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Dimension
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
        return TerminalSize.get_width() < 72

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


class _ThinkingView:
    def __init__(self, animation: "ThinkingAnimation"):
        self.animation = animation

    def __rich_console__(self, console, options):
        elapsed = self.animation.elapsed()
        frame_index = int(elapsed * 4) % 2
        frames = GHOST_WORK_FRAMES if self.animation.unicode else GHOST_ASCII_WORK_FRAMES
        sparkle = ("✦" if frame_index == 0 else "✧") if self.animation.unicode else ("*" if frame_index == 0 else "+")
        line = Text()
        line.append(frames[frame_index] + "  ", style=f"bold {ZERO_PURPLE}")
        line.append(sparkle + " ", style=f"bold {ZERO_PURPLE_LIGHT}")
        message = ellipsize(self.animation.message, max(8, TerminalSize.get_width() - 20))
        line.append(message, style=f"italic {ZERO_LIGHT}")
        line.append(f"  {elapsed:.0f}s", style=f"dim {ZERO_GRAY}")
        yield line


class ThinkingAnimation:
    """Compact mascot and status animation while the agent works."""

    def __init__(self, console: Console, message: str | None = None):
        self.console = console
        self.message = message or random.choice(WORK_PHRASES)
        self.started_at = 0.0
        self.unicode = self._supports_unicode()
        self._live: Optional[Live] = None
        self._paused = False
        self._paused_at: float | None = None
        self._paused_total = 0.0

    @staticmethod
    def _supports_unicode() -> bool:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        try:
            "─◉✦".encode(encoding)
            return True
        except (LookupError, UnicodeEncodeError):
            return False

    def start(self):
        self.started_at = time.monotonic()
        self._paused_at = None
        self._paused_total = 0.0
        self._start_live()

    def _start_live(self):
        self._live = Live(
            _ThinkingView(self),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        )
        self._live.start()
        self._paused = False

    def set_message(self, message: str):
        self.message = message
        if self._live:
            self._live.update(_ThinkingView(self), refresh=True)

    def pause(self):
        if self._paused:
            return
        if self._live:
            self._live.stop()
            self._live = None
        self._paused_at = time.monotonic()
        self._paused = True

    def resume(self):
        if self._paused:
            if self._paused_at is not None:
                self._paused_total += time.monotonic() - self._paused_at
                self._paused_at = None
            self._start_live()

    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self._paused_at if self._paused_at is not None else time.monotonic()
        return max(0.0, end - self.started_at - self._paused_total)

    def stop(self) -> float:
        if self._live:
            self._live.stop()
            self._live = None
        elapsed = self.elapsed()
        self._paused = False
        self._paused_at = None
        return elapsed


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
        plan_mode: bool = False,
        ultrathink: bool = False,
        effort: str = "medium",
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
        self.plan_mode = plan_mode
        self.ultrathink = ultrathink
        self.effort = effort if effort in {"low", "medium", "high"} else "medium"
        self.max_output_tokens = 1024
        self.max_tool_rounds = 6
        self.native_effort_supported = False
        self.native_effort_status = "budget only (not declared by provider)"
        self._unicode = ThinkingAnimation._supports_unicode()
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

        @kb.add("enter", eager=True)
        def submit_prompt(event):
            event.current_buffer.validate_and_handle()

        @kb.add("c-j")
        def insert_newline(event):
            event.current_buffer.insert_text("\n")

        pt_style = PTStyle.from_dict(
            {
                "prompt": f"{ZERO_PURPLE} bold",
                "completion-menu.completion": f"bg:{ZERO_BG} {ZERO_LIGHT}",
                "completion-menu.completion.current": f"bg:{ZERO_USER_BG} {ZERO_LIGHT} bold",
                "completion-menu.meta.completion": f"bg:{ZERO_BG} {ZERO_GRAY}",
                "bottom-toolbar": "fg:default bg:default noreverse",
                "bottom-toolbar.text": "fg:default bg:default noreverse",
                "composer-border": f"{ZERO_GRAY}",
                "composer-bottom-border": "fg:default bg:default noreverse",
                "composer-status": "fg:default bg:default noreverse",
            }
        )

        self._prompt_session = PromptSession(
            history=ProjectPromptHistory(Path.cwd()),
            completer=SlashCommandCompleter(self.commands),
            complete_while_typing=True,
            style=pt_style,
            key_bindings=kb,
            multiline=True,
            prompt_continuation="  ",
            wrap_lines=True,
        )

        # Keep the composer compact and let its buffer scroll internally after six rows.
        app = self._prompt_session.app
        for window in app.layout.find_all_windows():
            if getattr(window.content, "buffer", None) is self._prompt_session.default_buffer:
                window.height = Dimension(min=1, max=6)
                window.dont_extend_height = to_filter(True)

    def header(self):
        """Clear the visible screen and draw the responsive welcome header."""
        self._refresh_size()
        self.console.clear()
        self.console.print()

        if not self._unicode:
            ghost = "(o o)" if self._is_small else "\n".join(GHOST_ASCII_FULL)
        else:
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
        path.append("workspace ", style=f"dim {ZERO_GRAY}")
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
        self.console.print(Text(f"{self.state_face('error')}  {message}", style=f"bold {ZERO_RED}"))

    def render_tool_call(self, name: str, target: str = ""):
        suffix = f"({target})" if target else "()"
        self.console.print(Text(f"● {name}{suffix}", style=ZERO_PURPLE_LIGHT))

    def render_tool_done(self, files: int = 0, tokens: int = 0, seconds: float = 0.0):
        self.console.print(Text(f"  └ Done ({files} files · {tokens} tokens · {seconds:.1f}s)", style=f"dim {ZERO_GRAY}"))

    def set_runtime_state(
        self,
        *,
        plan_mode: bool,
        ultrathink: bool,
        effort: str,
        max_output_tokens: int,
        max_tool_rounds: int,
        native_effort_supported: bool,
        native_effort_status: str = "",
    ) -> None:
        self.plan_mode = bool(plan_mode)
        self.ultrathink = bool(ultrathink)
        self.effort = effort if effort in {"low", "medium", "high"} else "medium"
        self.max_output_tokens = int(max_output_tokens)
        self.max_tool_rounds = int(max_tool_rounds)
        self.native_effort_supported = bool(native_effort_supported)
        self.native_effort_status = native_effort_status or (
            "supported by provider" if self.native_effort_supported
            else "budget only (not declared by provider)"
        )

    def handle_agent_event(self, event, animation: ThinkingAnimation | None = None) -> None:
        kind = getattr(event, "kind", "")
        name = getattr(event, "tool_name", "")
        target = ellipsize(getattr(event, "target", ""), max(8, TerminalSize.get_width() - 30))
        summary = getattr(event, "summary", "")
        duration = float(getattr(event, "duration_seconds", 0.0) or 0.0)
        if kind == "tool_started":
            label = {
                "read_file": "Read",
                "list_files": "Explore",
                "search_files": "Search",
                "write_file": "Write",
                "edit_file": "Edit",
                "run_command": "Command",
            }.get(name, name)
            self.console.print(Text(f"● {label} {target}".rstrip(), style=ZERO_PURPLE_LIGHT))
        elif kind == "tool_completed":
            self.console.print(Text(f"  └ {summary or 'Completed'} · {duration:.1f}s", style=f"dim {ZERO_GRAY}"))
        elif kind == "tool_denied":
            self.console.print(Text(f"  └ {summary or 'Denied · no action taken'}", style=f"dim {ZERO_YELLOW}"))
        elif kind == "tool_error":
            self.console.print(Text(f"  └ {summary or 'Tool error'}", style=f"dim {ZERO_RED}"))
        if animation is None:
            return
        if kind == "thinking":
            animation.set_message(random.choice(WORK_PHRASES))
            return
        if kind == "tool_started":
            action = {
                "read_file": "Reading",
                "list_files": "Exploring",
                "search_files": "Searching",
                "write_file": "Preparing a file change",
                "edit_file": "Preparing a file edit",
                "run_command": "Preparing a command",
            }.get(name, f"Using {name}")
            animation.set_message(f"{action} {target}".strip())
            return
        if kind == "approval_requested":
            animation.set_message("Waiting for approval")
            return
        if kind == "tool_completed":
            animation.set_message(summary or "Step complete")
            return
        if kind == "tool_denied":
            animation.set_message("Action denied · no action taken")
            return
        if kind == "tool_error":
            animation.set_message("Tool error · continuing carefully")

    def state_face(self, state: str) -> str:
        if self._unicode:
            return GHOST_SMALL_STATES.get(state, GHOST_SMALL_STATES["idle"])
        return {"idle": "(o o)", "approval": "(o ?)", "success": "(^ ^)", "error": "(x x)"}.get(state, "(o o)")

    def show_thinking(self, message: str | None = None) -> ThinkingAnimation:
        anim = ThinkingAnimation(self.console, message)
        anim.start()
        return anim

    def confirm_action(self, action: str, preview: str) -> bool:
        """Show the complete approval preview and accept explicit Y/N/Esc input."""
        self.show_warning(f"{action} requires approval")
        self.console.print(Text(preview))
        prompt = "Approve? [Y/N/Esc] "
        if HAS_PROMPT_TOOLKIT:
            bindings = KeyBindings()

            @bindings.add("y", eager=True)
            @bindings.add("Y", eager=True)
            def approve(event):
                event.app.exit(result=True)

            @bindings.add("n", eager=True)
            @bindings.add("N", eager=True)
            @bindings.add("escape", eager=True)
            def reject(event):
                event.app.exit(result=False)

            try:
                # Only the Y binding yields True; Enter or any typed text returns a string and must refuse.
                return PromptSession(key_bindings=bindings).prompt(prompt) is True
            except (EOFError, KeyboardInterrupt):
                return False
        try:
            return input(prompt).strip().lower() in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False

    def _composer_rule(self) -> str:
        return ("─" if self._unicode else "-") * max(1, self._refresh_size())

    def _status_line_text(self) -> str:
        width = max(1, TerminalSize.get_width())
        value = ellipsize(f"Effort: {self.effort.title()}", width)
        return " " * max(0, width - len(value)) + value

    def _prompt_message(self):
        return [
            ("class:composer-border", self._composer_rule()),
            ("", "\n"),
            ("class:prompt", "› "),
        ]

    def _bottom_toolbar(self):
        return [
            ("class:composer-bottom-border", self._composer_rule()),
            ("", "\n"),
            ("class:composer-status", self._status_line_text()),
        ]

    def input_prompt(self) -> str:
        self._refresh_size()
        if HAS_PROMPT_TOOLKIT and self._prompt_session is not None:
            try:
                return self._prompt_session.prompt(
                    self._prompt_message,
                    bottom_toolbar=self._bottom_toolbar,
                    prompt_continuation="  ",
                    multiline=True,
                ).strip()
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return "/exit"

        try:
            self.console.print(Text(self._composer_rule(), style=ZERO_GRAY))
            self.console.print(Text("› ", style=f"bold {ZERO_PURPLE}"), end="")
            value = input().strip()
            self.console.print(Text(self._composer_rule()))
            self.console.print(Text(self._status_line_text()))
            return value
        except (KeyboardInterrupt, EOFError):
            return ""

    def show_skills(self, skills: list):
        self.console.print()
        self.console.print(Text("skills", style=f"bold {ZERO_PURPLE_LIGHT}"))
        if not skills:
            self.console.print(Text("  No skills found.", style=f"dim {ZERO_GRAY}"))
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
        self.console.print(Text(f"{self.state_face('success')}  {message}", style=ZERO_GREEN))

    def show_warning(self, message: str):
        self.console.print(Text(f"{self.state_face('approval')}  {message}", style=ZERO_YELLOW))

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
        self.console.print(Text(f"  Provider                 {self.provider_name}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Model                    {self.model}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Mode profile             {self.mode}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Plan                     {'On' if self.plan_mode else 'Off'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Ultrathink               {'On' if self.ultrathink else 'Off'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Effort (budgets)         {self.effort.title()}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Effective output budget  {self.max_output_tokens} tokens", style=ZERO_LIGHT))
        self.console.print(Text(f"  Tool round limit         {self.max_tool_rounds}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Provider native effort   {self.native_effort_status}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Skills                   {', '.join(self.skills) if self.skills else 'none'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Session                  {self.session_id or 'none'}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Turns / messages         {self._turn_count} / {len(self.history)}", style=ZERO_LIGHT))
        self.console.print(Text(f"  Uptime                   {mins}:{secs:02d}", style=ZERO_LIGHT))

    def show_cost(self):
        self.show_status()

    def goodbye(self):
        self.console.print()
        self.console.print(Text("ZeroCoding session ended.", style=f"dim {ZERO_GRAY}"))
        self.console.print()
