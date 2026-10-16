"""Persistent full-screen prototype using Textual."""
from __future__ import annotations

import asyncio
import locale
import os
import time
from pathlib import Path

from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog, Static, TextArea

from zerocoding import __version__

from .demo_support import (
    DEMO_COMMANDS,
    GRAY,
    GREEN,
    LIGHT,
    PURPLE,
    PURPLE_LIGHT,
    RED,
    USER_BG,
    YELLOW,
    DemoConversation,
    DemoMessage,
    ProjectPromptHistory,
    ghost_frame,
    random_work_phrase,
    sparkle,
    workspace_branch,
)


class DemoComposer(TextArea):
    """Multiline composer with Enter submit and Ctrl+J newline."""

    def _on_key(self, event: events.Key) -> None:
        app = self.app
        if app.conversation.pending_approval:
            if event.key in {"up", "down"}:
                app.conversation.approval_index = 0 if event.key == "up" else 1
                app.refresh_approval_choice()
            elif event.key == "enter":
                app.resolve_approval(app.conversation.approval_index == 0)
            elif event.key.lower() == "y":
                app.resolve_approval(True)
            elif event.key.lower() in {"n", "escape"}:
                app.resolve_approval(False)
            event.stop()
            event.prevent_default()
            return

        aliases = set(getattr(event, "aliases", ()))
        if event.key in {"ctrl+j", "ctrl+enter"} or aliases.intersection({"ctrl+j", "ctrl+enter"}):
            self.insert("\n")
            event.stop()
            event.prevent_default()
            return
        if event.key == "enter":
            app.submit_prompt()
            event.stop()
            event.prevent_default()
            return

        if app.suggestions:
            if event.key == "up":
                app.move_suggestion(-1)
                event.stop()
                event.prevent_default()
                return
            if event.key == "down":
                app.move_suggestion(1)
                event.stop()
                event.prevent_default()
                return
            if event.key == "tab":
                app.accept_suggestion()
                event.stop()
                event.prevent_default()
                return

        row, _column = self.cursor_location
        last_row = len(self.document.lines) - 1
        if event.key == "up" and row == 0:
            app.move_history(-1)
            event.stop()
            event.prevent_default()
            return
        if event.key == "down" and row == last_row:
            app.move_history(1)
            event.stop()
            event.prevent_default()
            return

        super()._on_key(event)


