"""Git as a first-class, hardened tool: read-only inspection and an approved, explicit-path commit.

Git can run repository-controlled code (fsmonitor, pagers, textconv and external diff drivers, hooks), so
every call is built from a fixed argv, never through a shell, with those features switched off on the
command line (which overrides repository config) and a minimal environment. The model cannot pass raw
git options: it picks an action and a few typed arguments.
"""
from __future__ import annotations

import os
from pathlib import Path

from .command_policy import CommandPolicy
from .process import run_capped

READ_ACTIONS = ("status", "diff", "log")
GIT_TIMEOUT = 20
MAX_COMMIT_PATHS = 50
MAX_MESSAGE_CHARS = 2000

# Global options placed before the subcommand. `-c` here wins over .git/config and ~/.gitconfig.
HARDENING = (
    "--no-pager", "--no-optional-locks",
    "-c", "core.fsmonitor=false",
    "-c", "core.pager=cat",
    "-c", "core.quotepath=false",
    "-c", "color.ui=never",
    "-c", "core.hooksPath=/dev/null",  # read-only calls never run hooks; commit overrides this explicitly
)
# Same options minus the hooksPath override: a commit runs the repository's own hooks (that is why it is
# approved explicitly and never auto-approved).
COMMIT_HARDENING = tuple(HARDENING[:-2])
READ_FLAGS = ("--no-ext-diff", "--no-textconv", "--no-color")


def git_environment(policy: CommandPolicy) -> dict[str, str]:
    env = dict(policy.environment())
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
    })
    env.pop("GIT_EXTERNAL_DIFF", None)
    return env


def _run(root: Path, policy: CommandPolicy, args: list[str], *, hardening=HARDENING, max_chars: int | None = None,
         timeout: int = GIT_TIMEOUT):
    argv = ["git", *hardening, *args]
    return run_capped(argv, cwd=root, env=git_environment(policy), timeout=timeout,
                      max_output_chars=max_chars or policy.max_output_chars)


def is_git_repo(root: Path, policy: CommandPolicy | None = None) -> bool:
    """True when `root` is inside a git work tree and the git binary is available."""
    try:
        result = _run(root, policy or CommandPolicy(), ["rev-parse", "--is-inside-work-tree"], max_chars=64, timeout=5)
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and result.output.strip() == "true"


def read(root: Path, policy: CommandPolicy, args: dict, resolve_path) -> str:
    """Run one of the read-only actions. `resolve_path` is ToolRegistry._path (workspace scoping)."""
    action = str(args.get("action", "")).strip().lower()
    if action not in READ_ACTIONS:
        raise ValueError(f"Unknown git action '{action}'. Available actions: {', '.join(READ_ACTIONS)}")
    raw_path = args.get("path")
    pathspec = "."
    if raw_path not in (None, "", "."):
        pathspec = resolve_path(str(raw_path)).relative_to(root).as_posix() or "."
    if action == "status":
        git_args = ["status", "--short", "--branch", "--", pathspec]
    elif action == "diff":
        git_args = ["diff", *READ_FLAGS, "--unified=3"]
        if _truthy(args.get("staged")):
            git_args.append("--cached")
        git_args += ["--", pathspec]
    else:
        limit = _bounded_int(args.get("limit"), 10, 1, 50)
        git_args = ["log", *READ_FLAGS, "--oneline", "--decorate=short", "-n", str(limit)]
        if pathspec != ".":
            git_args += ["--", pathspec]
    try:
        result = _run(root, policy, git_args)
    except FileNotFoundError:
        raise ValueError("git is not installed or not on PATH") from None
    text = result.output.strip()
    if result.timed_out:
        return f"git {action} timed out after {GIT_TIMEOUT}s and was stopped."
    if result.returncode != 0:
        return f"git {action} failed (exit {result.returncode}): {text or 'no output'}"
    if len(text) >= policy.max_output_chars - 1:
        text += "\n[output truncated: pass a narrower path or a smaller limit]"
    return text or {"status": "Working tree clean.", "diff": "No changes.", "log": "No commits."}[action]


def prepare_commit(root: Path, policy: CommandPolicy, args: dict, resolve_path) -> tuple[list[str], str, str]:
    """Validate a commit request and build the approval preview. Returns (relative paths, message, preview)."""
    message = str(args.get("message", "")).strip()
    if not message:
        raise ValueError("message must not be empty")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message is too long (limit: {MAX_MESSAGE_CHARS} characters)")
    raw_paths = args.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths or not all(isinstance(p, str) and p.strip() for p in raw_paths):
        raise ValueError("paths must be a non-empty list of file paths; commit never stages everything implicitly")
    if len(raw_paths) > MAX_COMMIT_PATHS:
        raise ValueError(f"too many paths (limit: {MAX_COMMIT_PATHS})")
    paths = []
    for value in raw_paths:
        relative = resolve_path(value).relative_to(root).as_posix()
        if relative in ("", "."):
            raise ValueError("commit a list of files, not the whole project directory")
        if relative not in paths:
            paths.append(relative)
    status = _run(root, policy, ["status", "--short", "--", *paths], max_chars=4000)
    stat = _run(root, policy, ["diff", *READ_FLAGS, "--stat", "HEAD", "--", *paths], max_chars=4000)
    if status.returncode != 0:
        raise ValueError(f"git status failed: {status.output.strip()[:300]}")
    if not status.output.strip():
        raise ValueError("None of the listed paths has changes to commit.")
    preview = "\n".join([
        f"Commit message:\n  {message}",
        "",
        "Files:",
        status.output.rstrip(),
        "",
        (stat.output.rstrip() if stat.returncode == 0 and stat.output.strip() else "(no tracked diff to summarize)"),
        "",
        "The repository's own commit hooks will run. Nothing is pushed.",
    ])
    return paths, message, preview


def commit(root: Path, policy: CommandPolicy, paths: list[str], message: str) -> str:
    """Stage exactly `paths` and commit only them (other staged changes stay staged). Hooks run; no --no-verify."""
    hardening = COMMIT_HARDENING
    added = _run(root, policy, ["add", "--", *paths], hardening=hardening, max_chars=2000)
    if added.returncode != 0:
        return f"git add failed (exit {added.returncode}): {added.output.strip()[:500]}. Nothing was committed."
    done = _run(root, policy, ["commit", "--only", "-m", message, "--", *paths], hardening=hardening,
                max_chars=4000, timeout=120)
    if done.timed_out:
        return "git commit timed out and was stopped."
    text = done.output.strip()
    if done.returncode != 0:
        return f"git commit failed (exit {done.returncode}): {text[:800]}"
    return f"Committed {len(paths)} file(s).\n{text[:600]}"


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim"}
    return bool(value)


def _bounded_int(value, default: int, low: int, high: int) -> int:
    try:
        return min(high, max(low, int(value)))
    except (TypeError, ValueError):
        return default
