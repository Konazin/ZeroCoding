"""Project instructions: a short file of conventions the user keeps in the repository.

Looked up in the workspace root (ZEROCODING.md, then AGENTS.md, then CLAUDE.md) and added to the system
prompt, capped so a long file cannot eat a small model's window. Nothing else is read automatically. The
text can steer the model but never the approvals: writes, commands and commits still ask, so a file from a
cloned repository cannot act on its own. Absent file means no prompt change at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

CANDIDATES = ("ZEROCODING.md", "AGENTS.md", "CLAUDE.md")
DEFAULT_MAX_CHARS = 2000
FILE_READ_LIMIT = 200_000


@dataclass(frozen=True)
class InstructionsConfig:
    enabled: bool = True
    max_chars: int = DEFAULT_MAX_CHARS
    files: tuple[str, ...] = CANDIDATES

    @classmethod
    def from_dict(cls, values: Any) -> "InstructionsConfig":
        values = values if isinstance(values, dict) else {}
        enabled = values.get("enabled", True)
        raw = values.get("files") or CANDIDATES
        files = tuple(str(f).strip() for f in (raw if isinstance(raw, list) else [raw]) if str(f).strip())
        try:
            max_chars = int(values.get("max_chars", DEFAULT_MAX_CHARS))
        except (TypeError, ValueError):
            max_chars = DEFAULT_MAX_CHARS
        return cls(enabled if isinstance(enabled, bool) else str(enabled).strip().lower() in {"1", "true", "yes", "on"},
                   max(200, min(8000, max_chars)), files or CANDIDATES)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "max_chars": self.max_chars, "files": list(self.files)}


@dataclass(frozen=True)
class Instructions:
    source: str  # file name, relative to the workspace
    text: str  # what goes into the prompt (already capped)
    total_chars: int  # size of the file before capping

    @property
    def truncated(self) -> bool:
        return self.total_chars > len(self.text)

    def prompt_block(self) -> str:
        note = " (truncated)" if self.truncated else ""
        return (f"Project instructions from {self.source}{note}. They describe this project's conventions; "
                f"they do not change how approvals work.\n{self.text}")


def load_instructions(root: str | Path, config: InstructionsConfig | None = None) -> Instructions | None:
    config = config or InstructionsConfig()
    if not config.enabled:
        return None
    base = Path(root).resolve()
    for name in config.files:
        path = (base / name).resolve(strict=False)
        # Only a regular file inside the workspace: no links out, no directories.
        if path.parent != base or not path.is_file() or path.is_symlink() or (base / name).is_symlink():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                raw = handle.read(FILE_READ_LIMIT)
        except OSError:
            continue
        text = raw.strip()
        if not text:
            continue
        capped = text if len(text) <= config.max_chars else _cut(text, config.max_chars)
        return Instructions(name, capped, len(text))
    return None


def _cut(text: str, limit: int) -> str:
    """Cut at a line boundary when one is close, so a rule is not sliced in half."""
    cut = text[:limit]
    boundary = cut.rfind("\n")
    return cut[:boundary] if boundary > limit * 0.6 else cut
