"""Per-turn journal of the files the agent wrote, so a whole turn can be undone.

Only `write_file` and `edit_file` are journaled: they are exact (the tool knows the original bytes), they
work without git, and the user already approves each of them. Changes made by commands (`run_command`)
are not tracked, and `/undo` says so. An undo refuses to run if a journaled file was changed by anything
else after the agent wrote it, so it can never overwrite the user's own edits.

Entries live in memory and, when persistence is on, in `~/.zerocoding/journal/<session-id>/` (0700/0600,
atomic writes), because they hold file contents.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_TURNS = 20
JOURNAL_VERSION = 1
_TURN_FILE = re.compile(r"^turn-(\d{6})\.json$")


def _sha(data: bytes | None) -> str:
    return hashlib.sha256(data).hexdigest() if data is not None else ""


@dataclass
class Entry:
    path: str  # workspace-relative, posix
    before: bytes | None  # None: the agent created the file
    after_sha: str


@dataclass
class Turn:
    id: int
    label: str
    entries: dict[str, Entry] = field(default_factory=dict)


@dataclass
class UndoAction:
    path: str
    kind: str  # "restore" or "delete"
    diff: str


@dataclass
class UndoPlan:
    turn: Turn
    actions: list[UndoAction]
    conflicts: list[str]

    @property
    def preview(self) -> str:
        parts = [f"Undo turn {self.turn.id}: {self.turn.label}"]
        for action in self.actions:
            parts.append(f"\n{'Delete' if action.kind == 'delete' else 'Restore'} {action.path}")
            parts.append(action.diff)
        parts.append("\nChanges made by commands (run_command) are not undone.")
        return "\n".join(parts).strip()


class FileJournal:
    def __init__(self, root: str | Path, directory: str | Path | None = None):
        self.root = Path(root).resolve()
        self.directory = Path(directory) if directory is not None else None
        self._turns: list[Turn] = []
        self._current: Turn | None = None
        self._next_id = 1
        if self.directory is not None:
            self._load()

    # ------------------------------------------------------------------ recording
    def begin_turn(self, label: str) -> None:
        label = " ".join(str(label).split())[:60] or "turn"
        self._current = Turn(self._next_id, label)

    def record(self, relative_path: str, before: bytes | None, after: bytes) -> None:
        """Remember the original of a file the agent just wrote (first write of a turn wins)."""
        if self._current is None:
            self.begin_turn("changes outside a turn")
        turn = self._current
        existing = turn.entries.get(relative_path)
        if existing is None:
            turn.entries[relative_path] = Entry(relative_path, before, _sha(after))
        else:
            existing.after_sha = _sha(after)
        if turn not in self._turns:
            self._turns.append(turn)
            self._next_id = turn.id + 1
            self._prune()
        self._save(turn)

    # ------------------------------------------------------------------ querying
    def turns(self) -> list[Turn]:
        """Journaled turns, newest first."""
        return [t for t in reversed(self._turns) if t.entries]

    def latest(self) -> Turn | None:
        turns = self.turns()
        return turns[0] if turns else None

    def get(self, turn_id: int) -> Turn | None:
        return next((t for t in self._turns if t.id == turn_id and t.entries), None)

    # ------------------------------------------------------------------ undo
    def plan_undo(self, turn: Turn) -> UndoPlan:
        actions, conflicts = [], []
        for entry in turn.entries.values():
            target = self._resolve(entry.path)
            current = target.read_bytes() if target.is_file() else None
            if _sha(current) != entry.after_sha:
                conflicts.append(entry.path)
                continue
            if entry.before is None:
                actions.append(UndoAction(entry.path, "delete", self._diff(entry.path, current, None)))
            else:
                actions.append(UndoAction(entry.path, "restore", self._diff(entry.path, current, entry.before)))
        return UndoPlan(turn, actions, conflicts)

    def apply(self, plan: UndoPlan) -> int:
        """Restore the planned files atomically. Refuses when anything changed since the plan was made."""
        if plan.conflicts:
            raise ValueError("Files changed after the agent wrote them: " + ", ".join(plan.conflicts))
        fresh = self.plan_undo(plan.turn)
        if fresh.conflicts:
            raise ValueError("Files changed while the undo was being confirmed: " + ", ".join(fresh.conflicts))
        done = 0
        for action in fresh.actions:
            entry = plan.turn.entries[action.path]
            target = self._resolve(entry.path)
            if entry.before is None:
                target.unlink(missing_ok=True)
            else:
                self._atomic_restore(target, entry.before)
            done += 1
        self._drop(plan.turn)
        return done

    # ------------------------------------------------------------------ internals
    def _resolve(self, relative: str) -> Path:
        target = (self.root / relative).resolve(strict=False)
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Journal path escapes the workspace: {relative}")
        return target

    @staticmethod
    def _diff(path: str, current: bytes | None, wanted: bytes | None) -> str:
        def text(data):
            return [] if data is None else data.decode("utf-8", errors="replace").splitlines(True)
        diff = "".join(difflib.unified_diff(text(current), text(wanted), fromfile=path, tofile=path))
        return diff or "(no textual change)"

    @staticmethod
    def _atomic_restore(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.zerocoding-undo-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(temporary, mode)
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _prune(self) -> None:
        while len(self._turns) > MAX_TURNS:
            self._drop(self._turns[0])

    def _drop(self, turn: Turn) -> None:
        if turn in self._turns:
            self._turns.remove(turn)
        if self.directory is not None:
            try:
                (self.directory / f"turn-{turn.id:06d}.json").unlink()
            except OSError:
                pass

    def _save(self, turn: Turn) -> None:
        if self.directory is None:
            return
        payload = {
            "version": JOURNAL_VERSION, "id": turn.id, "label": turn.label,
            "entries": [{"path": e.path, "existed": e.before is not None,
                         "before": base64.b64encode(e.before).decode("ascii") if e.before is not None else "",
                         "after_sha": e.after_sha} for e in turn.entries.values()],
        }
        try:
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            os.chmod(self.directory, 0o700)
            fd, temporary = tempfile.mkstemp(prefix=".turn-", dir=self.directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.directory / f"turn-{turn.id:06d}.json")
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        except OSError:
            # The in-memory journal still works; a full disk must not break the agent's write.
            return

    def _load(self) -> None:
        try:
            names = sorted(name for name in os.listdir(self.directory) if _TURN_FILE.match(name))
        except OSError:
            return
        for name in names:
            try:
                data = json.loads((self.directory / name).read_text(encoding="utf-8"))
                turn = Turn(int(data["id"]), str(data["label"]))
                for item in data["entries"]:
                    before = base64.b64decode(item["before"]) if item["existed"] else None
                    turn.entries[item["path"]] = Entry(item["path"], before, str(item["after_sha"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # a damaged entry only loses that turn's undo
            self._turns.append(turn)
            self._next_id = max(self._next_id, turn.id + 1)


def journal_for(session_id: str, root: str | Path, *, persist: bool = True,
                home: str | Path | None = None) -> FileJournal:
    base = Path(home) if home is not None else Path.home() / ".zerocoding"
    directory = base / "journal" / session_id if persist else None
    return FileJournal(root, directory)
