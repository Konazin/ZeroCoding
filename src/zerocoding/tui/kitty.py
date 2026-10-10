"""Small, optional Kitty graphics protocol support for the terminal mascot."""
from __future__ import annotations

import base64
import os
import re
import secrets
import select
import time

from prompt_toolkit.input.vt100 import Vt100Input

from ._mascot_sprites import MASCOT_FRAME_DELAY_MS, MASCOT_PNG_FRAMES, MASCOT_STATES
from .mascot import render_kitty_placeholder


PROBE_TIMEOUT = 0.25
PROBE_SEQUENCE = "\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\\x1b[c"
_KITTY_REPLY = "\x1b_Gi=31;"
_KITTY_RESPONSE = re.compile(r"\x1b_Gi=\d+;")
_ST = "\x1b\\"
_DA_REPLY = re.compile(r"\x1b\[\?[0-9;]*c")
_DIACRITICS = (0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F)


def kitty_probe_supported(data: str | bytes) -> bool | None:
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("ascii", errors="ignore")
    start = data.find(_KITTY_REPLY)
    if start >= 0:
        end = data.find(_ST, start)
        if end < 0:
            return False if _DA_REPLY.search(data) else None
        return data[start + len(_KITTY_REPLY):end] == "OK"
    return False if _DA_REPLY.search(data) else None


class KittyInputFilter:
    """Strip only the graphics and device-attribute replies sent by our probe."""

    def __init__(self):
        self.pending = ""

    def feed(self, data: str) -> str:
        data = self.pending + data
        self.pending = ""
        output = []
        cursor = 0
        while cursor < len(data):
            kitty_match = _KITTY_RESPONSE.search(data, cursor)
            kitty = kitty_match.start() if kitty_match else -1
            da = data.find("\x1b[?", cursor)
            starts = [position for position in (kitty, da) if position >= 0]
            if not starts:
                output.append(data[cursor:])
                break
            start = min(starts)
            output.append(data[cursor:start])
            if start == kitty:
                end = data.find(_ST, start)
                if end < 0:
                    self.pending = data[start:]
                    break
                cursor = end + len(_ST)
            else:
                match = _DA_REPLY.match(data, start)
                if match:
                    cursor = match.end()
                elif data[start:] in {"\x1b[?", "\x1b[?1", "\x1b[?1;"}:
                    self.pending = data[start:]
                    break
                else:
                    output.append(data[start])
                    cursor = start + 1
        return "".join(output)


class KittyAwareVt100Input(Vt100Input):
    def __init__(self, stdin):
        super().__init__(stdin)
        self._reply_filter = KittyInputFilter()

    def feed_raw(self, data: str) -> None:
        filtered = self._reply_filter.feed(data)
        if filtered:
            self.vt100_parser.feed(filtered)

    def read_keys(self):
        self.feed_raw(self.stdin_reader.read())
        result, self._buffer = self._buffer, []
        return result


def kitty_probe(input_stream, write, timeout: float = PROBE_TIMEOUT) -> tuple[bool, bytes]:
    """Query Kitty and preserve any bytes typed while the short probe runs."""
    timeout = min(max(0.0, timeout), PROBE_TIMEOUT)
    buffered = bytearray()
    try:
        with input_stream.raw_mode():
            write(PROBE_SEQUENCE)
            deadline = time.monotonic() + timeout
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                readable, _, _ = select.select([input_stream.fileno()], [], [], remaining)
                if not readable:
                    break
                chunk = os.read(input_stream.fileno(), 4096)
                if not chunk:
                    break
                buffered.extend(chunk)
                status = kitty_probe_supported(buffered)
                if status is not None:
                    return status, bytes(buffered)
    except (OSError, ValueError, TypeError):
        return False, bytes(buffered)
    return False, bytes(buffered)


def _graphics_command(control: str, payload: str = "") -> str:
    return f"\x1b_G{control};{payload}{_ST}"


def _transmit_png(image_id: int, png: bytes, frame_delay: int | None = None) -> str:
    encoded = base64.b64encode(png).decode("ascii")
    chunks = [encoded[index:index + 4096] for index in range(0, len(encoded), 4096)] or [""]
    output = []
    for index, chunk in enumerate(chunks):
        more = int(index < len(chunks) - 1)
        if index == 0:
            action = "f" if frame_delay is not None else "t"
            control = f"a={action},i={image_id},f=100,q=2"
            if frame_delay is not None:
                control += f",z={frame_delay}"
            if more:
                control += ",m=1"
        else:
            control = f"{'a=f,' if frame_delay is not None else ''}m={more},q=2"
        output.append(_graphics_command(control, chunk))
    return "".join(output)


class KittyMascot:
    """Uploads transparent state loops once and selects them through placeholders."""

    def __init__(self, id_factory=None):
        self._id_factory = id_factory or (lambda: secrets.randbelow(0xFFFFFF) + 1)
        self.image_ids = {}
        self._active = None

    def placeholder(self, state: str, compact: bool):
        size = "compact" if compact else "normal"
        return render_kitty_placeholder(self.image_ids[(state, size)], compact=compact)

    def upload(self, write) -> None:
        used = set()
        commands = []
        for state in MASCOT_STATES:
            encoded_frames = MASCOT_PNG_FRAMES[state]
            for size, (columns, rows) in (("normal", (8, 4)), ("compact", (6, 3))):
                image_id = self._id_factory()
                while not 0 < image_id <= 0xFFFFFF or image_id in used:
                    image_id = self._id_factory()
                used.add(image_id)
                self.image_ids[(state, size)] = image_id
                commands.append(_transmit_png(image_id, base64.b64decode(encoded_frames[0])))
                for frame in encoded_frames[1:]:
                    commands.append(_transmit_png(image_id, base64.b64decode(frame), MASCOT_FRAME_DELAY_MS))
                commands.append(_graphics_command(f"a=a,i={image_id},r=1,z={MASCOT_FRAME_DELAY_MS},q=2"))
                commands.append(_graphics_command(f"a=p,U=1,i={image_id},c={columns},r={rows},q=2"))
        write("".join(commands))

    def update(self, state: str, compact: bool, write) -> None:
        key = (state, "compact" if compact else "normal")
        image_id = self.image_ids[key]
        if key == self._active:
            return
        commands = []
        if self._active is not None:
            old_id = self.image_ids[self._active]
            commands.append(_graphics_command(f"a=a,i={old_id},s=1,q=2"))
        commands.append(_graphics_command(f"a=a,i={image_id},s=3,v=1,q=2"))
        write("".join(commands))
        self._active = key

    def cleanup(self, write) -> None:
        commands = []
        if self._active is not None:
            commands.append(_graphics_command(f"a=a,i={self.image_ids[self._active]},s=1,q=2"))
            self._active = None
        commands.extend(_graphics_command(f"a=d,d=I,i={image_id},q=2") for image_id in set(self.image_ids.values()))
        write("".join(commands))

    def stop(self, write) -> None:
        if self._active is not None:
            image_id = self.image_ids[self._active]
            write(_graphics_command(f"a=a,i={image_id},s=1,q=2"))
            self._active = None
