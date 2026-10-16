#!/usr/bin/env python3
"""Measure M1 prototype startup, idle RSS, and idle CPU on Linux."""
from __future__ import annotations

import fcntl
import os
import pty
import select
import statistics
import struct
import sys
import termios
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT_MARKER = "›".encode("utf-8")
START_TIMEOUT_SECONDS = 20
IDLE_RSS_SECONDS = 30
IDLE_CPU_SECONDS = 60
STARTUP_RUNS = 5


def _start(stack: str) -> tuple[int, int, float, bytearray]:
    started = time.monotonic()
    pid, fd = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        paths = [str(ROOT / "src")]
        if environment.get("PYTHONPATH"):
            paths.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        environment.setdefault("TERM", "xterm-256color")
        os.execve(sys.executable, [sys.executable, "-m", "zerocoding.tui.demo", stack], environment)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    output = bytearray()
    deadline = started + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        _drain(fd, output, 0.1)
        if PROMPT_MARKER in output:
            return pid, fd, time.monotonic() - started, output
        exited, status = os.waitpid(pid, os.WNOHANG)
        if exited:
            raise RuntimeError(f"{stack} exited before showing its prompt (status={status}): {_tail(output)}")
    _stop(pid, fd)
    raise TimeoutError(f"{stack} did not show its prompt within {START_TIMEOUT_SECONDS}s: {_tail(output)}")


def _drain(fd: int, output: bytearray, timeout: float) -> None:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return
    try:
        data = os.read(fd, 65536)
    except OSError:
        return
    if data:
        output.extend(data)
        if len(output) > 200_000:
            del output[:-100_000]


def _tail(output: bytearray) -> str:
    return bytes(output[-2000:]).decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")


def _stop(pid: int, fd: int) -> None:
    try:
        os.write(fd, b"/quit\r")
    except OSError:
        pass
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        _drain(fd, bytearray(), 0.1)
        try:
            exited, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            os.close(fd)
            return
        if exited:
            os.close(fd)
            return
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    os.close(fd)


def _proc_cpu_ticks(pid: int) -> int:
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    fields = stat[stat.rfind(")") + 2:].split()
    return int(fields[11]) + int(fields[12])


def _proc_rss_mib(pid: int) -> float:
    resident_pages = int(Path(f"/proc/{pid}/statm").read_text(encoding="ascii").split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)


def _wait_and_drain(pid: int, fd: int, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    sink = bytearray()
    while time.monotonic() < deadline:
        _drain(fd, sink, min(0.25, max(0.0, deadline - time.monotonic())))
        exited, status = os.waitpid(pid, os.WNOHANG)
        if exited:
            raise RuntimeError(f"prototype exited during idle sampling (status={status}): {_tail(sink)}")


def _measure_idle(stack: str) -> tuple[float, float]:
    pid, fd, _startup_seconds, _output = _start(stack)
    try:
        _wait_and_drain(pid, fd, IDLE_RSS_SECONDS)
        rss_mib = _proc_rss_mib(pid)
        start_ticks = _proc_cpu_ticks(pid)
        started = time.monotonic()
        _wait_and_drain(pid, fd, IDLE_CPU_SECONDS)
        elapsed = time.monotonic() - started
        cpu_ticks = _proc_cpu_ticks(pid) - start_ticks
        cpu_percent = 100 * cpu_ticks / os.sysconf("SC_CLK_TCK") / elapsed
        return rss_mib, cpu_percent
    finally:
        _stop(pid, fd)


def measure(stack: str) -> tuple[float, float, float]:
    startup_times = []
    for _ in range(STARTUP_RUNS):
        pid, fd, startup_seconds, _output = _start(stack)
        startup_times.append(startup_seconds)
        _stop(pid, fd)
    rss_mib, cpu_percent = _measure_idle(stack)
    return statistics.median(startup_times), rss_mib, cpu_percent


def main() -> int:
    if sys.platform != "linux":
        raise SystemExit("This resource measurement script currently requires Linux (/proc and a PTY).")
    print("Measuring the same 80x24 idle UI on this machine (five fresh launches, then a 90s idle sample).")
    print("No model is loaded. Do not type into the prototype while it is being measured.\n")
    print(f"{'Prototype':<25} {'Startup median':>16} {'RSS at 30s':>13} {'Idle CPU':>12}")
    for stack, label in (("rich", "Rich + prompt_toolkit"), ("textual", "Textual")):
        startup, rss, cpu = measure(stack)
        print(f"{label:<25} {startup:>13.3f}s {rss:>10.1f} MiB {cpu:>9.2f}%")
    return 0


if __name__ == "__main__":  # pragma: no cover - utility entry point
    raise SystemExit(main())

