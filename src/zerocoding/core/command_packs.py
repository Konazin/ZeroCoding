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


def leaves_workspace(command: str, root: Path) -> bool:
    """True when any argument could point outside the workspace (or the command cannot be parsed).

    Conservative on purpose: absolute paths, ``~``, ``..``, variables and symlinks that resolve
    elsewhere all count, including the value in ``--flag=value``.
    """
    try:
        argv = shlex.split(command.strip())
    except ValueError:
        return True
    root = Path(root).resolve()
    for token in argv:
        value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
        if value.startswith("-"):
            continue
        if value.startswith(("/", "~", "$")) or ".." in value.split("/") or "\x00" in value:
            if not _inside(value, root) or value.startswith(("~", "$")):
                return True
            continue
        if not _inside(value, root):  # a relative name that resolves outside, e.g. through a symlink
            return True
    return False


# Commands that reach the network, install code or rewrite history. They are asked even in yolo mode:
# the workspace check cannot tell that `git push` or `pip install` affects things outside the project.
NETWORK_EXECUTABLES = frozenset({"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "telnet", "ftp", "gh"})
INSTALLERS = frozenset({"pip", "pip3", "pipx", "npx", "conda", "apt", "apt-get", "brew", "dnf", "yum", "pacman", "snap", "flatpak"})
# Tools that also run project code (`npm test`, `cargo build`): only their fetch/install subcommands are asked.
MANAGER_SUBCOMMANDS = {
    name: frozenset({"install", "i", "add", "update", "upgrade", "publish", "remove", "uninstall", "get", "ci", "login",
                     "fetch", "dlx", "create", "init", "yank", "owner", "mod"})
    for name in ("npm", "yarn", "pnpm", "cargo", "gem", "bundle", "go", "poetry")
}
GIT_ALWAYS_ASK = frozenset({"push", "pull", "fetch", "clone", "remote", "submodule", "reset", "clean", "rebase",
                            "filter-branch", "gc", "prune", "reflog"})


def needs_explicit_approval(command: str) -> bool:
    """True for network, install and history-rewriting commands (and anything that cannot be parsed)."""
    try:
        argv = shlex.split(command.strip())
    except ValueError:
        return True
    if not argv:
        return False
    name = Path(argv[0]).name
    if name in NETWORK_EXECUTABLES or name in INSTALLERS:
        return True
    if name in MANAGER_SUBCOMMANDS:
        return any(a in MANAGER_SUBCOMMANDS[name] for a in argv[1:3])
    if name == "uv" and any(a in {"pip", "add", "sync", "tool", "install", "publish"} for a in argv[1:3]):
        return True
    if name in {"python", "python3"} and "-m" in argv:
        module = argv[argv.index("-m") + 1] if argv.index("-m") + 1 < len(argv) else ""
        return module in {"pip", "ensurepip", "venv"}
    if name == "git":
        rest = [a for a in argv[1:] if not a.startswith("-")]
        # `git -c key=val sub`: the value after -c is not a subcommand
        subcommand = next((a for a in argv[1:] if not a.startswith("-") and "=" not in a), "")
        return subcommand in GIT_ALWAYS_ASK or (bool(rest) and rest[0] in GIT_ALWAYS_ASK)
    return False
