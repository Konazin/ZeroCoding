from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SESSION_DIR = Path("~/.zerocoding/sessions").expanduser()


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
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def new(cls, provider: str, model: str, mode: str = "code", path: str = ".") -> "Session":
        return cls(id=uuid.uuid4().hex[:8], provider=provider, model=model, mode=mode, path=path)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return cls(
            id=str(data["id"]),
            provider=str(data.get("provider", "")),
            model=str(data.get("model", "")),
            mode=str(data.get("mode", "code")),
            skills=list(data.get("skills") or []),
            path=str(data.get("path", ".")),
            history=list(data.get("history") or []),
            context_files=list(data.get("context_files") or []),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "skills": list(self.skills),
            "path": self.path,
            "history": list(self.history),
            "context_files": list(self.context_files),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionManager:
    def __init__(self, root: str | Path = DEFAULT_SESSION_DIR):
        self.root = Path(root).expanduser()

    def create(self, provider: str, model: str, mode: str = "code", path: str = ".") -> Session:
        session = Session.new(provider=provider, model=model, mode=mode, path=path)
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        session.updated_at = time.time()
        self._path(session.id).write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")

    def load(self, session_id: str) -> Session:
        matches = sorted(self.root.glob(f"{session_id}*.json"))
        if not matches:
            raise FileNotFoundError(f"Session not found: {session_id}")
        data = json.loads(matches[0].read_text(encoding="utf-8"))
        return Session.from_dict(data)

    def list_recent(self, limit: int = 10) -> list[Session]:
        sessions = []
        for path in self.root.glob("*.json"):
            try:
                sessions.append(Session.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)[:limit]

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"
