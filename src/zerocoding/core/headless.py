"""Non-interactive runs (`zc run -m "task"`) for scripts and CI.

No human is there to approve anything, so the permissions are decided up front by flags and default to
read-only: without `--write` the agent runs in Plan mode. Writes and edits are approved only with
`--write`; commands only through the same code-checked packs as `/permission auto` (`--commands auto`);
commits, network and installs are never approved. The answer goes to stdout, progress to stderr, and
`--json` prints one machine-readable object.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .cancel import CancelToken, TurnCancelled
from .permissions import PermissionPolicy

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNVERIFIED = 2
EXIT_CANCELLED = 130
HEADLESS_PACKS = ("fs", "read", "git", "tests")


@dataclass
class HeadlessOptions:
    write: bool = False
    commands: str = "none"  # none | auto
    as_json: bool = False
    quiet: bool = False
    max_rounds: int | None = None


@dataclass
class HeadlessReport:
    answer: str = ""
    outcome: str = "error"
    files_changed: list[str] = field(default_factory=list)
    verified: bool | None = None
    stats: dict = field(default_factory=dict)
    duration_s: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        keep = ("llm_calls", "tool_calls", "tool_rounds", "tool_errors", "tool_denied", "prompt_tokens", "completion_tokens",
                "verify_runs", "verify_failures")
        return {"answer": self.answer, "outcome": self.outcome, "files_changed": self.files_changed,
                "verified": self.verified, "duration_s": round(self.duration_s, 2), "error": self.error,
                "stats": {key: self.stats.get(key, 0) for key in keep}}


def make_approver(root: Path, options: HeadlessOptions, denied: list):
    """The only approval logic in headless mode: explicit flags and code-checked command packs."""
    policy = PermissionPolicy(root, "auto", HEADLESS_PACKS) if options.commands == "auto" else None

    def approve(action: str, preview: str) -> bool:
        if action in ("Write file", "Edit file"):
            allowed = options.write
        elif action in ("Run command", "Run verification") and policy is not None:
            allowed = policy.decide("Run command", preview) is not None
        else:
            allowed = False  # commits, external tools and anything else are never approved without a person
        if not allowed:
            denied.append(f"{action}: {preview.splitlines()[0][:80] if preview else ''}")
        return allowed

    return approve


def run_headless(agent, task: str, root: Path, options: HeadlessOptions, out=None, err=None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    report = HeadlessReport()
    denied: list[str] = []
    changed: list[str] = []
    if agent.tools is not None:
        agent.tools.approve = make_approver(root, options, denied)
    agent.set_session_controls(plan_mode=not options.write, ultrathink=False)
    if options.max_rounds:
        agent.max_tool_rounds = max(1, min(100, int(options.max_rounds)))

    def on_event(event):
        kind, name, target = event.kind, event.tool_name, event.target
        if kind == "tool_completed" and name in ("write_file", "edit_file") and target and target not in changed:
            changed.append(target)
        if options.quiet:
            return
        if kind == "tool_started":
            print(f"● {name} {target}".rstrip(), file=err)
        elif kind in ("verify_passed", "verify_failed", "verify_skipped"):
            print(f"  ⎿ verify {event.summary or kind.split('_')[1]}", file=err)
        elif kind in ("tool_denied", "tool_error"):
            print(f"  ⎿ {event.summary or kind}", file=err)

    if not options.quiet:
        print(f"[zc run] writes {'allowed' if options.write else 'denied (read-only)'}; commands {options.commands}", file=err)
    started = time.monotonic()
    cancel = CancelToken()
    try:
        report.answer = agent.ask(task, use_tools=True, on_event=on_event, cancel=cancel)
        report.outcome = "ok"
    except (KeyboardInterrupt, TurnCancelled):
        report.outcome, report.error = "cancelled", "cancelled"
    except Exception as exc:  # the provider, the template, the budget: all become a clean error and an exit code
        report.error = str(exc)
    report.duration_s = time.monotonic() - started
    report.files_changed = changed
    report.stats = dict(agent.last_turn or {})
    verification = getattr(agent, "last_verification", None)
    report.verified = None if verification is None else bool(verification.ok)

    if options.as_json:
        payload = report.to_dict()
        payload["denied"] = denied
        print(json.dumps(payload, ensure_ascii=False), file=out)
    else:
        if report.answer:
            print(report.answer, file=out)
        if report.error and report.outcome != "ok":
            print(f"Error: {report.error}", file=err)
        if denied and not options.quiet:
            print(f"[zc run] {len(denied)} action(s) were not approved in headless mode (see --write / --commands auto)", file=err)
    if report.outcome == "cancelled":
        return EXIT_CANCELLED
    if report.outcome != "ok":
        return EXIT_ERROR
    return EXIT_UNVERIFIED if report.verified is False else EXIT_OK