class RichTextualDemo(App):
    TITLE = "ZeroCoding"
    SUB_TITLE = "Local UI prototype · Textual"

    CSS = f"""
    Screen {{ background: #09090B; color: {LIGHT}; }}
    #root {{ height: 100%; padding: 0 1; }}
    #header {{ height: auto; padding: 1 0; border-bottom: solid {PURPLE}; }}
    #transcript {{ height: 1fr; border: none; padding: 1 0; background: #09090B; }}
    #status {{ height: 1; color: {PURPLE_LIGHT}; }}
    #approval-choice {{ height: 1; color: {YELLOW}; }}
    #suggestions {{ height: auto; color: {GRAY}; }}
    #composer-label {{ height: 1; color: {PURPLE}; }}
    #composer {{ height: 4; border: tall {PURPLE}; background: #111014; padding: 0 1; }}
    #footer {{ height: auto; padding-top: 1; border-top: solid {PURPLE}; color: {GRAY}; }}
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Exit"),
    ]

    def __init__(self):
        super().__init__()
        self.conversation = DemoConversation()
        self.prompt_history = ProjectPromptHistory()
        self._history_entries = list(self.prompt_history.load_history_strings())
        self._history_position = -1
        self._history_draft = ""
        self.suggestions: list[tuple[str, str]] = []
        self.suggestion_index = 0
        self.frame = 0
        self.is_working = False
        self.current_phrase = ""
        self.work_started = 0.0
        self.workspace_path = Path.cwd()
        self.project = self.workspace_path.name or str(self.workspace_path)
        self.branch = workspace_branch()
        self.workspace_label = f"{self.project} ({self.branch})" if self.branch else self.project

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield Static(id="header")
            yield RichLog(id="transcript", wrap=True, highlight=False, markup=False)
            yield Static(id="status")
            yield Static(id="approval-choice")
            yield Static(id="suggestions")
            yield Static("›", id="composer-label")
            yield DemoComposer(id="composer", soft_wrap=True)
            yield Static(id="footer")

    def on_mount(self) -> None:
        self.set_interval(0.25, self.tick)
        self.refresh_header()
        self.refresh_footer()
        self.query_one("#transcript", RichLog).write(
            Text("Local UI prototype · fixed sample data · no model or tools are called", style=f"dim {GRAY}")
        )
        self.query_one(DemoComposer).focus()
        self.refresh_status()

    def on_resize(self, _event) -> None:
        self.refresh_header()
        self.refresh_footer()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "composer":
            self.update_suggestions(event.text_area.text)

    def refresh_header(self) -> None:
        if not self.is_mounted:
            return
        width = self.size.width or 80
        compact = width < 80 or bool(self.conversation.messages)
        unicode = self.unicode_available()
        art = ghost_frame(self.frame, compact=compact, unicode=unicode)
        color = {"approval": YELLOW, "success": GREEN, "error": RED}.get(self.conversation.status_kind, PURPLE)
        workspace = self.workspace_label

        header = Text()
        if width >= 80 and not compact:
            details = (
                (f"ZeroCoding v{__version__}", f"bold {LIGHT}"),
                ("Ollama · deepseek-coder-v2", PURPLE_LIGHT),
                (workspace, f"dim {GRAY}"),
                ("", ""),
            )
            art_width = max(len(line) for line in art)
            for index, line in enumerate(art):
                header.append(line.ljust(art_width), style=f"bold {color}")
                header.append("  ")
                label, style = details[index]
                if label:
                    header.append(label, style=style)
                if index < len(art) - 1:
                    header.append("\n")
        else:
            header.append(art[0], style=f"bold {color}")
            header.append(f"  ZeroCoding v{__version__}\n", style=f"bold {LIGHT}")
            header.append(art[1], style=f"bold {color}")
            header.append("  Ollama · deepseek-coder-v2\n", style=PURPLE_LIGHT)
            header.append(workspace, style=f"dim {GRAY}")
        self.query_one("#header", Static).update(header)

    def refresh_footer(self) -> None:
        if not self.is_mounted:
            return
        where = self.workspace_label
        width = self.size.width or 80
        footer = Text(f"{where} · mode: code", style=f"dim {GRAY}")
        if width >= 80:
            footer.append(f"\n{self.conversation.hint}", style=f"dim {GRAY}")
            footer.append("\n↑/↓ history · Tab complete · Ctrl+J newline · Enter send", style=f"dim {GRAY}")
        elif width >= 60:
            footer.append("\nArrows · Tab complete · Ctrl+J new line · Enter send", style=f"dim {GRAY}")
        else:
            footer.append("\nEnter sends · Ctrl+J adds a line", style=f"dim {GRAY}")
        self.query_one("#footer", Static).update(footer)

    @staticmethod
    def unicode_available() -> bool:
        encoding = (locale.getpreferredencoding(False) or "").lower()
        return "ascii" not in encoding and "dumb" not in os.environ.get("TERM", "").lower()

    def refresh_status(self) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#status", Static)
        if self.is_working:
            elapsed = time.monotonic() - self.work_started
            icon = sparkle(self.frame, unicode=self.unicode_available())
            status.update(Text(f"{icon} {self.current_phrase}  {elapsed:.0f}s", style=PURPLE_LIGHT))
        elif self.conversation.pending_approval:
            status.update(Text("Approval required · review the proposed change", style=YELLOW))
        elif self.conversation.status_kind == "error":
            status.update(Text(self.conversation.status, style=RED))
        else:
            status.update(Text(self.conversation.last_duration or "Ready", style=f"dim {GRAY}"))
        self.refresh_header()

    def refresh_approval_choice(self) -> None:
        if not self.is_mounted or not self.conversation.pending_approval:
            return
        first = "[ Accept ]" if self.conversation.approval_index == 0 else "  Accept  "
        second = "[ Reject ]" if self.conversation.approval_index == 1 else "  Reject  "
        text = Text(f"{first}     {second}     ↑/↓ · Enter · Y/N · Esc", style=YELLOW)
        self.query_one("#approval-choice", Static).update(text)

    def update_suggestions(self, text: str) -> None:
        if text.startswith("/") and "\n" not in text and " " not in text.strip():
            self.suggestions = [(command, description) for command, description in DEMO_COMMANDS if command.startswith(text)]
        else:
            self.suggestions = []
        self.suggestion_index = min(self.suggestion_index, max(0, len(self.suggestions) - 1))
        self.refresh_suggestions()

    def refresh_suggestions(self) -> None:
        if not self.is_mounted:
            return
        widget = self.query_one("#suggestions", Static)
        width = self.size.width or 80
        if not self.suggestions or width < 60:
            widget.update("")
            return
        text = Text()
        for index, (command, description) in enumerate(self.suggestions[:5]):
            if index:
                text.append("   ")
            style = f"bold {PURPLE_LIGHT}" if index == self.suggestion_index else f"dim {GRAY}"
            text.append(command, style=style)
            if width >= 80:
                text.append(f" {description}", style=f"dim {GRAY}")
        widget.update(text)

    def move_suggestion(self, amount: int) -> None:
        if self.suggestions:
            self.suggestion_index = (self.suggestion_index + amount) % len(self.suggestions)
            self.refresh_suggestions()

    def accept_suggestion(self) -> None:
        if not self.suggestions:
            return
        composer = self.query_one(DemoComposer)
        command = self.suggestions[self.suggestion_index][0]
        composer.load_text(command + " ")
        composer.cursor_location = (0, len(command) + 1)
        self.update_suggestions(composer.text)

    def move_history(self, amount: int) -> None:
        composer = self.query_one(DemoComposer)
        if amount < 0:
            if not self._history_entries:
                return
            if self._history_position < 0:
                self._history_draft = composer.text
                self._history_position = 0
            elif self._history_position < len(self._history_entries) - 1:
                self._history_position += 1
            composer.load_text(self._history_entries[self._history_position])
            composer.cursor_location = composer.document.end
        elif self._history_position >= 0:
            if self._history_position == 0:
                self._history_position = -1
                composer.load_text(self._history_draft)
            else:
                self._history_position -= 1
                composer.load_text(self._history_entries[self._history_position])
            composer.cursor_location = composer.document.end
        self.update_suggestions(composer.text)

    def tick(self) -> None:
        if self.is_working:
            self.frame += 1
            self.refresh_status()

    async def animate_stage(self, phrase: str, seconds: float) -> None:
        self.current_phrase = phrase
        self.is_working = True
        self.work_started = time.monotonic()
        self.conversation.status = phrase
        self.conversation.status_kind = "working"
        self.refresh_status()
        await asyncio.sleep(seconds)
        self.is_working = False

    @work(exclusive=True)
    async def submit_prompt(self) -> None:
        composer = self.query_one(DemoComposer)
        prompt = composer.text.strip()
        if not prompt:
            return
        composer.load_text("")
        self._history_position = -1
        self.prompt_history.store_string(prompt)
        self._history_entries.insert(0, prompt)
        del self._history_entries[200:]
        self.update_suggestions("")

        previous_count = len(self.conversation.messages)
        result = self.conversation.submit(prompt)
        new_messages = self.conversation.messages[previous_count:]
        log = self.query_one("#transcript", RichLog)
        if result == "quit":
            self.exit()
            return
        if result == "clear":
            log.clear()
            self.refresh_header()
            self.refresh_status()
            return
        if result == "help":
            for command, description in DEMO_COMMANDS:
                line = Text()
                line.append(command.ljust(18), style=f"bold {PURPLE}")
                line.append(description, style=LIGHT)
                log.write(line)
            return
        if result == "approval":
            for message in new_messages:
                log.write(self.render_message(message))
            self.refresh_approval_choice()
            self.refresh_status()
            return
        if result == "error":
            for message in new_messages:
                log.write(self.render_message(message))
            self.refresh_status()
            return

        user_message = self.conversation.messages[-1]
        log.write(self.render_message(user_message))
        turn_started = time.monotonic()
        composer.disabled = True
        try:
            if result == "tool":
                await self.animate_stage(random_work_phrase(), 0.8)
                events = self.conversation.tool_scenario_events()
                for event in events[:2]:
                    self.conversation.set_tool_activity(event.text, event.target)
                    await self.animate_stage(self.conversation.status, 0.45)
                    log.write(self.render_message(event))
                    await self.animate_stage(random_work_phrase(), 0.65)
                response = events[-1]
            else:
                await self.animate_stage(random_work_phrase(), 1.2)
                response = DemoMessage("assistant", self.conversation.response_for(user_message.text))
            log.write(self.render_message(response))
            self.conversation.finish(time.monotonic() - turn_started)
        except Exception as exc:
            self.is_working = False
            self.conversation.status = "Prototype error"
            self.conversation.status_kind = "error"
            log.write(Text(f"! Prototype error: {exc}", style=f"bold {RED}"))
        finally:
            self.is_working = False
            composer.disabled = False
            self.refresh_status()

    def resolve_approval(self, accepted: bool) -> None:
        self.conversation.resolve_approval(accepted)
        self.query_one("#approval-choice", Static).update("")
        self.query_one("#transcript", RichLog).write(self.render_message(self.conversation.messages[-1]))
        self.refresh_status()

    @staticmethod
    def render_message(message: DemoMessage):
        if message.kind == "user":
            return Panel(Text(message.text, style=LIGHT), title="You", border_style=PURPLE, style=USER_BG, box=box.ROUNDED, padding=(0, 1))
        if message.kind == "assistant":
            return Markdown(message.text, code_theme="monokai")
        if message.kind == "tool":
            return Text(f"  {message.text} · {message.target} · {message.result}", style=f"dim {GRAY}")
        if message.kind == "approval":
            return Panel(
                Syntax(message.result, "diff", theme="monokai", word_wrap=True),
                title=message.text,
                subtitle="Accept selected · arrows change selection · Enter confirms · Y/N · Esc",
                border_style=YELLOW,
                box=box.ROUNDED,
            )
        if message.kind == "error":
            return Text(f"! {message.text}", style=f"bold {RED}")
        return Text(message.text, style=f"dim {GRAY}")


def run() -> int:
    RichTextualDemo().run()
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(run())

