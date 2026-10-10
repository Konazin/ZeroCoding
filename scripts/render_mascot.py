"""Build animated terminal sprites and Kitty PNG frames from the source atlas.

Pillow is only needed to regenerate these assets; the TUI loads the generated
Python data module and does not import Pillow.
"""
from __future__ import annotations

import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mascot" / "animated-atlas.png"
GIF_DIR = ROOT / "assets" / "mascot" / "animations"
OUTPUT = ROOT / "src" / "zerocoding" / "tui" / "_mascot_sprites.py"
STATES = ("idle", "thinking", "tool", "approval", "done", "error")
SIZES = {"normal": (8, 4), "compact": (6, 3)}
FRAME_COUNT = 4
FRAME_DELAY_MS = 200
PNG_SIDE = 192


def xterm_palette():
    base = [
        (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
        (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
        (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
        (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
    ]
    levels = (0, 95, 135, 175, 215, 255)
    base.extend((red, green, blue) for red in levels for green in levels for blue in levels)
    base.extend((gray, gray, gray) for gray in range(8, 239, 10))
    return base


PALETTE = xterm_palette()


def _palette_hex(rgb):
    red, green, blue = rgb
    return min(
        PALETTE,
        key=lambda color: (
            (2 + (red + color[0]) / 256) * (red - color[0]) ** 2
            + 4 * (green - color[1]) ** 2
            + (2 + (510 - red - color[0]) / 256) * (blue - color[2]) ** 2
        ),
    )


def _artwork_canvas(cell, side, Image):
    visible = cell.getchannel("A").point(lambda alpha: 255 if alpha >= 96 else 0)
    bounds = visible.getbbox()
    if bounds is None:
        raise ValueError("sprite cell is empty")
    artwork = cell.crop(bounds)
    artwork.thumbnail((side, side), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(artwork, ((side - artwork.width) // 2, (side - artwork.height) // 2))
    return canvas


def _save_gif_frames(frames, path, Image):
    palette_frames = []
    for frame in frames:
        rgba = frame.convert("RGBA")
        quantized = rgba.convert("RGB").quantize(colors=255, method=Image.Quantize.FASTOCTREE)
        alpha = rgba.getchannel("A").getdata()
        indices = quantized.getdata()
        quantized.putdata([index if opacity >= 96 else 255 for index, opacity in zip(indices, alpha)])
        palette = quantized.getpalette() or []
        palette.extend([0] * (768 - len(palette)))
        palette[765:768] = [0, 0, 0]
        quantized.putpalette(palette[:768])
        quantized.info["transparency"] = 255
        palette_frames.append(quantized)
    palette_frames[0].save(
        path,
        save_all=True,
        append_images=palette_frames[1:],
        duration=FRAME_DELAY_MS,
        loop=0,
        disposal=2,
        transparency=255,
        optimize=False,
    )


def write_gifs(source=SOURCE, destination=GIF_DIR):
    from PIL import Image

    atlas = Image.open(source).convert("RGBA")
    if atlas.width % len(STATES) or atlas.height % FRAME_COUNT:
        raise ValueError("animated atlas must have six columns and four equal frame rows")
    cell_width, cell_height = atlas.width // len(STATES), atlas.height // FRAME_COUNT
    if cell_width != cell_height:
        raise ValueError("animated atlas cells must be square")
    destination.mkdir(parents=True, exist_ok=True)
    for column, state in enumerate(STATES):
        frames = []
        for row in range(FRAME_COUNT):
            cell = atlas.crop((column * cell_width, row * cell_height, (column + 1) * cell_width, (row + 1) * cell_height))
            frames.append(_artwork_canvas(cell, PNG_SIDE, Image))
        _save_gif_frames(frames, destination / f"{state}.gif", Image)


def _load_gif(path, Image):
    frames = []
    with Image.open(path) as image:
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frames.append(image.convert("RGBA").copy())
    if len(frames) != FRAME_COUNT:
        raise ValueError(f"{path.name} must contain {FRAME_COUNT} animation frames")
    return frames


def _ansi_frame(image, width, height, Image):
    artwork = image.copy()
    artwork.thumbnail((width, height * 2), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height * 2), (0, 0, 0, 0))
    canvas.alpha_composite(artwork, ((width - artwork.width) // 2, (height * 2 - artwork.height) // 2))
    def color_at(x, y):
        red, green, blue, alpha = canvas.getpixel((x, y))
        return "______" if alpha < 96 else "".join(f"{value:02X}" for value in _palette_hex((red, green, blue)))

    return tuple(
        "".join(color_at(x, y) + color_at(x, y + 1) for x in range(width))
        for y in range(0, height * 2, 2)
    )


def _png_bytes(image):
    from io import BytesIO

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def render_data(source=GIF_DIR):
    from PIL import Image

    sprites, png_frames = {}, {}
    for state in STATES:
        frames = _load_gif(Path(source) / f"{state}.gif", Image)
        sprites[state] = {size: tuple(_ansi_frame(frame, *dimensions, Image) for frame in frames) for size, dimensions in SIZES.items()}
        png_frames[state] = tuple(_png_bytes(frame) for frame in frames)
    return sprites, png_frames


def write_module(sprites, png_frames, destination=OUTPUT):
    lines = [
        '"""Generated by scripts/render_mascot.py; do not edit by hand."""',
        f"MASCOT_STATES = {STATES!r}",
        f"MASCOT_FRAME_DELAY_MS = {FRAME_DELAY_MS}",
        "MASCOT_FRAMES = {",
    ]
    for state, sizes in sprites.items():
        lines.append(f"    {state!r}: {{")
        for size_name, frames in sizes.items():
            lines.append(f"        {size_name!r}: (")
            for frame in frames:
                lines.append("            (")
                lines.extend(f"                {row!r}," for row in frame)
                lines.append("            ),")
            lines.append("        ),")
        lines.append("    },")
    lines.extend(("}", "MASCOT_PNG_FRAMES = {"))
    for state, frames in png_frames.items():
        lines.append(f"    {state!r}: {frames!r},")
    lines.append("}\n")
    destination.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    try:
        write_gifs()
        write_module(*render_data())
    except ImportError as exc:
        raise SystemExit("Install Pillow to regenerate mascot assets: python3 -m pip install Pillow") from exc
    print(f"Wrote {OUTPUT.relative_to(ROOT)} and {GIF_DIR.relative_to(ROOT)}")
