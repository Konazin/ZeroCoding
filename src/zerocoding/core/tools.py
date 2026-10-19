"""Small, workspace-scoped toolset for the coding agent."""
from __future__ import annotations

import difflib
import json
import os
import re
import shlex
import stat
import tempfile
from pathlib import Path
from typing import Callable

from . import git_tools
from .command_policy import CommandPolicy
from .events import AgentEvent
from .process import run_capped


IGNORED = {".git", ".zerocoding", "node_modules", "venv", ".venv", "__pycache__", "target", "dist", "build"}
READ_ONLY_TOOL_NAMES = frozenset({"list_files", "search_files", "read_file", "git"})


class ToolRegistry:
    def __init__(self, root: str | Path, approve: Callable[[str, str], bool] | None = None,
                 policy: CommandPolicy | None = None):
        self.root = Path(root).resolve()
        self.approve = approve
        self.policy = policy or CommandPolicy()
        self.journal = None  # core.journal.FileJournal, attached per session by the CLI
        self._external: dict = {}  # name -> ExternalTool (duck-typed: .spec .server .tool .read_only .handler)
        self._specs = [
            self._spec("list_files", "List project files", {"path": {"type": "string"}, "limit": {"type": "integer"}}),
            self._spec("search_files", "Search text in project files using a regular expression", {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}, ["pattern"]),
            self._spec("read_file", "Read a file inside the project", {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
            self._spec("write_file", "Propose a complete file content update; user approval is required before writing", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            self._spec("edit_file", "Propose replacing one exact piece of text in an existing file; old_text must match exactly once. User approval is required before writing", {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, ["path", "old_text", "new_text"]),
            self._spec("run_command", "Run a command in the project; user approval is required first", {"command": {"type": "string"}}, ["command"]),
        ]
        # Git tools exist only inside a repository, so projects without git pay no prompt tokens for them.
        self.git_enabled = git_tools.is_git_repo(self.root, self.policy)
        if self.git_enabled:
            self._specs += [
                self._spec("git", "Inspect the git repository (read-only): status, diff or log",
                           {"action": {"type": "string", "enum": list(git_tools.READ_ACTIONS)}, "path": {"type": "string"},
                            "staged": {"type": "boolean"}, "limit": {"type": "integer"}}, ["action"]),
                self._spec("git_commit", "Commit the listed files with a message; user approval is required first",
                           {"message": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}},
                           ["message", "paths"]),
            ]

    @staticmethod
    def _spec(name, description, properties, required=None):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}}

    @property
    def schemas(self):
        return self._specs

    def is_read_only(self, name: str) -> bool:
        external = self._external.get(name)
        return external.read_only if external else name in READ_ONLY_TOOL_NAMES

    @property
    def read_only_schemas(self):
        return [spec for spec in self._specs if self.is_read_only(spec["function"]["name"])]

    def register_external(self, tool) -> None:
        """Expose an extension tool (MCP or subagent). Replaces an earlier registration of the same name."""
        if tool.name in {s["function"]["name"] for s in self._specs} and tool.name not in self._external:
            raise ValueError(f"Tool name '{tool.name}' collides with a built-in tool")
        self._external[tool.name] = tool
        self._specs = [s for s in self._specs if s["function"]["name"] != tool.name] + [tool.spec]

    def clone_for(self, root: str | Path) -> "ToolRegistry":
        """Same approval callback, policy and extension tools, different workspace root."""
        clone = ToolRegistry(root, approve=self.approve, policy=self.policy)
        for tool in self._external.values():
            clone.register_external(tool)
        return clone

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
            directories[:] = sorted(
                name for name in directories
                if name not in IGNORED and not (Path(current) / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = Path(current) / filename
                if not path.is_symlink():
                    yield path

    def _file_snapshot(self, path: Path):
        """Return a small identity/content snapshot used to detect edits during approval."""
        if not path.exists():
            return None
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Path is not a regular file")
        if info.st_size > 1_000_000:
            raise ValueError("File is too large to update with this tool (limit: 1 MB)")
        return (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size), path.read_bytes()

    def _assert_unchanged(self, original_value: str, path: Path, snapshot) -> None:
        """Refuse an approved write if the path or file changed while approval was open."""
        current = self._path(original_value, must_exist=snapshot is not None)
        if current != path:
            raise ValueError("Path changed after approval. Nothing was written; read the file again and retry.")
        if snapshot is None:
            if current.exists():
                raise ValueError("File appeared after approval. Nothing was written; review the new file and retry.")
            return
        try:
            now = self._file_snapshot(current)
        except FileNotFoundError:
            now = None
        if now != snapshot:
            raise ValueError("File changed after approval. Nothing was written; read it again and review a new diff.")

    def _atomic_write(self, original_value: str, path: Path, content: str, snapshot) -> None:
        """Write approved text atomically, preserving permissions and refusing stale previews."""
        self._assert_unchanged(original_value, path, snapshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Creating a temporary file in the destination directory keeps os.replace atomic.
        self._assert_unchanged(original_value, path, snapshot)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.zerocoding-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if snapshot is not None:
                current_mode = stat.S_IMODE(path.stat().st_mode)
                os.chmod(temporary, current_mode)
            self._assert_unchanged(original_value, path, snapshot)
            if snapshot is None:
                # link() fails atomically if another process created the target meanwhile.
                os.link(temporary, path)
                os.unlink(temporary)
            else:
                os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _journal(self, path: Path, snapshot, new_text: str) -> None:
        """Record the original of a file just written so the turn can be undone (best effort)."""
        if self.journal is None:
            return
        try:
            self.journal.record(path.relative_to(self.root).as_posix(),
                                snapshot[1] if snapshot is not None else None, new_text.encode("utf-8"))
        except Exception:
            return  # the write already happened and was approved; a journal failure must not hide that

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

    @staticmethod
    def _int(args: dict, key: str, default: int, low: int, high: int) -> int:
        try:
            return min(high, max(low, int(args.get(key, default))))
        except (TypeError, ValueError):
            raise ValueError(f"Argument '{key}' must be an integer") from None

    def _validate(self, name: str, args) -> None:
        spec = next((s["function"] for s in self._specs if s["function"]["name"] == name), None)
        if spec is None:
            known = ", ".join(s["function"]["name"] for s in self._specs)
            raise ValueError(f"Unknown tool '{name}'. Available tools: {known}")
        if not isinstance(args, dict):
            raise ValueError(f"Arguments for {name} must be an object")
        missing = [key for key in (spec["parameters"].get("required") or []) if args.get(key) is None]
        if missing:
            raise ValueError(f"Missing required argument(s) for {name}: {', '.join(missing)}")

    def _run_external(self, tool, args: dict, event_callback) -> str:
        if not tool.read_only:
            preview = f"Server: {tool.server}\nTool: {tool.tool}\nArguments:\n{json.dumps(args, indent=2, ensure_ascii=False)[:2000]}"
            self._emit(event_callback, AgentEvent("approval_requested", tool.name, tool.tool, "Tool call preview ready"))
            if not self.approve or not self.approve("Run external tool", preview):
                return "External tool call denied by user. Nothing was executed."
        return tool.handler(args)

    def _execute(self, name: str, args: dict, event_callback=None, plan_mode: bool = False) -> str:
        if plan_mode and not self.is_read_only(name):
            return f"Tool '{name}' is blocked in Plan mode. No action was taken."
        self._validate(name, args)
        if name in self._external:
            return self._run_external(self._external[name], args, event_callback)
        if name == "list_files":
            root = self._path(args.get("path", "."), must_exist=True)
            if not root.is_dir():
                raise ValueError("Path is not a directory")
            limit = self._int(args, "limit", 100, 1, 200)
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
            try:
                regex = re.compile(str(args["pattern"]))
            except re.error as exc:
                raise ValueError(f"Invalid regular expression: {exc}") from None
            limit = self._int(args, "limit", 30, 1, 100)
            found = []
            scanned_bytes = 0
            scanned_files = 0
            for path in self._iter_files(root):
                try:
                    # Resolve again at use time so links and excluded targets are never read.
                    path = self._path(str(path), must_exist=True)
                except (ValueError, FileNotFoundError):
                    continue
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
            start = self._int(args, "start_line", 1, 1, 10**9)
            end = min(len(lines), self._int(args, "end_line", start + 300, 1, 10**9))
            return "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines[start - 1:end], start))[:12000]
        if name == "git":
            return git_tools.read(self.root, self.policy, args, self._path)
        if name == "git_commit":
            paths, message, preview = git_tools.prepare_commit(self.root, self.policy, args, self._path)
            self._emit(event_callback, AgentEvent("approval_requested", name, ", ".join(paths)[:96], "Commit preview ready"))
            if not self.approve or not self.approve("Git commit", preview):
                return "Commit denied by user. Nothing was committed."
            return git_tools.commit(self.root, self.policy, paths, message)
        if name == "write_file":
            original_value = args["path"]
            path = self._path(original_value)
            snapshot = self._file_snapshot(path)
            old_bytes = snapshot[1] if snapshot is not None else b""
            old = old_bytes.decode("utf-8", errors="replace")
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
            self._atomic_write(original_value, path, new, snapshot)
            self._journal(path, snapshot, new)
            return f"Wrote {path.relative_to(self.root)}."
        if name == "edit_file":
            original_value = args["path"]
            path = self._path(original_value, must_exist=True)
            snapshot = self._file_snapshot(path)
            if snapshot is None:
                raise FileNotFoundError(f"Path does not exist: {original_value}")
            old_text, new_text = str(args["old_text"]), str(args["new_text"])
            if not old_text:
                raise ValueError("old_text must not be empty; use write_file to create a new file")
            try:
                original = snapshot[1].decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("File is not valid UTF-8 text and cannot be edited with this tool") from None
            relative = str(path.relative_to(self.root))
            count = original.count(old_text)
            if count == 0:
                raise ValueError(f"old_text was not found in {relative}. Read the file again and copy the exact text, including indentation.")
            if count > 1:
                raise ValueError(f"old_text matches {count} places in {relative}. Include more surrounding lines so it matches exactly once.")
            if old_text == new_text:
                return "old_text and new_text are identical. No file was changed."
            updated = original.replace(old_text, new_text, 1)
            diff = "".join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                      fromfile=relative, tofile=relative))
            self._emit(event_callback, AgentEvent("approval_requested", name, relative, "Edit preview ready"))
            if not self.approve or not self.approve("Edit file", diff):
                return "Edit denied by user. No file was changed."
            self._atomic_write(original_value, path, updated, snapshot)
            self._journal(path, snapshot, updated)
            return f"Edited {relative}."
        if name == "run_command":
            command = str(args["command"])
            try:
                argv = shlex.split(command)
            except ValueError as exc:
                raise ValueError(f"Could not parse the command: {exc}") from None
            reason = self.policy.check(argv, self.root)
            if reason:
                return f"Command blocked by policy: {reason}. Nothing was executed."
            target = " ".join(command.split())
            if len(target) > 96:
                target = target[:93] + "…"
            self._emit(event_callback, AgentEvent(
                "approval_requested", name, target, "Command preview ready"
            ))
            if not self.approve or not self.approve("Run command", command):
                return "Command denied by user. Nothing was executed."
            try:
                result = run_capped(argv, cwd=self.root, env=self.policy.environment(),
                                    timeout=self.policy.timeout,
                                    max_output_chars=self.policy.max_output_chars)
            except FileNotFoundError:
                return f"Command not found: {argv[0]}. Nothing was executed."
            except OSError as exc:
                return f"Command could not be started: {exc}. Nothing was executed."
            if result.timed_out:
                return f"Command timed out after {self.policy.timeout}s and was stopped."
            return f"exit code: {result.returncode}\n{result.output.strip()}"
        raise ValueError(f"Unknown tool: {name}")
