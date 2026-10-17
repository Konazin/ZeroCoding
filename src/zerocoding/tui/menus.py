"""Terminal screens for settings: select lists, bordered text boxes and a tabbed settings panel.

Layout follows Claude Code's /model picker and /config panel. Every screen is a small state machine
(`key(name) -> Done | None` plus `fragments(width)`), so behavior is tested by feeding keys and the
prompt_toolkit runner only translates real key presses into those names.

Key names: "up" "down" "left" "right" "enter" "escape" "tab" "backspace" "ctrl-u", and "char:x"
for printable characters.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    HAS_PROMPT_TOOLKIT = True
except ImportError:  # pragma: no cover - prompt_toolkit is a declared dependency
    HAS_PROMPT_TOOLKIT = False

ACCENT, GOOD, WARN, BAD, DIM = "#C4B5FD", "#86EFAC", "#FDE68A", "#FCA5A5", "#9CA3AF"


@dataclass
class Done:
    value: object = None  # None means cancelled
    key: str = "enter"

    @property
    def cancelled(self) -> bool:
        return self.value is None


CANCELLED = Done(None, "escape")


@dataclass
class Row:
    name: str
    value: str = ""        # right-hand column (settings) or description (pickers)
    id: object = None
    checked: bool = False  # shows the green check, e.g. the active provider or model
    enabled: bool = True


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _window(total: int, index: int, size: int) -> tuple[int, int]:
    """First and last+1 row to show so that `index` stays visible."""
    if total <= size:
        return 0, total
    start = min(max(0, index - size + 1 + size // 2), total - size)
    return start, start + size


def _box(value: str, placeholder: str, width: int, icon: str = "") -> list[tuple[str, str]]:
    inner = max(10, min(width - 4, 72))
    shown = _clip(value, inner - 4 - len(icon)) if value else ""
    body = (icon + " " if icon else "") + (shown + "▌" if value or not placeholder else "▌" + _clip(placeholder, inner - 6))
    pad = " " * max(0, inner - 2 - len(body))
    top, bottom = "╭" + "─" * (inner - 2) + "╮", "╰" + "─" * (inner - 2) + "╯"
    style = "" if value else f"fg:{DIM}"
    return [(f"fg:{ACCENT}", top + "\n"), (f"fg:{ACCENT}", "│ "), (style, body + pad[:-1] if pad else body),
            (f"fg:{ACCENT}", "│\n"), (f"fg:{ACCENT}", bottom + "\n")]


class SelectScreen:
    """Numbered picker: name column, description column, check mark, optional ←/→ adjuster."""

    def __init__(self, title: str, rows: list[Row], subtitle: str = "", index: int = 0,
                 extra_keys: dict[str, str] | None = None, adjust: tuple[str, list[str], str] | None = None,
                 enter_text: str = "Enter to confirm", window: int = 8):
        self.title, self.subtitle, self.rows = title, subtitle, rows
        self.index = min(max(0, index), max(0, len(rows) - 1))
        self.extra_keys = extra_keys or {}
        self.levels = adjust[1] if adjust else []   # adjust = (label, levels, current)
        self.adjust_label = adjust[0] if adjust else ""
        self.adjusted = adjust[2] if adjust else ""
        self.enter_text, self.window = enter_text, window

    def key(self, name: str) -> Done | None:
        if name == "escape":
            return CANCELLED
        if not self.rows and name != "escape":
            return None
        if name == "up":
            self.index = (self.index - 1) % len(self.rows)
        elif name == "down":
            self.index = (self.index + 1) % len(self.rows)
        elif name in {"left", "right"} and self.levels:
            step = -1 if name == "left" else 1
            at = self.levels.index(self.adjusted) if self.adjusted in self.levels else 0
            self.adjusted = self.levels[min(max(0, at + step), len(self.levels) - 1)]
        elif name == "enter":
            return Done(self.index, "enter")
        elif name.startswith("char:"):
            char = name[5:]
            if char in self.extra_keys:
                return Done(self.index, char)
            if char.isdigit() and 1 <= int(char) <= len(self.rows):
                self.index = int(char) - 1
        return None

    def footer(self) -> str:
        parts = [self.enter_text] + [f"{k} {t}" for k, t in self.extra_keys.items()] + ["Esc to cancel"]
        return " · ".join(parts)

    def fragments(self, width: int) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = [(f"bold fg:{ACCENT}", self.title + "\n")]
        if self.subtitle:
            out.append(("", self.subtitle + "\n"))
        out.append(("", "\n"))
        start, end = _window(len(self.rows), self.index, self.window)
        name_w = min(max((len(r.name) for r in self.rows), default=0) + 2, max(12, width // 2))
        if start:
            out.append((f"fg:{DIM}", f"  ↑ {start} more\n"))
        for position in range(start, end):
            row, active = self.rows[position], position == self.index
            mark = "❯" if active else " "
            label = _clip(row.name, name_w - 1).ljust(name_w)
            style = f"bold fg:{GOOD}" if (active and row.checked) else (f"bold fg:{ACCENT}" if active else "")
            out.append((f"fg:{ACCENT}", f"{mark} "))
            out.append((style or "", f"{position + 1}. {label}"))
            out.append((f"fg:{GOOD}", "✔ " if row.checked else "  "))
            out.append((f"fg:{DIM}", _clip(row.value, max(0, width - name_w - 12)) + "\n"))
        if end < len(self.rows):
            out.append((f"fg:{DIM}", f"  … +{len(self.rows) - end} more\n"))
        out.append(("", "\n"))
        if self.levels:
            out.append((f"fg:{WARN}", "◐ "))
            out.append(("", f"{self.adjusted.title()} {self.adjust_label} "))
            out.append((f"fg:{DIM}", "←/→ to adjust\n\n"))
        out.append((f"fg:{DIM}", self.footer() + "\n"))
        return out


class InputScreen:
    """Bordered text box with inline validation; replaces typing positional command arguments."""

    def __init__(self, title: str, subtitle: str = "", default: str = "", placeholder: str = "",
                 validate: Callable[[str], str | None] | None = None, icon: str = "", fallback: str = ""):
        self.title, self.subtitle, self.placeholder, self.icon = title, subtitle, placeholder, icon
        self.fallback = fallback  # used when Enter is pressed on an empty box; shown as the placeholder
        self.value, self.validate, self.error = default, validate, ""

    def key(self, name: str) -> Done | None:
        if name == "escape":
            return CANCELLED
        if name == "enter":
            text = self.value.strip() or self.fallback
            self.error = (self.validate(text) if self.validate else None) or ""
            return None if self.error else Done(text, "enter")
        if name == "backspace":
            self.value = self.value[:-1]
        elif name == "ctrl-u":
            self.value = ""
        elif name.startswith("char:"):
            self.value += name[5:]
        self.error = ""
        return None

    def fragments(self, width: int) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = [(f"bold fg:{ACCENT}", self.title + "\n")]
        if self.subtitle:
            out.append(("", self.subtitle + "\n"))
        out.append(("", "\n"))
        hint = self.placeholder or (f"{self.fallback}  (Enter to accept)" if self.fallback else "")
        out += _box(self.value, hint, width, self.icon)
        out.append((f"fg:{BAD}", (self.error if self.error else "") + "\n"))
        out.append((f"fg:{DIM}", "Enter to confirm · Ctrl+U to clear · Esc to cancel\n"))
        return out


@dataclass
class Tab:
    name: str
    rows: Callable[[], list[Row]] | None = None   # selectable list (Config, Providers)
    lines: Callable[[], list[tuple[str, str]]] | None = None  # read-only label/value lines (Status)
    searchable: bool = False


class SettingsScreen:
    """Tab bar, optional search box and a name/value list. Enter returns (tab name, row id)."""

    def __init__(self, tabs: list[Tab], tab: str | None = None, window: int = 10):
        self.tabs, self.window = tabs, window
        self.tab = next((i for i, t in enumerate(tabs) if t.name == tab), 0)
        self.focus = "tabs" if self.current.rows is None else "list"
        self.index, self.query = 0, ""

    @property
    def current(self) -> Tab:
        return self.tabs[self.tab]

    def visible_rows(self) -> list[Row]:
        rows = self.current.rows() if self.current.rows else []
        needle = self.query.lower()
        return [r for r in rows if needle in r.name.lower() or needle in r.value.lower()] if needle else rows

    def _switch(self, step: int) -> None:
        self.tab = (self.tab + step) % len(self.tabs)
        self.index, self.query = 0, ""
        if self.current.rows is None:
            self.focus = "tabs"

    def key(self, name: str) -> Done | None:
        rows = self.visible_rows()
        if name == "escape":
            if self.focus == "list" and self.query:
                self.query, self.index = "", 0
                return None
            return CANCELLED
        if name == "tab":
            self._switch(1)
        elif self.focus == "tabs":
            if name == "left":
                self._switch(-1)
            elif name == "right":
                self._switch(1)
            elif name in {"down", "enter"} and self.current.rows is not None:
                self.focus = "list"
        else:  # list focus
            if name == "up":
                if self.index == 0:
                    self.focus = "tabs"
                else:
                    self.index -= 1
            elif name == "down" and rows:
                self.index = min(self.index + 1, len(rows) - 1)
            elif name == "enter" and rows and rows[self.index].enabled:
                return Done((self.current.name, rows[self.index].id), "enter")
            elif name == "backspace" and self.current.searchable:
                self.query, self.index = self.query[:-1], 0
            elif name.startswith("char:") and self.current.searchable:
                self.query, self.index = self.query + name[5:], 0
        return None

    def fragments(self, width: int) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = [(f"bold fg:{ACCENT}", "Settings  ")]
        for i, tab in enumerate(self.tabs):
            if i == self.tab:
                style = f"bold reverse fg:{ACCENT}" if self.focus == "tabs" else "bold reverse"
                out.append((style, f" {tab.name} "))
            else:
                out.append(("", f" {tab.name} "))
            out.append(("", " "))
        out.append(("", "\n\n"))
        tab = self.current
        if tab.lines is not None:
            for label, value in tab.lines():
                out.append((f"fg:{DIM}", label.ljust(18)))
                out.append(("", value + "\n"))
        if tab.searchable:
            out += _box(self.query, "Search settings…", width, "⌕")
        if tab.rows is not None:
            rows = self.visible_rows()
            start, end = _window(len(rows), self.index, self.window)
            name_w = min(max((len(r.name) for r in rows), default=0) + 4, max(16, width // 2))
            if not rows:
                out.append((f"fg:{DIM}", "  No match.\n"))
            for position in range(start, end):
                row = rows[position]
                active = self.focus == "list" and position == self.index
                label_style = f"bold fg:{ACCENT}" if active else ("" if row.enabled else f"fg:{DIM}")
                out.append((f"fg:{ACCENT}", "❯ " if active else "  "))
                out.append((label_style, _clip(row.name, name_w - 1).ljust(name_w)))
                value_style = f"fg:{GOOD}" if row.checked else ("" if row.enabled else f"fg:{DIM}")
                out.append((value_style, ("✔ " if row.checked else "") + _clip(row.value, max(0, width - name_w - 6)) + "\n"))
            if end < len(rows):
                out.append((f"fg:{DIM}", f"  ↓ {len(rows) - end} more\n"))
        hint = "Type to filter · " if tab.searchable else ""
        out.append(("", "\n"))
        out.append((f"fg:{DIM}", f"{hint}Enter/↓ to select · ↑ to tabs · ←/→ switch tabs · Esc to "
                    f"{'clear' if self.query else 'close'}\n"))
        return out


def run_screen(screen, width: int | None = None) -> Done:
    """Draw a screen inline and return its result; cancelled when there is no terminal."""
    if not HAS_PROMPT_TOOLKIT or not sys.stdin.isatty() or not sys.stdout.isatty():
        return CANCELLED
    import shutil
    bindings = KeyBindings()
    result: list[Done] = []

    def feed(event, name):
        done = screen.key(name)
        if done is not None:
            result.append(done)
            event.app.exit()

    for key, name in (("up", "up"), ("down", "down"), ("left", "left"), ("right", "right"),
                      ("enter", "enter"), ("tab", "tab"), ("backspace", "backspace"), ("c-h", "backspace"),
                      ("c-u", "ctrl-u")):
        bindings.add(key)(lambda event, name=name: feed(event, name))
    bindings.add("escape", eager=True)(lambda event: feed(event, "escape"))
    bindings.add("c-c")(lambda event: feed(event, "escape"))

    @bindings.add(Keys.Any)
    def _(event):
        data = event.data
        if data and data.isprintable():
            feed(event, "char:" + data)

    def render():
        return FormattedText(screen.fragments(width or shutil.get_terminal_size((80, 24)).columns))

    app = Application(layout=Layout(Window(FormattedTextControl(render, show_cursor=False), always_hide_cursor=True)),
                      key_bindings=bindings, full_screen=False, erase_when_done=True)
    app.run()
    return result[0] if result else CANCELLED
