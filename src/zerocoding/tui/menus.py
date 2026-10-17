"""Arrow-key menus for the settings flows (/config), modeled on Claude Code's pickers.

`MenuState` holds the logic so it can be tested without a terminal; `run_menu` and `ask_text`
draw it with prompt_toolkit and fall back to numbered prompts when there is no terminal.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    HAS_PROMPT_TOOLKIT = True
except ImportError:  # pragma: no cover - prompt_toolkit is a declared dependency
    HAS_PROMPT_TOOLKIT = False


@dataclass
class MenuOption:
    label: str
    hint: str = ""


@dataclass
class MenuState:
    title: str
    options: list[MenuOption]
    index: int = 0
    extra_keys: dict[str, str] = field(default_factory=dict)  # key -> help text, e.g. {"s": "this session only"}

    def move(self, delta: int) -> None:
        if self.options:
            self.index = (self.index + delta) % len(self.options)

    def jump(self, number: int) -> bool:
        """Select by 1-based number; returns False when out of range."""
        if 1 <= number <= len(self.options):
            self.index = number - 1
            return True
        return False

    def help_line(self) -> str:
        parts = ["↑↓ select", "enter confirm", "esc cancel"]
        parts += [f"{key} {text}" for key, text in self.extra_keys.items()]
        return " · ".join(parts)

    def lines(self, accent="ansimagenta", dim="ansibrightblack") -> list[tuple[str, str]]:
        out = [(f"bold {accent}", self.title + "\n")]
        for number, option in enumerate(self.options, start=1):
            active = number - 1 == self.index
            out.append((f"bold {accent}" if active else "", f"{'❯' if active else ' '} {number}. {option.label}"))
            if option.hint:
                out.append((dim, f"  {option.hint}"))
            out.append(("", "\n"))
        out.append((dim, self.help_line() + "\n"))
        return out


def run_menu(state: MenuState) -> tuple[int, str] | None:
    """Show the menu; returns (index, key) where key is "enter" or an extra key, or None on Esc."""
    if not state.options:
        return None
    if HAS_PROMPT_TOOLKIT:
        try:
            return _run_prompt_toolkit(state)
        except Exception:
            pass  # not a real terminal: fall through to the numbered prompt
    print(state.title)
    for number, option in enumerate(state.options, start=1):
        print(f"  {number}. {option.label}" + (f"  ({option.hint})" if option.hint else ""))
    try:
        answer = input(f"Number [{state.index + 1}], empty to cancel: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not answer:
        return None
    return (int(answer) - 1, "enter") if answer.isdigit() and state.jump(int(answer)) else None


def _run_prompt_toolkit(state: MenuState) -> tuple[int, str] | None:
    bindings = KeyBindings()

    def finish(event, key):
        event.app.exit(result=(state.index, key))

    @bindings.add("up")
    @bindings.add("k")
    def _(event):
        state.move(-1)

    @bindings.add("down")
    @bindings.add("j")
    def _(event):
        state.move(1)

    @bindings.add("enter")
    def _(event):
        finish(event, "enter")

    @bindings.add("escape", eager=True)
    @bindings.add("c-c")
    def _(event):
        event.app.exit(result=None)

    for digit in "123456789":
        @bindings.add(digit)
        def _(event, digit=digit):
            if state.jump(int(digit)):
                state.index = int(digit) - 1

    for key in state.extra_keys:
        @bindings.add(key)
        def _(event, key=key):
            finish(event, key)

    control = FormattedTextControl(lambda: FormattedText(state.lines()), show_cursor=False)
    app = Application(layout=Layout(Window(control, always_hide_cursor=True)), key_bindings=bindings,
                      full_screen=False, erase_when_done=True)
    return app.run()


def ask_text(prompt: str, default: str = "") -> str | None:
    """Single-line input with an editable default; None when cancelled."""
    try:
        if HAS_PROMPT_TOOLKIT:
            return PromptSession().prompt(f"{prompt} ", default=default).strip()
        return input(f"{prompt} [{default}] ").strip() or default
    except (EOFError, KeyboardInterrupt):
        return None
