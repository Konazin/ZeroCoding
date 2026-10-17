"""Pixel-art mascot "Patinhas": a 12x10 grid per pose, rendered with half blocks.

Each text row packs two pixel rows (▀ ▄ █), so the mascot is 12 columns by 5 rows.
Holes in the body are the eyes, so one foreground color is enough.
"""

BODY = (
    ".....XX.....",
    ".....XX.....",
    "XXXXXXXXXXXX",
    "XXXXXXXXXXXX",
    "XXXXXXXXXXXX",
    "XXXXXXXXXXXX",
    "XXXXXXXXXXXX",
    "XXXXXXXXXXXX",
    "XX.XX..XX.XX",
    "XX.XX..XX.XX",
)

Cells = frozenset  # set of (row, col) pixels cut out of the body

EYES = frozenset({(4, 2), (4, 3), (5, 2), (5, 3), (4, 8), (4, 9), (5, 8), (5, 9)})
SQUINT = frozenset({(5, 2), (5, 3), (5, 8), (5, 9)})
ANTENNA_TIP = frozenset({(0, 5), (0, 6)})
ANTENNA = frozenset({(0, 5), (0, 6), (1, 5), (1, 6)})
LEGS_A = frozenset({(9, 3), (9, 4), (9, 7), (9, 8)})  # inner legs short
LEGS_B = frozenset({(9, 0), (9, 1), (9, 10), (9, 11)})  # outer legs short
PROGRESS = (
    frozenset({(7, 2), (7, 3)}),
    frozenset({(7, 4), (7, 5)}),
    frozenset({(7, 6), (7, 7)}),
    frozenset({(7, 8), (7, 9)}),
)

POSE_HOLES = {
    "idle": EYES,
    "approval": EYES | {(6, 2), (6, 3), (6, 8), (6, 9)},
    "success": frozenset({(4, 3), (5, 2), (5, 4), (4, 8), (5, 7), (5, 9)}),
    "error": frozenset(
        {(4, 2), (4, 4), (5, 3), (6, 2), (6, 4), (4, 7), (4, 9), (5, 8), (6, 7), (6, 9)}
    )
    | ANTENNA,
}

# Walking in place, antenna blinking, progress bar crossing the chest.
WORK_HOLES = tuple(
    SQUINT | PROGRESS[i] | (LEGS_B if i % 2 else LEGS_A) | (ANTENNA_TIP if i > 1 else frozenset())
    for i in range(4)
)
POSES = tuple(POSE_HOLES) + ("work_a", "work_b", "work_c", "work_d")


def holes_for(pose: str) -> frozenset:
    if pose.startswith("work_"):
        return WORK_HOLES[ord(pose[-1]) - ord("a")]
    return POSE_HOLES[pose]


def pose_grid(pose: str) -> tuple[str, ...]:
    holes = holes_for(pose)
    return tuple(
        "".join("." if (r, c) in holes else ch for c, ch in enumerate(row))
        for r, row in enumerate(BODY)
    )


def render(pose: str) -> tuple[str, ...]:
    """Half-block lines for a pose (5 lines, 12 columns)."""
    grid = pose_grid(pose)
    lines = []
    for top, bottom in zip(grid[0::2], grid[1::2]):
        line = ""
        for t, b in zip(top, bottom):
            line += {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}[(t == "X", b == "X")]
        lines.append(line.rstrip())
    return tuple(lines)


def render_ascii(pose: str) -> tuple[str, ...]:
    """Same shape for terminals without Unicode block support."""
    return tuple(line.translate(str.maketrans({"█": "#", "▀": "'", "▄": "_"})) for line in render(pose))


def svg(pose: str = "idle", cell: int = 16, fill: str = "#A78BFA") -> str:
    grid = pose_grid(pose)
    w, h = len(grid[0]) * cell, len(grid) * cell
    rects = [
        f'<rect x="{c * cell}" y="{r * cell}" width="{cell}" height="{cell}"/>'
        for r, row in enumerate(grid) for c, ch in enumerate(row) if ch == "X"
    ]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'shape-rendering="crispEdges"><g fill="{fill}">{"".join(rects)}</g></svg>')
