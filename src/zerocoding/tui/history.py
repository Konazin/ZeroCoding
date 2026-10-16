"""Persistent, workspace-scoped prompt history for the production TUI."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from prompt_toolkit.history import History


def project_history_path(workspace: Path | None = None) -> Path:
    root = (workspace or Path.cwd()).resolve()
    key = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:20]
    if os.name == "nt":
        data_home = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "zerocoding" / "history" / f"{key}.json"


class ProjectPromptHistory(History):
    """A small per-workspace prompt history, capped at 200 entries."""

    limit = 200

    def __init__(self, workspace: Path | None = None):
        super().__init__()
        self.path = project_history_path(workspace)
        self._entries: list[str] | None = None

    def _load(self) -> list[str]:
        if self._entries is None:
            try:
                values = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = [item for item in values if isinstance(item, str)][-self.limit:]
            except (OSError, ValueError, TypeError):
                self._entries = []
        return self._entries

    def load_history_strings(self) -> Iterable[str]:
        yield from reversed(self._load())

    def store_string(self, string: str) -> None:
        if not string.strip():
            return
        entries = self._load()
        entries.append(string)
        del entries[:-self.limit]
        temp_name = ""
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(prefix="history-", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(entries, stream, ensure_ascii=False)
                stream.write("\n")
            os.replace(temp_name, self.path)
        except OSError:
            return
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
