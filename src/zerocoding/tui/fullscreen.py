"""Full-screen TUI: fixed window, scrollable transcript, input box that stays visible while the agent works.

The classic scrollback UI (app.py) prints into the terminal; here everything is drawn by one
prompt_toolkit Application. Existing display code is reused unchanged: `self.console` is a
`TranscriptConsole` that records Rich prints and re-renders them at the current width, so Markdown,
tool lines and diffs look the same and wrap correctly after a resize.

Threads: the Application runs on the main thread; the interactive loop from cli.py runs in a worker
thread. The worker blocks in `input_prompt`, `run_screen` and `confirm_action` on queues that the key
bindings feed, so the UI never freezes while the agent is busy.
"""
from __future__ import annotations

import queue
import random
import threading
import time
from io import StringIO
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import CompletionsMenu, ConditionalContainer, Dimension, Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.text import Text

from .app import (
    PET_ASCII, PET_IDLE, PET_WORK, SlashCommandCompleter, TerminalSize, ZerocodingTUI, _ThinkingView, format_tokens,
)
from .diffview import DiffView, looks_like_diff, parse_diff, summarize
from .history import ProjectPromptHistory
from .mascot import ANIMATIONS, render, render_ascii
from .menus import CANCELLED, Done
from .theme import (
    BG as ZERO_BG, GRAY as ZERO_GRAY, LIGHT as ZERO_LIGHT, PURPLE as ZERO_PURPLE, RED as ZERO_RED,
    USER_BG as ZERO_USER_BG, YELLOW as ZERO_YELLOW,
)

Fragments = list  # list of (style, text[, handler]) tuples


def ansi_lines(text: str) -> list[Fragments]:
    """Split ANSI-colored text into prompt_toolkit fragment lines."""
    return list(split_lines(to_formatted_text(ANSI(text))))


class TranscriptConsole:
    """Rich-compatible sink: records print calls and renders them to ANSI lines at any width."""

    def __init__(self, on_change):
        self._calls: list[tuple[tuple, str]] = []
        self._on_change = on_change
        self._lock = threading.RLock()
        self._cache: dict[int, tuple[int, list[Fragments]]] = {}

    def print(self, *objects, end: str = "\n", **_kwargs) -> None:
        with self._lock:
            self._calls.append((objects, end))
        self._on_change()

    def clear(self, *_args, **_kwargs) -> None:
        with self._lock:
            self._calls.clear()
            self._cache.clear()
        self._on_change()

    def render_lines(self, width: int) -> list[Fragments]:
        with self._lock:
            count = len(self._calls)
            cached = self._cache.get(width)
            if cached and cached[0] == count:
                return cached[1]
            buffer = StringIO()
            console = Console(file=buffer, force_terminal=True, color_system="truecolor", width=width, highlight=False)
            for objects, end in self._calls:
                console.print(*objects, end=end)
            lines = ansi_lines(buffer.getvalue())
            if lines and not any(fragment[1] for fragment in lines[-1]):
                lines.pop()  # trailing newline, not a real empty row
            self._cache = {width: (count, lines)}
            return lines


class FullscreenAnimation:
    """Same contract as ThinkingAnimation, drawn on the activity line instead of a Live region."""

    unicode = True
    footer = None

    def __init__(self, tui: "FullscreenTUI", message: str, tokens=None):
        self.tui, self.message, self.tokens = tui, message, tokens
        self.started_at = 0.0
        self._paused_at: float | None = None
        self._paused_total = 0.0

    def start(self) -> None:
        self.started_at = time.monotonic()
        self.tui._activity = self
        self.tui._invalidate()

    def set_message(self, message: str) -> None:
        self.message = message

    def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = time.monotonic()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None

    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self._paused_at if self._paused_at is not None else time.monotonic()
        return max(0.0, end - self.started_at - self._paused_total)

    def stop(self) -> float:
        elapsed = self.elapsed()
        if self.tui._activity is self:
            self.tui._activity = None
        self.tui._invalidate()
        return elapsed


