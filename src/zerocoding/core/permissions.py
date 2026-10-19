"""Approval modes for tool actions: ask (default), auto (safe command packs) and yolo (everything).

The mode lives in memory for the current session only. It never overrides the command policy
(deny list), workspace scoping or Plan mode, which are enforced by the tool executor.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command_packs import DEFAULT_PACKS, PACKS, evaluate, leaves_workspace, needs_explicit_approval

MODES = ("ask", "auto", "yolo")
MODE_SUMMARY = {
    "ask": "Ask before every write, edit and command",
    "auto": "Auto-approve safe commands from the packs; ask for everything else",
    "yolo": "Approve writes, edits and commands without asking, except commands that may leave the project, use the network or install code, and commits",
}


@dataclass(frozen=True)
class Decision:
    note: str  # shown in the transcript, e.g. "auto · fs pack"


class PermissionPolicy:
    def __init__(self, root, mode: str = "ask", packs=DEFAULT_PACKS):
        self.root = Path(root)
        self.mode = mode if mode in MODES else "ask"
        self.packs = tuple(p for p in packs if p in PACKS) or DEFAULT_PACKS

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown permission mode: {mode}")
        self.mode = mode

    def decide(self, action: str, preview: str) -> Decision | None:
        """Return a Decision when the action is approved without asking, otherwise None (ask the user)."""
        if action == "Run verification":
            action = "Run command"  # same rules as any command: packs in auto, workspace and network checks in yolo
        if action == "Git commit":
            return None  # the repository's hooks run on commit, so a person always confirms it
        if self.mode == "yolo":
            # Even yolo keeps commands inside the project, and asks about network, installs and history rewrites.
            if action == "Run command" and (leaves_workspace(preview, self.root) or needs_explicit_approval(preview)):
                return None
            return Decision("yolo")
        if self.mode == "auto" and action == "Run command":
            verdict = evaluate(preview, self.root, self.packs)
            if verdict.allowed:
                return Decision(f"auto · {verdict.pack} pack")
        return None
