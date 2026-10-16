"""User-defined hooks around tool calls (M6.1): zero prompt cost, deterministic, run under CommandPolicy.

Hooks come from the user's own configuration (never from the model). A blocking ``pre_tool`` hook can refuse
a tool call, but no hook can approve anything: user approval of writes and commands is unaffected.
"""
from __future__ import annotations

import fnmatch
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .command_policy import CommandPolicy

EVENTS = ("pre_tool", "post_tool", "turn_end")
OUTPUT_LIMIT = 800
STDIN_VALUE_LIMIT = 1000


@dataclass(frozen=True)
class Hook:
    event: str
    command: str
    match: tuple = ("*",)  # tool-name globs
    path: str = ""         # optional glob over the tool target (file path, pattern or command)
    blocking: bool = False  # pre_tool only: failure refuses the call
    timeout: int = 30
    name: str = ""
    source: str = "config"

    def applies(self, tool_name: str, target: str) -> bool:
        if not any(fnmatch.fnmatch(tool_name, pattern) for pattern in self.match):
            return False
        return not self.path or fnmatch.fnmatch(target, self.path)


def parse_hooks(entries, source: str = "config") -> tuple[list[Hook], list[str]]:
    """Validate raw YAML entries. Invalid entries are skipped and reported, never raised."""
    hooks, errors = [], []
    for index, raw in enumerate(entries or []):
        label = f"{source} hook #{index + 1}"
        if not isinstance(raw, dict):
            errors.append(f"{label}: must be a mapping")
            continue
        event, command = str(raw.get("event", "")), str(raw.get("command", "")).strip()
        if event not in EVENTS:
            errors.append(f"{label}: event must be one of {', '.join(EVENTS)}")
            continue
        if not command:
            errors.append(f"{label}: command is required")
            continue
        match = raw.get("match", "*")
        match = tuple(str(m) for m in (match if isinstance(match, list) else [match])) or ("*",)
        try:
            timeout = max(1, min(300, int(raw.get("timeout", 30))))
        except (TypeError, ValueError):
            errors.append(f"{label}: timeout must be an integer")
            continue
        hooks.append(Hook(event=event, command=command, match=match, path=str(raw.get("path", "")),
                          blocking=bool(raw.get("blocking", False)) and event == "pre_tool",
                          timeout=timeout, name=str(raw.get("name") or f"{source}-{index + 1}"), source=source))
    return hooks, errors


class HookRunner:
    def __init__(self, hooks: list[Hook], root: str | Path, policy: CommandPolicy | None = None, errors=None):
        self.hooks = list(hooks)
        self.root = Path(root).resolve()
        self.policy = policy or CommandPolicy()
        self.errors = list(errors or [])
        self.last_failures: list[str] = []  # non-blocking failures, for /hooks

    def _run(self, hook: Hook, tool_name: str, target: str, arguments: dict) -> tuple[bool, str]:
        """Return (succeeded, output). Never raises."""
        try:
            argv = shlex.split(hook.command)
        except ValueError as exc:
            return False, f"could not parse command: {exc}"
        reason = self.policy.check(argv, self.root)
        if reason:
            return False, f"blocked by command policy: {reason}"
        payload = json.dumps({
            "event": hook.event, "tool": tool_name, "target": target,
            "arguments": {k: (str(v)[:STDIN_VALUE_LIMIT]) for k, v in (arguments or {}).items()},
        })
        env = {**self.policy.environment(), "ZC_HOOK_EVENT": hook.event, "ZC_TOOL_NAME": tool_name, "ZC_TOOL_TARGET": target}
        try:
            result = subprocess.run(argv, cwd=self.root, input=payload, capture_output=True, text=True,
                                    timeout=hook.timeout, shell=False, env=env)
        except subprocess.TimeoutExpired:
            return False, f"timed out after {hook.timeout}s"
        except FileNotFoundError:
            return False, f"command not found: {argv[0]}"
        except OSError as exc:
            return False, f"could not start: {exc}"
        output = (result.stdout + result.stderr).strip()
        if len(output) > OUTPUT_LIMIT:
            output = output[:OUTPUT_LIMIT] + "…"
        return result.returncode == 0, (output if result.returncode == 0 else f"exit {result.returncode}: {output}".rstrip(": "))

    def _matching(self, event: str, tool_name: str, target: str):
        return [h for h in self.hooks if h.event == event and h.applies(tool_name, target)]

    def pre_tool(self, tool_name: str, target: str, arguments: dict) -> str | None:
        """Return a refusal message if a blocking hook refuses the call, otherwise None."""
        for hook in self._matching("pre_tool", tool_name, target):
            ok, output = self._run(hook, tool_name, target, arguments)
            if ok:
                continue
            if hook.blocking:
                detail = f": {output}" if output else ""
                return f"Blocked by hook '{hook.name}'{detail}. Nothing was executed."
            self.last_failures.append(f"{hook.name}: {output}")
        return None

    def post_tool(self, tool_name: str, target: str, arguments: dict) -> str | None:
        """Run post hooks after a tool executed. Only failures are reported (to keep the prompt small)."""
        notes = []
        for hook in self._matching("post_tool", tool_name, target):
            ok, output = self._run(hook, tool_name, target, arguments)
            if not ok:
                notes.append(f"[hook '{hook.name}' failed — {output}]")
        return "\n".join(notes) or None

    def turn_end(self, outcome: str) -> None:
        for hook in self._matching("turn_end", "", ""):
            ok, output = self._run(hook, "", outcome, {})
            if not ok:
                self.last_failures.append(f"{hook.name}: {output}")

    def describe(self) -> list[str]:
        lines = []
        for hook in self.hooks:
            flags = " blocking" if hook.blocking else ""
            scope = ",".join(hook.match) + (f" path={hook.path}" if hook.path else "")
            lines.append(f"{hook.name} [{hook.source}] {hook.event}{flags} match={scope} → {hook.command}")
        return lines