class ApprovalScreen:
    """Approval panel: styled diff or command, explicit Y to approve, N/Esc/Enter to refuse."""

    def __init__(self, action: str, preview: str, max_lines: int = 24):
        self.action, self.preview, self.max_lines = action, preview, max_lines

    def key(self, name: str) -> Done | None:
        if name in {"char:y", "char:Y"}:
            return Done(True, "y")
        if name in {"char:n", "char:N", "escape", "enter"}:
            return Done(False, "n")
        return None  # any other key or typed text neither approves nor refuses

    def fragments(self, width: int) -> Fragments:
        out: Fragments = [("fg:#FDE68A bold", f"{self.action} requires approval\n")]
        if looks_like_diff(self.preview):
            path, lines = parse_diff(self.preview)
            out.append(("bold", f"{path}\n" if path else "\n"))
            out.append(("fg:#9CA3AF", f"{summarize(lines)}\n"))
            buffer = StringIO()
            Console(file=buffer, force_terminal=True, color_system="truecolor", width=width, highlight=False).print(
                DiffView(self.preview, indent=0, max_lines=self.max_lines))
            for line in ansi_lines(buffer.getvalue())[: self.max_lines + 1]:
                out.extend(line)
                out.append(("", "\n"))
        else:
            out.append(("fg:#C4B5FD", "$ " + self.preview.strip() + "\n"))
        out.append(("", "\n"))
        out.append(("fg:#9CA3AF", "Approve? "))
        out.append(("bold fg:#86EFAC", "Y"))
        out.append(("fg:#9CA3AF", " yes · N / Enter / Esc no\n"))
        return out


