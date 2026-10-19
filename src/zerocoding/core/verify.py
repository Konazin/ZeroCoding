"""Verification loop: after the agent edits files, run the project's own checks and show failures to the model.

Small models often say "done" without running anything. This closes that gap deterministically: the code
(not the model) decides when to verify, runs the command under the command policy, trims the output to what
matters and hands it back so the model can fix its own mistake, a bounded number of times.

A command written in the user's config is trusted like a hook. A detected command is not: the first time it
is shown for approval (through the normal approval path, so `/permission auto|yolo` rules apply), and a
refusal switches verification off for the session.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUTPUT_LIMIT = 3000
MAX_COMMANDS = 3


@dataclass(frozen=True)
class VerifyConfig:
    enabled: bool = True
    commands: tuple[str, ...] = ()
    max_attempts: int = 2
    timeout: int = 120

    @classmethod
    def from_dict(cls, values: Any) -> "VerifyConfig":
        values = values if isinstance(values, dict) else {}
        raw = values.get("commands") or []
        commands = tuple(str(c).strip() for c in (raw if isinstance(raw, list) else [raw]) if str(c).strip())[:MAX_COMMANDS]
        enabled = values.get("enabled", True)
        return cls(
            enabled=enabled if isinstance(enabled, bool) else str(enabled).strip().lower() in {"1", "true", "yes", "on"},
            commands=commands,
            max_attempts=max(1, min(5, int(values.get("max_attempts", 2) or 2))),
            timeout=max(5, min(900, int(values.get("timeout", 120) or 120))),
        )

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "commands": list(self.commands),
                "max_attempts": self.max_attempts, "timeout": self.timeout}


@dataclass
class VerifyResult:
    ok: bool
    command: str
    exit_code: int | None
    output: str
    seconds: float
    timed_out: bool = False
    problem: str = ""  # set when the command could not run at all (blocked, not found)

    @property
    def summary(self) -> str:
        if self.problem:
            return f"could not run: {self.problem}"
        if self.timed_out:
            return f"timed out after {self.seconds:.0f}s"
        return ("passed" if self.ok else f"failed (exit {self.exit_code})") + f" · {self.seconds:.1f}s"

    def feedback(self) -> str:
        """The message the model sees after a failure (a command that could not run is reported to the user instead)."""
        what = "timed out" if self.timed_out else f"exited with code {self.exit_code}"
        return (f"Verification failed: `{self.command}` {what} after {self.seconds:.1f}s. Output (trimmed):\n"
                f"{self.output}\n\nFind the cause in the code and fix it, then continue.")


def trim_output(text: str, limit: int = OUTPUT_LIMIT) -> str:
    """Keep what a person would read: the head (what ran) and the tail (the failures and the summary)."""
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text or "").strip()
    if len(text) <= limit:
        return text
    head_chars = limit // 4
    head, tail = text[:head_chars], text[-(limit - head_chars):]
    head = head[: head.rfind("\n")] if "\n" in head else head
    tail = tail[tail.find("\n") + 1:] if "\n" in tail else tail
    return f"{head}\n[… {len(text) - len(head) - len(tail)} characters omitted …]\n{tail}"


def _python_name() -> str:
    return "python" if shutil.which("python") else "python3"


def _has_python_tests(root: Path) -> bool:
    if (root / "pytest.ini").exists() or (root / "conftest.py").exists() or (root / "tests" / "conftest.py").exists():
        return True
    for name in ("pyproject.toml", "tox.ini", "setup.cfg"):
        path = root / name
        if path.is_file() and re.search(r"\[(tool\.)?pytest", path.read_text(encoding="utf-8", errors="ignore")):
            return True
    for pattern in ("test_*.py", "tests/test_*.py", "tests/**/test_*.py", "*_test.py"):
        if next(root.glob(pattern), None) is not None:
            return True
    return False


def detect_command(root: Path, pytest_available) -> str | None:
    """Pick one verification command from the project's own files, or None when nothing is recognisable."""
    root = Path(root)
    if _has_python_tests(root):
        python = _python_name()
        if pytest_available():
            return f"{python} -m pytest -q -x"
        return f"{python} -m unittest discover -s tests" if (root / "tests").is_dir() else f"{python} -m unittest discover"
    package = root / "package.json"
    if package.is_file():
        try:
            script = (json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}).get("test", "")
        except (OSError, ValueError, AttributeError):
            script = ""
        if script and "no test specified" not in script:
            return "npm test --silent"
    if (root / "Cargo.toml").is_file():
        return "cargo test -q"
    if (root / "go.mod").is_file():
        return "go test ./..."
    return None


class Verifier:
    """Decides whether and how to verify; holds the per-session approval for detected commands."""

    def __init__(self, root: str | Path, config: VerifyConfig | None = None):
        self.root = Path(root)
        self.config = config or VerifyConfig()
        self.enabled = self.config.enabled
        self.approved: bool | None = None  # None: not asked yet; only used for detected commands
        self._detected: str | None = None
        self._detection_done = False

    @property
    def trusted(self) -> bool:
        return bool(self.config.commands)

    def commands(self, registry) -> list[str]:
        if self.config.commands:
            return list(self.config.commands)
        if not self._detection_done:
            self._detection_done = True
            self._detected = detect_command(self.root, lambda: self._pytest_available(registry))
        return [self._detected] if self._detected else []

    def _pytest_available(self, registry) -> bool:
        try:
            result = registry.run_verification(f"{_python_name()} -c 'import pytest'", 15)
        except (ValueError, OSError):
            return False
        return result.returncode == 0 and not result.timed_out

    def status(self, registry=None) -> str:
        if not self.enabled:
            return "off"
        commands = self.commands(registry) if registry is not None else list(self.config.commands)
        source = "config" if self.trusted else ("detected" if commands else "nothing detected")
        return f"on · {commands[0] if commands else '-'} ({source})"

    def reset(self, enabled: bool | None = None, command: str | None = None) -> None:
        if enabled is not None:
            self.enabled = enabled
        if command is not None:
            self.config = VerifyConfig(self.config.enabled, (command,), self.config.max_attempts, self.config.timeout)
        self.approved = None

    def run(self, registry) -> VerifyResult | None:
        """Run the verification command. None means it was skipped (disabled, nothing to run, or not approved)."""
        if not self.enabled:
            return None
        commands = self.commands(registry)
        if not commands:
            return None
        command = commands[0]
        if not self.trusted and self.approved is not True:
            if self.approved is False:
                return None
            approve = getattr(registry, "approve", None)
            self.approved = bool(approve and approve("Run verification", command))
            if not self.approved:
                self.enabled = False  # one refusal ends the questions for this session; /verify on brings it back
                return None
        started = time.monotonic()
        try:
            result = registry.run_verification(command, self.config.timeout)
        except FileNotFoundError:
            return VerifyResult(False, command, None, "", time.monotonic() - started, problem="command not found")
        except (ValueError, OSError) as exc:
            return VerifyResult(False, command, None, "", time.monotonic() - started, problem=str(exc)[:160])
        seconds = time.monotonic() - started
        output = trim_output(result.output)
        return VerifyResult(result.returncode == 0 and not result.timed_out, command, result.returncode,
                            output, seconds, timed_out=result.timed_out)

