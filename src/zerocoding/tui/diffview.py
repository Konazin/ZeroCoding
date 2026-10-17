"""Claude Code style diff rendering: line-number gutter, red/green rows, dim context."""
from __future__ import annotations

import re
from dataclasses import dataclass

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

ADDED_BG, REMOVED_BG = "#12301f", "#3a1620"
ADDED_FG, REMOVED_FG, CONTEXT_FG, GUTTER_FG = "#86EFAC", "#FCA5A5", "#9CA3AF", "#6B7280"
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class DiffLine:
    kind: str      # "add", "del" or "ctx"
    number: int    # new-file number for add/ctx, old-file number for del
    text: str


def parse_diff(diff: str) -> tuple[str, list[DiffLine]]:
    """Return (path, lines) from unified diff text. Unknown shapes yield no lines."""
    path, lines, old_no, new_no = "", [], 0, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            path = path[2:] if path.startswith("b/") else path
        elif raw.startswith("--- "):
            if not path:
                path = raw[4:].strip()
        elif match := _HUNK.match(raw):
            old_no, new_no = int(match.group(1)), int(match.group(2))
        elif raw.startswith("+"):
            lines.append(DiffLine("add", new_no, raw[1:])); new_no += 1
        elif raw.startswith("-"):
            lines.append(DiffLine("del", old_no, raw[1:])); old_no += 1
        elif raw.startswith(" "):
            lines.append(DiffLine("ctx", new_no, raw[1:])); old_no += 1; new_no += 1
    if path == "/dev/null":
        path = ""
    return path, lines


def looks_like_diff(text: str) -> bool:
    return text.startswith(("--- ", "+++ ")) or "\n+++ " in text


def summarize(lines: list[DiffLine]) -> str:
    added = sum(line.kind == "add" for line in lines)
    removed = sum(line.kind == "del" for line in lines)
    parts = []
    if added:
        parts.append(f"Added {added} line{'s' if added != 1 else ''}")
    if removed:
        parts.append(f"removed {removed} line{'s' if removed != 1 else ''}" if parts else f"Removed {removed} line{'s' if removed != 1 else ''}")
    return ", ".join(parts) or "No changes"


class DiffView:
    """Rich renderable; rows fill the available width so the red/green bands read as blocks."""

    def __init__(self, diff: str, indent: int = 5, max_lines=None, hint: str = ""):
        """`max_lines` is an int, None (all rows) or a callable evaluated at render time, so a toggle such as
        Ctrl+T takes effect on diffs that are already on screen. `hint` is appended to the "more lines" row."""
        self.path, self.lines = parse_diff(diff)
        self.indent, self.max_lines, self.hint = indent, max_lines, hint

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        limit = self.max_lines() if callable(self.max_lines) else self.max_lines
        shown = self.lines if limit is None else self.lines[:limit]
        digits = max((len(str(line.number)) for line in shown), default=1)
        width = max(20, options.max_width - self.indent)
        for line in shown:
            sign = {"add": "+", "del": "-", "ctx": " "}[line.kind]
            fg = {"add": ADDED_FG, "del": REMOVED_FG, "ctx": CONTEXT_FG}[line.kind]
            bg = {"add": f" on {ADDED_BG}", "del": f" on {REMOVED_BG}", "ctx": ""}[line.kind]
            row = Text(" " * self.indent)
            body = Text(f"{str(line.number).rjust(digits)} {sign} {line.text.expandtabs(4)}", style=fg + bg)
            body.stylize(GUTTER_FG + bg, 0, digits)
            body.truncate(width, overflow="ellipsis", pad=True)
            row.append_text(body)
            yield row
        if len(shown) < len(self.lines):
            more = f"… +{len(self.lines) - len(shown)} lines" + (f" ({self.hint})" if self.hint else "")
            yield Text(" " * self.indent + more, style=f"dim {CONTEXT_FG}")