class _TranscriptControl(FormattedTextControl):
    def __init__(self, tui: "FullscreenTUI"):
        super().__init__(tui._transcript_fragments, focusable=False, show_cursor=False)
        self.tui = tui

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self.tui.scroll(3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self.tui.scroll(-3)
            return None
        return super().mouse_handler(mouse_event)


class FullscreenTUI(ZerocodingTUI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.console = TranscriptConsole(self._invalidate)
        self.mouse_enabled = True
        self._inbox: queue.Queue[str] = queue.Queue()
        self._modal: tuple | None = None
        self._activity: FullscreenAnimation | None = None
        self._cancel = None
        self._scroll = 0
        self._last_total = 0
        self._pose = "idle"
        self._show_art = False
        self._stream_text = ""
        self._flash = ("", 0.0)
        self._farewell = ""
        self._playing = False
        self._app: Application | None = None
        self._build_app()

    # -- plumbing -----------------------------------------------------------------------------

    def _setup_prompt_toolkit(self):  # the classic PromptSession is not used here
        self._prompt_session = None

    def _invalidate(self) -> None:
        if self._app is not None:
            self._app.invalidate()

    def _size(self) -> tuple[int, int]:
        try:
            size = self._app.output.get_size() if self._app else None
            return (size.columns, size.rows) if size else (TerminalSize.get_width(), 24)
        except Exception:
            return TerminalSize.get_width(), 24

    @property
    def busy(self) -> bool:
        return self._activity is not None

    def set_cancel(self, token) -> None:
        self._cancel = token

    # -- layout -------------------------------------------------------------------------------

    def _build_app(self) -> None:
        self._buffer = Buffer(
            multiline=True, history=ProjectPromptHistory(Path.cwd()),
            completer=SlashCommandCompleter(self.commands), complete_while_typing=True,
        )
        modal_active = Condition(lambda: self._modal is not None)
        self._transcript_window = Window(_TranscriptControl(self), wrap_lines=False)
        modal_window = Window(
            FormattedTextControl(self._modal_fragments, show_cursor=False),
            height=lambda: Dimension(max=max(6, self._size()[1] - 6)), dont_extend_height=True,
        )
        input_window = Window(
            BufferControl(self._buffer), height=Dimension(min=1, max=6), wrap_lines=True, dont_extend_height=True,
            get_line_prefix=lambda lineno, wrap: [("class:prompt", "› ")] if lineno == 0 and wrap == 0 else "  ",
        )

        def rule():
            return [("class:rule", ("─" if self._unicode else "-") * self._size()[0])]

        body = HSplit([
            self._transcript_window,
            ConditionalContainer(modal_window, filter=modal_active),
            Window(FormattedTextControl(self._activity_fragments), height=1),
            Window(FormattedTextControl(rule), height=1),
            input_window,
            Window(FormattedTextControl(rule), height=1),
            Window(FormattedTextControl(self._status_fragments), height=1),
        ])
        root = FloatContainer(body, floats=[
            Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=8, scroll_offset=1)),
        ])
        style = Style.from_dict({
            "prompt": f"{ZERO_PURPLE} bold", "rule": ZERO_GRAY, "pet": ZERO_PURPLE, "flash": ZERO_YELLOW,
            "completion-menu.completion": f"bg:{ZERO_BG} {ZERO_LIGHT}",
            "completion-menu.completion.current": f"bg:{ZERO_USER_BG} {ZERO_LIGHT} bold",
            "completion-menu.meta.completion": f"bg:{ZERO_BG} {ZERO_GRAY}",
        })
        self._app = Application(
            layout=Layout(root, focused_element=input_window), key_bindings=self._key_bindings(modal_active),
            style=style, full_screen=True, mouse_support=Condition(lambda: self.mouse_enabled), refresh_interval=0.12,
        )

    def _key_bindings(self, modal_active) -> KeyBindings:
        kb = KeyBindings()
        idle = ~modal_active

        @kb.add("enter", filter=idle, eager=True)
        def _submit(event):
            self.submit_input()

        @kb.add("c-j", filter=idle)
        def _newline(event):
            event.current_buffer.insert_text("\n")

        @kb.add("c-c", filter=idle)
        def _interrupt(event):
            if self.busy and self._cancel is not None:
                self._cancel.cancel()
            else:
                self._buffer.reset()

        @kb.add("c-d", filter=idle)
        def _eof(event):
            if not self._buffer.text:
                self._inbox.put("/exit")

        @kb.add("pageup", filter=idle)
        def _page_up(event):
            self.scroll(self._page())

        @kb.add("pagedown", filter=idle)
        def _page_down(event):
            self.scroll(-self._page())

        for key, name in (("up", "up"), ("down", "down"), ("left", "left"), ("right", "right"), ("enter", "enter"),
                          ("tab", "tab"), ("backspace", "backspace"), ("c-h", "backspace"), ("c-u", "ctrl-u"),
                          ("c-c", "escape")):
            kb.add(key, filter=modal_active, eager=True)(lambda event, name=name: self._feed_modal(name))
        kb.add("escape", filter=modal_active, eager=True)(lambda event: self._feed_modal("escape"))

        @kb.add(Keys.Any, filter=modal_active, eager=True)
        def _modal_char(event):
            if event.data and event.data.isprintable():
                self._feed_modal("char:" + event.data)

        return kb

    def submit_input(self) -> bool:
        """Send the typed text to the worker. While a task runs the draft stays and nothing is sent."""
        text = self._buffer.text.strip()
        if self.busy:
            self._flash = ("Still working; you can type, but sending waits until this task ends.", time.monotonic() + 3)
            return False
        if not text:
            return False
        self._buffer.reset(append_to_history=True)
        self._inbox.put(text)
        return True

    def _feed_modal(self, name: str) -> None:
        modal = self._modal
        if modal is None:
            return
        done = modal[0].key(name)
        if done is not None:
            modal[1].put(done)
        self._invalidate()

    # -- scrolling and painting ----------------------------------------------------------------

    def _page(self) -> int:
        return max(3, self._size()[1] - 8)

    def scroll(self, delta: int) -> None:
        self._scroll = max(0, self._scroll + delta)
        self._invalidate()

    def _header_lines(self, width: int) -> list[Fragments]:
        if not self._show_art or self._is_tiny:
            return []
        art = (render if self._unicode else render_ascii)(self._pose)
        return [[("fg:" + ZERO_PURPLE + " bold", row, self._on_mascot_mouse)] for row in ["", *art]]

    def _all_lines(self, width: int) -> list[Fragments]:
        lines = self._header_lines(width) + self.console.render_lines(width)
        if self._stream_text:
            buffer = StringIO()
            Console(file=buffer, force_terminal=True, color_system="truecolor", width=width, highlight=False).print(
                Text("• " + self._stream_text, style=ZERO_LIGHT))
            lines = lines + ansi_lines(buffer.getvalue())
        return lines

    def _transcript_fragments(self) -> Fragments:
        width, rows = self._size()
        info = self._transcript_window.render_info
        height = info.window_height if info is not None else max(3, rows - 6)
        lines = self._all_lines(width)
        total = len(lines)
        if self._scroll > 0 and total > self._last_total:
            self._scroll += total - self._last_total  # keep the view still while new output arrives
        self._last_total = total
        self._scroll = min(self._scroll, max(0, total - height))
        end = total - self._scroll
        out: Fragments = []
        for index, line in enumerate(lines[max(0, end - height):end]):
            if index:
                out.append(("", "\n"))
            out.extend(line)
        return out

    def _modal_fragments(self) -> Fragments:
        modal = self._modal
        return modal[0].fragments(self._size()[0]) if modal else []

    def _activity_fragments(self) -> Fragments:
        width = self._size()[0]
        anim = self._activity
        if anim is not None:
            buffer = StringIO()
            Console(file=buffer, force_terminal=True, color_system="truecolor", width=width, highlight=False).print(
                _ThinkingView(anim), end="")
            lines = ansi_lines(buffer.getvalue())
            return lines[0] if lines else []
        if self._scroll > 0:
            return [("fg:" + ZERO_GRAY, f"↓ {self._scroll} lines below · PageDown or scroll to follow")]
        return []

    def _status_fragments(self) -> Fragments:
        width = self._size()[0]
        if self._flash[0] and time.monotonic() < self._flash[1]:
            return [("class:flash", self._flash[0][:width])]
        pets = (PET_WORK if self._unicode else PET_ASCII) if self.busy else (PET_IDLE if self._unicode else PET_ASCII[0],)
        pet = pets[int(time.monotonic() * 4) % len(pets)] if self.busy else pets[0]
        before, glyph, after = self._status_parts(pet)
        if not glyph:
            return [("", before)]
        return [("", before), ("class:pet", glyph, self._on_pet_mouse), ("", after)]

    # -- mascot ------------------------------------------------------------------------------

    def _on_mascot_mouse(self, mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            self._play_in_thread()
        return None

    def _on_pet_mouse(self, mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            self._play_in_thread()
        return None

    def _play_in_thread(self) -> None:
        if not self._playing:
            threading.Thread(target=self.click_buddy, daemon=True).start()

    def _print_header_art(self) -> None:
        self._show_art = True

    def play_buddy(self, name: str | None = None) -> str:
        """Animate the mascot at the top of the transcript in place."""
        choice = name if name in ANIMATIONS else random.choice(sorted(ANIMATIONS))
        poses, delay = ANIMATIONS[choice]
        self._playing = True
        try:
            for pose in poses:
                self._pose = pose
                self._invalidate()
                time.sleep(delay)
        finally:
            self._pose = "idle"
            self._playing = False
            self._invalidate()
        return choice

    # -- worker-facing API -------------------------------------------------------------------

    def input_prompt(self) -> str:
        return self._inbox.get()

    def show_thinking(self, message: str | None = None, tokens=None) -> FullscreenAnimation:
        from .theme import WORK_PHRASES
        anim = FullscreenAnimation(self, message or random.choice(WORK_PHRASES), tokens)
        anim.start()
        return anim

    def run_screen(self, screen) -> Done:
        results: queue.Queue = queue.Queue()
        self._modal = (screen, results)
        self._invalidate()
        try:
            return results.get()
        finally:
            self._modal = None
            self._invalidate()

    def confirm_action(self, action: str, preview: str) -> bool:
        done = self.run_screen(ApprovalScreen(action, preview, max_lines=max(6, self._size()[1] - 14)))
        approved = done.value is True
        if looks_like_diff(preview):
            path, lines = parse_diff(preview)
            if approved:
                self.console.print(Text(f"  ⎿  {summarize(lines)}", style=f"dim {ZERO_GRAY}"))
                self.console.print(DiffView(preview))
            else:
                self.console.print(Text(f"  ⎿  Rejected {action.lower()}{' · ' + path if path else ''}", style=f"dim {ZERO_YELLOW}"))
        elif not approved:
            self.console.print(Text(f"  ⎿  Rejected {action.lower()}", style=f"dim {ZERO_YELLOW}"))
        return approved

    def _handle_response_event(self, kind, event, animation) -> None:
        """Streamed text lives in a dedicated tail block; the activity line keeps running meanwhile."""
        if kind == "response_delta":
            self._stream_text += getattr(event, "summary", "")
            self._invalidate()
            return
        text, self._stream_text = self._stream_text, ""
        if kind == "response_end" and getattr(event, "summary", "") == "before_tools" and text.strip():
            self.console.print(Text("• " + text.strip(), style=ZERO_LIGHT))
        self._invalidate()

    def goodbye(self) -> None:
        self._farewell = "ZeroCoding session ended."

    def header(self):
        self._show_art = False
        self._scroll = 0
        super().header()

    # -- entry point -------------------------------------------------------------------------

    def run(self, loop_fn) -> int:
        """Run the interactive loop in a worker thread and the UI on this one."""
        outcome: dict = {}

        def worker():
            try:
                outcome["code"] = loop_fn()
            except BaseException as exc:  # re-raised on the main thread after the UI closes
                outcome["exc"] = exc
            finally:
                loop = getattr(self._app, "loop", None)
                if loop is not None:
                    try:
                        loop.call_soon_threadsafe(self._app.exit)
                    except Exception:
                        pass

        thread = threading.Thread(target=worker, daemon=True)
        self._app.run(pre_run=thread.start)
        self._inbox.put("/exit")  # unblock the worker if the UI closed first
        thread.join(timeout=2)
        if self._farewell:
            Console(highlight=False).print(Text(self._farewell, style=f"dim {ZERO_GRAY}"))
        if "exc" in outcome:
            raise outcome["exc"]
        return outcome.get("code", 0)
