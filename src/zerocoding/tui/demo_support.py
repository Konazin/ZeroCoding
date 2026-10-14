"""Shared, provider-free UI fixtures for the M1 stack prototypes."""
from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from zerocoding import __version__
from .history import ProjectPromptHistory, project_history_path


PURPLE = "#A78BFA"
PURPLE_LIGHT = "#C4B5FD"
GRAY = "#9CA3AF"
LIGHT = "#F4F4F5"
GREEN = "#86EFAC"
RED = "#FCA5A5"
YELLOW = "#FDE68A"
USER_BG = "#211827"

WORK_PHRASES = (
    "Untangling the code…",
    "Checking the moving parts…",
    "Connecting a few dots…",
    "Sorting through the details…",
    "Giving the pieces a closer look…",
)

DEMO_HINTS = (
    "Try /demo tool to see compact tool activity.",
    "Try /demo approval to inspect an approval card.",
    "Try /demo error to view an error state.",
    "Type /help to see the prototype controls.",
)

DEMO_COMMANDS = (
    ("/help", "Show prototype controls"),
    ("/demo ask", "Show a normal response"),
    ("/demo tool", "Show read and search activity"),
    ("/demo approval", "Show an approval card"),
    ("/demo error", "Show an error state"),
    ("/clear", "Clear the transcript"),
    ("/quit", "Exit the prototype"),
)

ASCII_GHOST = (
    ("  .---.", " / o o \\", "|   ^  |", " \\_---/"),
    ("  .---.", " / o o \\", "|  ^   |", " \\---_/"),
)

PIXEL_GHOST = (
    ("  ▄██▄", " ▟█o o█▙", " █  ^ █▙", "  ▀█▄▄▀"),
    ("  ▄██▄", " ▟█o o█▙", " ▙█ ^  █", "  ▀█▄▄▀"),
)

COMPACT_GHOST = (
    ("(o o)", " /_\\"),
    ("(o o)", " \\_ /"),
)
ASCII_SPARKLES = ("*", ".", "+", ".")
UNICODE_SPARKLES = ("✦", "✧", "✣", "✧")


def random_work_phrase() -> str:
    return random.choice(WORK_PHRASES)


def random_hint() -> str:
    return random.choice(DEMO_HINTS)


@dataclass
class DemoMessage:
    kind: str
    text: str
    target: str = ""
    result: str = ""


class DemoConversation:
    """State machine for the same canned scenarios in both UI stacks."""

    def __init__(self) -> None:
        self.messages: list[DemoMessage] = []
        self.status = "Ready"
        self.status_kind = "idle"
        self.pending_approval = False
        self.approval_index = 0
        self.last_duration = ""
        self.hint = random_hint()

    @property
    def approval_choice(self) -> str:
        return "Accept" if self.approval_index == 0 else "Reject"

    def clear(self) -> None:
        self.messages.clear()
        self.status = "Ready"
        self.status_kind = "idle"
        self.pending_approval = False
        self.approval_index = 0
        self.last_duration = ""

    def begin_work(self) -> None:
        self.status = random_work_phrase()
        self.status_kind = "working"

    def set_tool_activity(self, action: str, target: str) -> None:
        self.status = f"{action} {target}"
        self.status_kind = "working"

    def finish(self, duration: float) -> None:
        self.status = "Ready"
        self.status_kind = "success"
        self.last_duration = f"Worked for {duration:.1f}s"

    def submit(self, prompt: str) -> str:
        """Return a command result or ``scenario`` for a canned user turn."""
        command = prompt.strip().lower()
        if command in {"/quit", "/exit"}:
            return "quit"
        if command == "/clear":
            self.clear()
            return "clear"
        if command in {"/help", "/demo help"}:
            return "help"

        if command == "/demo approval":
            self.messages.append(DemoMessage("user", "Add a status indicator to the header."))
            self.pending_approval = True
            self.approval_index = 0
            self.status = "Approval required"
            self.status_kind = "approval"
            self.messages.append(
                DemoMessage(
                    "approval",
                    "Proposed change · src/zerocoding/tui/theme.py",
                    result="+ STATUS_COLOR = '#86EFAC'\n+ STATUS_LABEL = 'Ready'",
                )
            )
            return "approval"

        if command == "/demo error":
            self.messages.append(DemoMessage("user", "Read a file from the workspace."))
            self.status = "Could not read the requested file"
            self.status_kind = "error"
            self.messages.append(DemoMessage("error", "Permission denied while reading src/private.txt"))
            return "error"

        if command == "/demo tool":
            self.messages.append(DemoMessage("user", "Find where file approvals are handled."))
            return "tool"

        if command == "/demo ask":
            self.messages.append(DemoMessage("user", "Explain what happens before a file is written."))
            return "ask"

        if command.startswith("/demo"):
            self.messages.append(DemoMessage("error", f"Unknown prototype command: {prompt}"))
            self.status = "Unknown command"
            self.status_kind = "error"
            return "error"

        if command.startswith("/"):
            self.messages.append(DemoMessage("error", f"Unknown command: {prompt}"))
            self.status = "Unknown command"
            self.status_kind = "error"
            return "error"

        self.messages.append(DemoMessage("user", prompt))
        return "ask"

    def resolve_approval(self, accepted: bool) -> None:
        self.pending_approval = False
        if accepted:
            self.messages.append(DemoMessage("tool", "Write file", "src/zerocoding/tui/theme.py", "Accepted · 1 file proposed"))
            self.status = "Approved"
            self.status_kind = "success"
        else:
            self.messages.append(DemoMessage("tool", "Write file", "src/zerocoding/tui/theme.py", "Denied · no files changed"))
            self.status = "Declined"
            self.status_kind = "idle"

    def tool_scenario_events(self) -> list[DemoMessage]:
        return [
            DemoMessage("tool", "Read", "src/zerocoding/core/tools.py", "42 lines"),
            DemoMessage("tool", "Search", "approve", "3 matches"),
            DemoMessage("assistant", "File writes and commands request approval before execution."),
        ]

    def response_for(self, prompt: str) -> str:
        if "project" in prompt.lower():
            return "This prototype uses fixed sample data. It does not inspect the workspace or call a model."
        return "I would inspect the relevant files, summarize what I found, and ask before any proposed write or command."


@lru_cache(maxsize=4)
def workspace_branch(path: Path | None = None) -> str:
    """Return the current branch name without failing outside a Git checkout."""
    from subprocess import TimeoutExpired, run

    try:
        result = run(
            ["git", "branch", "--show-current"],
            cwd=path or Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def ghost_frame(frame: int, *, compact: bool = False, unicode: bool = True) -> tuple[str, ...]:
    if compact:
        return COMPACT_GHOST[frame % len(COMPACT_GHOST)]
    return (PIXEL_GHOST if unicode else ASCII_GHOST)[frame % 2]


def sparkle(frame: int, *, unicode: bool = True) -> str:
    return (UNICODE_SPARKLES if unicode else ASCII_SPARKLES)[frame % 4]

