"""Runtime renderers for the preconverted animated mascot sprites."""
from __future__ import annotations

from ._mascot_sprites import MASCOT_FRAMES, MASCOT_STATES


def render_mascot(state: str, compact: bool = False, frame: int = 0) -> list[list[tuple[str, str]]]:
    size = "compact" if compact else "normal"
    frames = MASCOT_FRAMES.get(state, MASCOT_FRAMES["idle"])[size]
    rows = frames[frame % len(frames)]
    rendered = []
    for row in rows:
        segments = []
        for offset in range(0, len(row), 12):
            top, bottom = row[offset:offset + 6], row[offset + 6:offset + 12]
            if top == "______" and bottom == "______":
                style, char = "", " "
            elif bottom == "______":
                style, char = f"fg:#{top}", "▀"
            elif top == "______":
                style, char = f"fg:#{bottom}", "▄"
            else:
                style, char = f"fg:#{top} bg:#{bottom}", "▀"
            if segments and segments[-1][0] == style:
                segments[-1] = (style, segments[-1][1] + char)
            else:
                segments.append((style, char))
        rendered.append(segments)
    return rendered


def render_kitty_placeholder(image_id: int, compact: bool = False) -> list[list[tuple[str, str]]]:
    width, height = (6, 3) if compact else (8, 4)
    marks = tuple(map(chr, (0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F)))
    style = f"fg:#{image_id:06X}"
    return [
        [(style, "\U0010eeee" + marks[row] + marks[column]) for column in range(width)]
        for row in range(height)
    ]
