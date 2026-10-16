"""Policy for `run_command`: what may be launched, with which environment, timeout and output size."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DENY = frozenset({
    "sudo", "su", "doas", "mkfs", "dd", "shutdown", "reboot", "halt", "poweroff", "chown", "mount", "umount",
})
DEFAULT_ENV_PASSTHROUGH = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "VIRTUAL_ENV"})


@dataclass(frozen=True)
class CommandPolicy:
    deny: frozenset = DEFAULT_DENY
    allow: frozenset = frozenset()  # empty = any executable that is not denied
    env_passthrough: frozenset = DEFAULT_ENV_PASSTHROUGH
    timeout: int = 60
    max_output_chars: int = 8000

    @classmethod
    def from_dict(cls, values: dict[str, Any] | None) -> "CommandPolicy":
        values = values or {}
        return cls(
            deny=DEFAULT_DENY | frozenset(str(x) for x in values.get("deny") or []),
            allow=frozenset(str(x) for x in values.get("allow") or []),
            env_passthrough=DEFAULT_ENV_PASSTHROUGH | frozenset(str(x) for x in values.get("env_passthrough") or []),
            timeout=max(1, min(600, int(values.get("timeout", 60)))),
            max_output_chars=max(500, min(100_000, int(values.get("max_output_chars", 8000)))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deny": sorted(self.deny - DEFAULT_DENY),
            "allow": sorted(self.allow),
            "env_passthrough": sorted(self.env_passthrough - DEFAULT_ENV_PASSTHROUGH),
            "timeout": self.timeout,
            "max_output_chars": self.max_output_chars,
        }

    def environment(self) -> dict[str, str]:
        """Minimal environment: secrets such as API keys are not inherited unless listed."""
        return {key: value for key, value in os.environ.items() if key in self.env_passthrough}

    def check(self, argv: list[str], root: Path) -> str | None:
        """Return a reason when the command must not run, otherwise None."""
        if not argv:
            return "empty command"
        name = Path(argv[0]).name
        if name in self.deny:
            return f"'{name}' is not allowed"
        if self.allow and name not in self.allow:
            return f"'{name}' is not in the allowed list ({', '.join(sorted(self.allow))})"
        if name == "rm" and any(a.startswith("-") and ("r" in a.lower() or a == "--recursive") for a in argv[1:]):
            targets = [a for a in argv[1:] if not a.startswith("-")]
            for target in targets or ["."]:
                resolved = (root / Path(target).expanduser()).resolve(strict=False)
                if resolved == root or root not in resolved.parents:
                    return f"recursive rm of '{target}' is outside the allowed scope (inside the project, not the project root)"
        return None

    def truncate(self, output: str) -> str:
        if len(output) <= self.max_output_chars:
            return output
        omitted = len(output) - self.max_output_chars
        return output[: self.max_output_chars] + f"\n… [{omitted} characters omitted]"
