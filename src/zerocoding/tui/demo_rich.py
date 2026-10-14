"""Classic scrollback prototype using Rich and prompt_toolkit."""
from __future__ import annotations

import locale
import os
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

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


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        before = document.text_before_cursor
        if not before.startswith("/") or " " in before.strip():
            return
        for command, description in DEMO_COMMANDS:
            if command.startswith(before):
                yield Completion(command, start_position=-len(before), display_meta=description)


def _unicode_available() -> bool:
    encoding = (locale.getpreferredencoding(False) or "").lower()
    return "ascii" not in encoding and "dumb" not in os.environ.get("TERM", "").lower()


def _header(console: Console, frame: int = 0, state: str = "idle") -> Group:
    width = console.width
    compact = width < 60
    unicode = _unicode_available()
    art = "\n".join(ghost_frame(frame, compact=compact, unicode=unicode))
    color = {"approval": YELLOW, "success": GREEN, "error": RED}.get(state, PURPLE)
    title = Text(f"ZeroCoding v{__version__}", style=f"bold {LIGHT}")
    meta = Text("Ollama · deepseek-coder-v2", style=PURPLE_LIGHT)
    project = Path.cwd().name or str(Path.cwd())
    branch = workspace_branch()
    workspace = Text(f"{project} ({branch})" if branch else project, style=f"dim {GRAY}")

    grid = Table.grid(padding=(0, 2), expand=False)
    grid.add_column(no_wrap=True)
    grid.add_column()
    details = Group(title, meta)
    if width >= 80:
        details = Group(title, meta, workspace)
    grid.add_row(Text(art, style=f"bold {color}"), details)
    pieces = [grid]
    if width < 80:
        pieces.append(workspace)
    pieces.append(Text("─" * max(1, width), style=f"dim {PURPLE}"))
    return Group(*pieces)


def _footer(console: Console, hint: str) -> Group:
    width = console.width
    branch = workspace_branch()
    project = Path.cwd().name or "Workspace"
    where = f"{project} ({branch})" if branch else project
    footer = Text(f"{where} · mode: code · /help", style=f"dim {GRAY}")
    rule = Text("─" * max(1, width), style=f"dim {PURPLE}")
    if width >= 80:
        hint_text = Text(hint, style=f"dim {GRAY}")
        return Group(rule, footer, hint_text)
    return Group(rule, footer)


