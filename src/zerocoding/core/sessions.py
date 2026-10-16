from __future__ import annotations

import errno
import json
import math
import os
import re
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SESSION_DIR = Path("~/.zerocoding/sessions").expanduser()
SESSION_SCHEMA_VERSION = 1
_SESSION_ID = re.compile(r"(?:[0-9a-f]{8}|[0-9a-f]{32})\Z")
_SESSION_ID_PREFIX = re.compile(r"[0-9a-f]{8,32}\Z")
_TEMP_SESSION_FILE = re.compile(r"\.(?:[0-9a-f]{8}|[0-9a-f]{32})-[A-Za-z0-9_-]+\.tmp\Z")
_STALE_TEMP_AGE_SECONDS = 24 * 60 * 60


def _string_field(data: dict[str, Any], name: str, default: str) -> str:
    value = data.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"Session field {name} must be a string.")
    return value


def _string_list_field(data: dict[str, Any], name: str) -> list[str]:
    value = data.get(name, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Session field {name} must be a list of strings.")
    return list(value)


def _object_list_field(data: dict[str, Any], name: str, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    value = data.get(name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Session field {name} must be a list of objects.")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in keys):
            fields = " and ".join(keys)
            raise ValueError(f"Session field {name}[{index}] must be an object with string {fields} fields.")
        result.append(dict(item))
    return result


def _boolean_field(data: dict[str, Any], name: str, default: bool = False) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"Session field {name} must be a boolean.")
    return value


def _timestamp_field(data: dict[str, Any], name: str, default: float) -> float:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Session field {name} must be a finite number.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"Session field {name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"Session field {name} must be a finite number.")
    return number


@dataclass
class Session:
    id: str
    provider: str
    model: str
    mode: str = "code"
    skills: list[str] = field(default_factory=list)
    path: str = "."
    history: list[dict[str, str]] = field(default_factory=list)
    context_files: list[dict[str, str]] = field(default_factory=list)
    plan_mode: bool = False
    ultrathink: bool = False
    effort: str = "medium"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def new(cls, provider: str, model: str, mode: str = "code", path: str = ".") -> "Session":
        return cls(id=uuid.uuid4().hex, provider=provider, model=model, mode=mode, path=path)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, legacy_timestamp: float = 0.0) -> "Session":
        version = data.get("schema_version", 0)
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError("Session schema_version must be a non-negative integer.")
        if version > SESSION_SCHEMA_VERSION:
            raise ValueError(
                f"Session schema version {version} is newer than supported version "
                f"{SESSION_SCHEMA_VERSION}. Update ZeroCoding before resuming it."
            )
        session_id = _string_field(data, "id", "")
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("Session field id must contain eight legacy or 32 lowercase hexadecimal digits.")
        effort = _string_field(data, "effort", "medium").lower()
        if effort not in {"low", "medium", "high"}:
            effort = "medium"
        created_at = _timestamp_field(data, "created_at", legacy_timestamp)
        return cls(
            id=session_id,
            provider=_string_field(data, "provider", ""),
            model=_string_field(data, "model", ""),
            mode=_string_field(data, "mode", "code"),
            skills=_string_list_field(data, "skills"),
            path=_string_field(data, "path", "."),
            history=_object_list_field(data, "history", ("role", "content")),
            context_files=_object_list_field(data, "context_files", ("path", "content")),
            plan_mode=_boolean_field(data, "plan_mode"),
            ultrathink=_boolean_field(data, "ultrathink"),
            effort=effort,
            created_at=created_at,
            updated_at=_timestamp_field(data, "updated_at", created_at),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "skills": list(self.skills),
            "path": self.path,
            "history": list(self.history),
            "context_files": list(self.context_files),
            "plan_mode": self.plan_mode,
            "ultrathink": self.ultrathink,
            "effort": self.effort,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionManager:
    def __init__(self, root: str | Path = DEFAULT_SESSION_DIR, *, persist: bool = True):
        self.root = Path(root).expanduser()
        self.persist = bool(persist)
        self._temporary_cleanup_done = False

    def create(self, provider: str, model: str, mode: str = "code", path: str = ".") -> Session:
        session = Session.new(provider=provider, model=model, mode=mode, path=path)
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        if not self.persist:
            session.updated_at = time.time()
            return
        if not isinstance(session, Session):
            raise ValueError("A Session instance is required.")
        if not isinstance(session.id, str) or not _SESSION_ID.fullmatch(session.id):
            raise ValueError("Session ID must be eight legacy hex digits or a 32-digit lowercase UUID.")
        if not isinstance(session.skills, list):
            raise ValueError("Session field skills must be a list of strings.")
        if not isinstance(session.history, list):
            raise ValueError("Session field history must be a list of objects.")
        if not isinstance(session.context_files, list):
            raise ValueError("Session field context_files must be a list of objects.")
        if not isinstance(session.effort, str) or session.effort.lower() not in {"low", "medium", "high"}:
            raise ValueError("Session field effort must be low, medium, or high.")

        updated_at = time.time()
        data = session.to_dict()
        data["updated_at"] = updated_at
        data["effort"] = session.effort.lower()
        try:
            # Validate the same schema that load() will consume before creating a temp file.
            Session.from_dict(data)
            payload = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, OverflowError, RecursionError) as exc:
            raise ValueError(f"Session data cannot be serialized: {exc}") from exc

        self._ensure_root(create=True)
        if not self._temporary_cleanup_done:
            self._cleanup_stale_temporary_files()
            self._temporary_cleanup_done = True
        target = self._path(session.id)
        self._validate_existing_target(target)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{session.id}-", suffix=".tmp", dir=self.root,
        )
        temporary = Path(temporary_name)
        try:
            if os.name == "posix":
                os.fchmod(descriptor, 0o600)
            handle = os.fdopen(descriptor, "wb")
            descriptor = -1
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            session.updated_at = updated_at
            session.effort = data["effort"]
            self._fsync_directory()
        finally:
            if descriptor != -1:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def load(self, session_id: str) -> Session:
        if not self.persist:
            raise ValueError("Session persistence is disabled for this run.")
        if not isinstance(session_id, str):
            raise ValueError("Session ID must contain 8 to 32 hexadecimal digits.")
        requested = session_id.lower()
        if not _SESSION_ID_PREFIX.fullmatch(requested):
            raise ValueError("Session ID must contain 8 to 32 hexadecimal digits.")
        if not self._ensure_root(create=False):
            raise FileNotFoundError(f"Session not found: {session_id}")

        candidates = [
            path for path in self.root.glob("*.json")
            if _SESSION_ID.fullmatch(path.stem)
        ]
        exact = [path for path in candidates if path.stem == requested]
        matches = exact or [path for path in candidates if path.stem.startswith(requested)]
        if not matches:
            raise FileNotFoundError(f"Session not found: {session_id}")
        if len(matches) > 1:
            ids = ", ".join(sorted(path.stem for path in matches))
            raise ValueError(f"Session ID prefix is ambiguous. Use one of: {ids}")
        return self._read_session(matches[0])

    def list_recent(self, limit: int | None = 10) -> list[Session]:
        sessions, _ = self.list_recent_with_errors(limit=limit)
        return sessions

    def list_recent_with_errors(self, limit: int | None = 10) -> tuple[list[Session], list[tuple[str, str]]]:
        """Return readable sessions and safe per-file diagnostics without exposing contents."""
        if not self.persist:
            return [], []
        if not self._ensure_root(create=False):
            return [], []
        sessions = []
        errors = []
        for path in self.root.glob("*.json"):
            if not _SESSION_ID.fullmatch(path.stem):
                continue
            try:
                sessions.append(self._read_session(path))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                errors.append((path.stem, str(exc)))
        ordered = sorted(sessions, key=lambda item: item.updated_at, reverse=True)
        return (ordered if limit is None else ordered[:max(0, limit)]), errors

    def saved_ids(self) -> list[str]:
        """Return exact, regular session filenames without parsing their contents."""
        if not self.persist or not self._ensure_root(create=False):
            return []
        ids = []
        for path in self.root.glob("*.json"):
            if not _SESSION_ID.fullmatch(path.stem) or path.is_symlink():
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                ids.append(path.stem)
        return sorted(ids)

    def size_bytes(self, session_id: str) -> int:
        if not self.persist:
            raise ValueError("Session persistence is disabled for this run.")
        if not self._ensure_root(create=False):
            raise FileNotFoundError(f"Session not found: {session_id}")
        path = self._path(session_id)
        info = self._validate_existing_target(path)
        if info is None:
            raise FileNotFoundError(f"Session not found: {session_id}")
        return info.st_size

    def delete(self, session_id: str) -> None:
        self.delete_many([session_id])

    def delete_many(self, session_ids: list[str]) -> list[str]:
        """Delete only exact session files after validating every target first."""
        if not self.persist:
            raise ValueError("Session persistence is disabled for this run.")
        if not isinstance(session_ids, list):
            raise ValueError("Session IDs must be provided as a list.")
        for session_id in session_ids:
            if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
                raise ValueError("Session ID must be eight legacy hex digits or a 32-digit lowercase UUID.")
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("Duplicate session IDs are not allowed.")
        if not session_ids:
            return []
        if not self._ensure_root(create=False):
            raise FileNotFoundError("No saved sessions were found.")

        targets = []
        for session_id in session_ids:
            path = self._path(session_id)
            if self._validate_existing_target(path) is None:
                raise FileNotFoundError(f"Session not found: {session_id}")
            targets.append((session_id, path))

        deleted = []
        for session_id, path in targets:
            try:
                path.unlink()
            except OSError as exc:
                raise OSError(
                    f"Deleted {len(deleted)} of {len(targets)} requested sessions before failure: {exc}"
                ) from exc
            deleted.append(session_id)
        self._fsync_directory()
        return deleted

    def _ensure_root(self, *, create: bool) -> bool:
        if self.root.is_symlink():
            raise ValueError(f"Session directory must not be a symbolic link: {self.root}")
        if not self.root.exists():
            if not create:
                return False
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError(f"Session directory must not be a symbolic link: {self.root}")
        info = self.root.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(f"Session path is not a directory: {self.root}")
        if os.name == "posix":
            if info.st_uid != os.getuid():
                raise PermissionError(f"Session directory is not owned by the current user: {self.root}")
            if stat.S_IMODE(info.st_mode) & 0o077:
                os.chmod(self.root, 0o700)
                if stat.S_IMODE(self.root.stat().st_mode) & 0o077:
                    raise PermissionError(f"Could not restrict session directory permissions: {self.root}")
        return True

    @staticmethod
    def _validate_existing_target(path: Path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Refusing to replace a symbolic link session file: {path}")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Session path is not a regular file: {path}")
        if os.name == "posix" and info.st_uid != os.getuid():
            raise PermissionError(f"Session file is not owned by the current user: {path}")
        return info

    def _read_session(self, path: Path) -> Session:
        if path.is_symlink():
            raise ValueError(f"Refusing to read a symbolic link session file: {path}")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"Session path is not a regular file: {path}")
            if os.name == "posix":
                if info.st_uid != os.getuid():
                    raise PermissionError(f"Session file is not owned by the current user: {path}")
                if stat.S_IMODE(info.st_mode) & 0o077:
                    os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                payload = handle.read().decode("utf-8")
            try:
                data = json.loads(payload)
            except RecursionError as exc:
                raise ValueError(f"Session JSON is nested too deeply to read: {path}") from exc
        finally:
            if descriptor != -1:
                os.close(descriptor)
        if not isinstance(data, dict):
            raise ValueError(f"Session file must contain a JSON object: {path}")
        session = Session.from_dict(data, legacy_timestamp=info.st_mtime)
        if session.id != path.stem:
            raise ValueError(f"Session ID does not match its file name: {path}")
        return session

    def _fsync_directory(self) -> None:
        if os.name != "posix":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        unsupported = {errno.EBADF, errno.EINVAL}
        if hasattr(errno, "ENOTSUP"):
            unsupported.add(errno.ENOTSUP)
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported.add(errno.EOPNOTSUPP)
        try:
            descriptor = os.open(self.root, flags)
        except OSError as exc:
            if exc.errno in unsupported:
                return
            raise
        try:
            try:
                os.fsync(descriptor)
            except OSError as exc:
                if exc.errno not in unsupported:
                    raise
        finally:
            os.close(descriptor)

    def _cleanup_stale_temporary_files(self) -> None:
        """Remove only old, regular files matching this manager's atomic-write naming."""
        cutoff = time.time() - _STALE_TEMP_AGE_SECONDS
        for path in self.root.iterdir():
            if not _TEMP_SESSION_FILE.fullmatch(path.name):
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            if os.name == "posix" and info.st_uid != os.getuid():
                continue
            if info.st_mtime < cutoff:
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    continue

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise ValueError("Session ID must be eight legacy hex digits or a 32-digit lowercase UUID.")
        return self.root / f"{session_id}.json"
