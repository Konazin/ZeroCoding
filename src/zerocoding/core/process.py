"""Subprocess helpers that keep captured output bounded while still draining child pipes."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class CappedProcessResult:
    returncode: int
    output: str
    timed_out: bool = False


def run_capped(argv, *, cwd, env, timeout: float, max_output_chars: int,
               input_text: str | None = None) -> CappedProcessResult:
    """Run argv, retain at most max_output_chars bytes, and continue draining excess output."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        start_new_session=(os.name == "posix"),
    )
    limit = max(1, int(max_output_chars))
    captured = bytearray()
    omitted = 0
    collecting = True
    lock = threading.Lock()

    def drain_output():
        nonlocal omitted
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                with lock:
                    if not collecting:
                        continue
                    remaining = limit - len(captured)
                    if remaining > 0:
                        captured.extend(chunk[:remaining])
                    omitted += max(0, len(chunk) - max(0, remaining))
        except (OSError, ValueError):
            return

    reader = threading.Thread(target=drain_output, name="zc-process-output", daemon=True)
    reader.start()

    writer = None
    if input_text is not None:
        def send_input():
            try:
                process.stdin.write(input_text.encode("utf-8"))
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass

        writer = threading.Thread(target=send_input, name="zc-process-input", daemon=True)
        writer.start()

    def stop_process():
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        except OSError:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    timed_out = False
    try:
        process.wait(timeout=max(0.01, timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_process()
        process.wait()
    except KeyboardInterrupt:
        stop_process()
        process.wait()
        reader.join(timeout=1)
        if writer:
            writer.join(timeout=1)
        raise

    reader.join(timeout=1)
    if writer:
        writer.join(timeout=1)
    with lock:
        collecting = False
        output_bytes = bytes(captured)
        output_omitted = omitted
    output = output_bytes.decode("utf-8", errors="replace")
    if output_omitted:
        output += f"\n… [output truncated; characters omitted]"
    return CappedProcessResult(process.returncode, output, timed_out)