def _render_message(message: DemoMessage):
    if message.kind == "user":
        return Panel(
            Text(message.text, style=LIGHT),
            title=Text("You", style=PURPLE_LIGHT),
            border_style=PURPLE,
            style=USER_BG,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    if message.kind == "assistant":
        return Group(Text("ZeroCoding", style=f"bold {PURPLE_LIGHT}"), Markdown(message.text, code_theme="monokai"))
    if message.kind == "tool":
        return Text(f"  {message.text} · {message.target} · {message.result}", style=f"dim {GRAY}")
    if message.kind == "approval":
        diff = Syntax(message.result, "diff", theme="monokai", word_wrap=True)
        choices = Text()
        choices.append("[ Accept ]", style=f"bold black on {GREEN}")
        choices.append("  Reject", style=YELLOW)
        return Panel(
            Group(Text(message.text, style=f"bold {YELLOW}"), diff, choices,
                  Text("↑/↓ select · Enter confirm · Y accept · N/Esc reject", style=f"dim {GRAY}")),
            border_style=YELLOW,
            title="Approval",
            box=box.ROUNDED,
        )
    if message.kind == "error":
        return Text(f"! {message.text}", style=f"bold {RED}")
    return Text(message.text, style=f"dim {GRAY}")


def _activity_view(conversation: DemoConversation, frame: int, phrase: str, elapsed: float, width: int):
    unicode = _unicode_available()
    art = "\n".join(ghost_frame(frame, compact=True, unicode=unicode))
    icon = sparkle(frame, unicode=unicode)
    activity = Text()
    activity.append(f"{icon} ", style=f"bold {PURPLE}")
    activity.append(phrase, style=f"{PURPLE_LIGHT}")
    activity.append(f"  {elapsed:.0f}s", style=f"dim {GRAY}")
    return Group(Text(art, style=f"bold {PURPLE}"), activity)


def _approval_input() -> bool:
    selected = [0]
    keys = KeyBindings()

    @keys.add("up")
    @keys.add("down")
    def move(event):
        selected[0] = 1 - selected[0]

    @keys.add("enter")
    def choose(event):
        event.app.exit(result=selected[0] == 0)

    @keys.add("Y")
    @keys.add("y")
    def accept(event):
        event.app.exit(result=True)

    @keys.add("N")
    @keys.add("n")
    @keys.add("escape")
    def reject(event):
        event.app.exit(result=False)

    def toolbar():
        accept_style = "class:current" if selected[0] == 0 else ""
        reject_style = "class:current" if selected[0] == 1 else ""
        return [
            (accept_style, "[ Accept ]" if selected[0] == 0 else "  Accept  "),
            ("", "    "),
            (reject_style, "[ Reject ]" if selected[0] == 1 else "  Reject  "),
            ("", "    ↑/↓ · Enter · Y/N · Esc"),
        ]

    session = PromptSession(key_bindings=keys, style=Style.from_dict({"current": f"fg:black bg:{GREEN} bold"}))
    return bool(session.prompt("Approval › ", bottom_toolbar=toolbar))


def _run_activity(console: Console, conversation: DemoConversation, phrase: str, seconds: float = 1.0) -> None:
    started = time.monotonic()
    frame = 0
    with Live(
        _activity_view(conversation, frame, phrase, 0.0, console.width),
        console=console,
        refresh_per_second=4,
        transient=True,
        vertical_overflow="visible",
    ) as live:
        while time.monotonic() - started < seconds:
            elapsed = time.monotonic() - started
            live.update(_activity_view(conversation, frame, phrase, elapsed, console.width))
            time.sleep(0.25)
            frame += 1


def _print_welcome(console: Console, conversation: DemoConversation) -> None:
    console.print(_header(console))
    console.print(Text("Local UI prototype · fixed sample data · no model or tools are called", style=f"dim {GRAY}"))
    console.print(_footer(console, conversation.hint))
    console.print()


def run() -> int:
    console = Console(highlight=False)
    conversation = DemoConversation()
    _print_welcome(console, conversation)

    prompt_style = Style.from_dict({
        "prompt": f"bold {PURPLE}",
        "completion-menu.completion": f"bg:#111014 {LIGHT}",
        "completion-menu.completion.current": f"bg:{USER_BG} {LIGHT} bold",
        "completion-menu.meta.completion": f"bg:#111014 {GRAY}",
        "bottom-toolbar": f"bg:#09090B {GRAY}",
    })
    keys = KeyBindings()

    @keys.add("c-j")
    def newline(event):
        event.current_buffer.insert_text("\n")

    @keys.add("up")
    def up_or_history(event):
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_previous()
        else:
            buffer.auto_up()

    @keys.add("down")
    def down_or_history(event):
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.auto_down()

    session = PromptSession(
        history=ProjectPromptHistory(),
        completer=SlashCompleter(),
        complete_while_typing=True,
        style=prompt_style,
        multiline=False,
        key_bindings=keys,
    )

    while True:
        try:
            prompt = session.prompt(
                HTML(f'<style color="{PURPLE}">› </style>'),
                bottom_toolbar=HTML(f'<style color="{GRAY}">{conversation.hint}</style>'),
            )
        except (EOFError, KeyboardInterrupt):
            return 0
        if not prompt.strip():
            continue
        previous_count = len(conversation.messages)
        result = conversation.submit(prompt)
        new_messages = conversation.messages[previous_count:]
        if result == "quit":
            console.print(Text("ZeroCoding prototype closed.", style=f"dim {GRAY}"))
            return 0
        if result == "clear":
            console.clear()
            _print_welcome(console, conversation)
            continue
        if result == "help":
            table = Table(title="Prototype controls", box=box.SIMPLE, show_header=False, expand=False)
            for command, description in DEMO_COMMANDS:
                table.add_row(Text(command, style=f"bold {PURPLE}"), Text(description, style=LIGHT))
            console.print(table)
            continue
        if result == "approval":
            for message in new_messages:
                console.print(_render_message(message))
            accepted = _approval_input()
            conversation.resolve_approval(accepted)
            console.print(_render_message(conversation.messages[-1]))
            console.print(Text("Approval accepted." if accepted else "Approval declined.", style=f"dim {GRAY}"))
            continue
        if result == "error":
            for message in new_messages:
                console.print(_render_message(message))
            continue

        user_message = conversation.messages[-1]
        console.print(_render_message(user_message))
        turn_started = time.monotonic()
        if result == "tool":
            phrase = random_work_phrase()
            _run_activity(console, conversation, phrase, 0.8)
            for event in conversation.tool_scenario_events()[:2]:
                conversation.set_tool_activity(event.text, event.target)
                _run_activity(console, conversation, conversation.status, 0.45)
                console.print(_render_message(event))
                phrase = random_work_phrase()
                _run_activity(console, conversation, phrase, 0.65)
            response = conversation.tool_scenario_events()[-1]
        else:
            phrase = random_work_phrase()
            _run_activity(console, conversation, phrase, 1.2)
            response = DemoMessage("assistant", conversation.response_for(user_message.text))
        console.print(_render_message(response))
        elapsed = time.monotonic() - turn_started
        conversation.finish(elapsed)
        console.print(Text(f"  Worked for {elapsed:.1f}s", style=f"dim {GRAY}"))


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(run())

