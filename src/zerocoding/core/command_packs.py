"""Packs of terminal commands that auto mode may approve without asking.

Everything is decided by code, never by the model: the command is parsed the same way `run_command`
launches it (shlex, no shell), must be a bare executable name from an enabled pack, may only use that
command's allowed flags, and every path argument must stay inside the workspace. Anything else is
left to the user. Packs hold non-destructive commands only: no rm, mv, cp, chmod, pip, curl or sed.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_PACKS = ("fs", "read", "git")
SHELL_SYNTAX = re.compile(r"&&|\|\||[|;<>`\n]|\$\(|\$\{")
FLAG = re.compile(r"^-[A-Za-z0-9]+$|^--[a-z][a-z-]*(=\S*)?$")


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    pack: str = ""
    reason: str = ""


def _inside(token: str, root: Path) -> bool:
    if token.startswith("~") or "\x00" in token:
        return False
    resolved = (root / token).resolve(strict=False)
    return resolved == root or root in resolved.parents


def _split(argv: list[str]) -> tuple[list[str], list[str]]:
    flags = [a for a in argv if a.startswith("-") and a != "-"]
    return flags, [a for a in argv if not (a.startswith("-") and a != "-")]


def _flags_ok(flags: list[str], allowed_letters: str = "", allowed_long: Iterable[str] = (), banned: Iterable[str] = ()) -> bool:
    allowed_long = set(allowed_long)
    for flag in flags:
        name = flag.split("=", 1)[0]
        if not FLAG.match(flag) or name in set(banned):
            return False
        if flag.startswith("--"):
            if allowed_long and name not in allowed_long:
                return False
        elif allowed_letters and any(letter not in allowed_letters for letter in flag[1:]):
            return False
    return True


def _paths_ok(paths: list[str], root: Path) -> bool:
    return all(_inside(path, root) for path in paths)


def _mkdir(argv, root):
    flags, targets = _split(argv)
    return bool(targets) and _flags_ok(flags, "pv", {"--parents", "--verbose"}) and _paths_ok(targets, root)


def _touch(argv, root):
    flags, targets = _split(argv)
    return bool(targets) and not flags and _paths_ok(targets, root)


def _ls(argv, root):
    flags, targets = _split(argv)
    return _flags_ok(flags, "alhRtrSF1d", {"--all", "--almost-all", "--human-readable"}) and _paths_ok(targets, root)


def _pwd(argv, root):
    return not argv


def _simple_reader(letters, long_flags=()):
    def check(argv, root):
        flags, rest = _split(argv)
        paths = [a for a in rest if not a.lstrip("+").isdigit()]  # -n 20 / -c 100 values
        return _flags_ok(flags, letters, long_flags) and _paths_ok(paths, root)
    return check


def _grep_like(banned, letters):
    def check(argv, root):
        flags, rest = _split(argv)
        if not _flags_ok(flags, letters, banned=banned) or any(f.split("=", 1)[0] in banned for f in flags):
            return False
        explicit_pattern = any(f in {"-e", "-f"} or f.startswith("--regexp") for f in flags)
        paths = rest if explicit_pattern else rest[1:]
        return _paths_ok(paths, root)
    return check


FIND_BANNED = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}


def _find(argv, root):
    if any(token in FIND_BANNED for token in argv):
        return False
    paths = []
    for token in argv:
        if token.startswith("-") or token in {"(", ")", "!"}:
            break
        paths.append(token)
    return _paths_ok(paths, root)


GIT_READ = {"status", "diff", "log", "show", "rev-parse", "ls-files", "blame", "shortlog", "describe"}
GIT_BANNED_FLAGS = {"--output", "-o", "--ext-diff", "--textconv", "--open-files-in-pager", "-O", "--exec", "--upload-pack"}


def _git(argv, root):
    if not argv or argv[0].startswith("-"):
        return False  # global options such as -c or -C can run code or leave the workspace
    sub, rest = argv[0], argv[1:]
    flags, positional = _split(rest)
    if any(f.split("=", 1)[0] in GIT_BANNED_FLAGS for f in flags):
        return False
    if sub in GIT_READ:
        return _paths_ok([p for p in positional if (root / p).exists() or "/" in p or "." in p], root)
    if sub == "branch":
        return not positional and _flags_ok(flags, "avl", {"--list", "--all", "--verbose"})
    if sub == "remote":
        return not positional and flags in ([], ["-v"])
    if sub == "tag":
        return not positional and _flags_ok(flags, "l", {"--list"})
    return False


def _tests(argv, root):
    # python -m unittest|pytest ..., pytest ...; runs project code, so this pack is opt-in.
    return all(_inside(a, root) for a in argv if not a.startswith("-") and ("/" in a or a.endswith(".py")))


PACKS: dict[str, dict[str, Callable]] = {
    "fs": {"mkdir": _mkdir, "touch": _touch, "ls": _ls, "pwd": _pwd},
    "read": {
        "cat": _simple_reader("nAbs"), "head": _simple_reader("nc0123456789"), "tail": _simple_reader("nc0123456789"), "wc": _simple_reader("lwcm"),
        "file": _simple_reader("bi"), "stat": _simple_reader(""), "diff": _simple_reader("uq"),
        "grep": _grep_like({"--include-from"}, "inrvlcwFEeHhoA"), "rg": _grep_like({"--pre", "--pre-glob", "--hostname-bin"}, "inrvlcwFeHhoSsuj"),
        "find": _find,
    },
    "git": {"git": _git},
    "tests": {"pytest": _tests},
}
PACK_SUMMARY = {
    "fs": "mkdir, touch, ls, pwd inside the workspace",
    "read": "cat, head, tail, wc, file, stat, diff, grep, rg, find (no -exec/-delete) inside the workspace",
    "git": "git status, diff, log, show, branch, rev-parse, ls-files, blame (read only)",
    "tests": "pytest, python -m pytest|unittest (runs project code; off by default)",
}


def evaluate(command: str, root: Path, packs: Iterable[str] = DEFAULT_PACKS) -> Verdict:
    """Decide whether `command` belongs to an enabled pack. Never raises."""
    command = command.strip()
    if not command:
        return Verdict(False, reason="empty command")
    if SHELL_SYNTAX.search(command):
        return Verdict(False, reason="needs a shell")
    try:
        argv = shlex.split(command)
    except ValueError:
        return Verdict(False, reason="unparseable")
    if not argv or "/" in argv[0]:
        return Verdict(False, reason="not a bare command name")
    name, args, root = argv[0], argv[1:], Path(root).resolve()
    if name in {"python", "python3"}:
        if len(args) >= 2 and args[0] == "-m" and args[1] in {"pytest", "unittest"} and "tests" in set(packs):
            return Verdict(_tests(args[2:], root), "tests", "")
        return Verdict(False, reason="not in an enabled pack")
    for pack in packs:
        check = PACKS.get(pack, {}).get(name)
        if check is not None:
            allowed = bool(check(args, root))
            return Verdict(allowed, pack, "" if allowed else "arguments outside the pack's limits")
    return Verdict(False, reason="not in an enabled pack")
