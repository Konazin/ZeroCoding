"""Small, workspace-scoped toolset for the coding agent."""
from __future__ import annotations

import difflib
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Callable

from .events import AgentEvent


IGNORED = {".git", ".zerocoding", "node_modules", "venv", ".venv", "__pycache__", "target", "dist", "build"}
READ_ONLY_TOOL_NAMES = frozenset({"list_files", "search_files", "read_file"})


class ToolRegistry:
    def __init__(self, root: str | Path, approve: Callable[[str, str], bool] | None = None):
        self.root = Path(root).resolve()
        self.approve = approve
        self._specs = [
            self._spec("list_files", "List project files", {"path": {"type": "string"}, "limit": {"type": "integer"}}),
            self._spec("search_files", "Search text in project files using a regular expression", {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}, ["pattern"]),
            self._spec("read_file", "Read a file inside the project", {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
            self._spec("write_file", "Propose a complete file content update; user approval is required before writing", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            self._spec("run_command", "Run a command in the project; user approval is required first", {"command": {"type": "string"}}, ["command"]),
        ]

    @staticmethod
    def _spec(name, description, properties, required=None):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}}

    @property
    def schemas(self):
        return self._specs

    @property
    def read_only_schemas(self):
        return [spec for spec in self._specs if spec["function"]["name"] in READ_ONLY_TOOL_NAMES]

    def _path(self, value: str, *, must_exist=False) -> Path:
        candidate = Path(value or ".").expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path is outside the project workspace") from exc
        if set(resolved.parts) & IGNORED:
            raise ValueError("Path is in an excluded directory")
        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {value}")
        return resolved

    @staticmethod
    def _iter_files(root: Path):
        for current, directories, filenames in os.walk(root):
            directories[:] = sorted(name for name in directories if name not in IGNORED)
            for filename in sorted(filenames):
                yield Path(current) / filename

    def execute(self, name: str, args: dict, *, plan_mode: bool = False) -> str:
        return self._execute(name, args, event_callback=None, plan_mode=plan_mode)

    def execute_with_events(self, name: str, args: dict, event_callback, *, plan_mode: bool = False) -> str:
        """Execute a tool and report approval prompts without exposing previews."""
        return self._execute(name, args, event_callback=event_callback, plan_mode=plan_mode)

    @staticmethod
    def _emit(callback, event: AgentEvent) -> None:
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            return

    def _execute(self, name: str, args: dict, event_callback=None, plan_mode: bool = False) -> str:
        if plan_mode and name not in READ_ONLY_TOOL_NAMES:
            return f"Tool '{name}' is blocked in Plan mode. No action was taken."
        if name == "list_files":
            root = self._path(args.get("path", "."), must_exist=True)
            if not root.is_dir():
                raise ValueError("Path is not a directory")
            limit = min(200, max(1, int(args.get("limit", 100))))
            found = []
            for path in self._iter_files(root):
                if not path.is_file():
                    continue
                found.append(str(path.relative_to(self.root)))
                if len(found) >= limit:
                    break
            return "\n".join(found) or "No files found."
        if name == "search_files":
            root = self._path(args.get("path", "."), must_exist=True)
            regex = re.compile(str(args["pattern"]))
            limit = min(100, max(1, int(args.get("limit", 30))))
            found = []
            scanned_bytes = 0
            scanned_files = 0
            for path in self._iter_files(root):
                if not path.is_file() or path.stat().st_size > 1_000_000:
                    continue
                scanned_bytes += path.stat().st_size
                scanned_files += 1
                if scanned_bytes > 20_000_000 or scanned_files > 5000:
                    break
                try:
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except OSError:
                    continue
                for line_no, line in enumerate(lines, 1):
                    if regex.search(line):
                        found.append(f"{path.relative_to(self.root)}:{line_no}: {line[:300]}")
                        if len(found) >= limit:
                            return "\n".join(found)
            return "\n".join(found) or "No matches found."
        if name == "read_file":
            path = self._path(args["path"], must_exist=True)
            if not path.is_file():
                raise ValueError("Path is not a file")
            if path.stat().st_size > 1_000_000:
                raise ValueError("File is too large to read with this tool (limit: 1 MB)")
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, int(args.get("start_line", 1)))
            end = min(len(lines), int(args.get("end_line", start + 300)))
            return "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines[start - 1:end], start))[:12000]
        if name == "write_file":
            path = self._path(args["path"])
            if path.exists() and not path.is_file():
                raise ValueError("Path is not a file")
            if path.exists() and path.stat().st_size > 1_000_000:
                raise ValueError("Existing file is too large to replace with this tool (limit: 1 MB)")
            old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            new = str(args["content"])
            if len(new) > 1_000_000:
                raise ValueError("Proposed file is too large (limit: 1 MB)")
            diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                      fromfile=str(path.relative_to(self.root)), tofile=str(path.relative_to(self.root))))
            preview = diff or "(empty file; no content change)"
            self._emit(event_callback, AgentEvent(
                "approval_requested", name, str(path.relative_to(self.root)), "Write preview ready"
            ))
            if not self.approve or not self.approve("Write file", preview):
                return "Write denied by user. No file was changed."
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8")
            return f"Wrote {path.relative_to(self.root)}."
        if name == "run_command":
            command = str(args["command"])
            target = " ".join(command.split())
            if len(target) > 96:
                target = target[:93] + "…"
            self._emit(event_callback, AgentEvent(
                "approval_requested", name, target, "Command preview ready"
            ))
            if not self.approve or not self.approve("Run command", command):
                return "Command denied by user. Nothing was executed."
            argv = shlex.split(command)
            if not argv:
                raise ValueError("Empty command")
            result = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=60, shell=False)
            output = (result.stdout + result.stderr).strip()
            return f"exit code: {result.returncode}\n{output[:8000]}"
        raise ValueError(f"Unknown tool: {name}")
