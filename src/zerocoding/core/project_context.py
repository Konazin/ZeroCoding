from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


IGNORED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "target", "dist", "build"}


@dataclass
class ContextFile:
    path: str
    content: str
    lines: int
    tokens: int


class ProjectContext:
    def __init__(self, root: str | Path = ".", max_file_chars: int = 20_000, max_total_chars: int = 60_000):
        self.root = Path(root).resolve()
        self.max_file_chars = max_file_chars
        self.max_total_chars = max_total_chars
        self.files: dict[str, ContextFile] = {}

    def add(self, path: str | Path) -> ContextFile:
        resolved = self._resolve(path)
        content = self._read_limited(resolved)
        rel = self._relative(resolved)
        context_file = ContextFile(
            path=rel,
            content=content,
            lines=len(content.splitlines()),
            tokens=self._estimate_tokens(content),
        )
        projected = self.total_chars + len(content)
        existing = self.files.get(rel)
        if existing:
            projected -= len(existing.content)
        if projected > self.max_total_chars:
            raise ValueError(f"Context limit exceeded ({self.max_total_chars} chars total).")
        self.files[rel] = context_file
        return context_file

    def read(self, path: str | Path) -> ContextFile:
        resolved = self._resolve(path)
        content = self._read_limited(resolved)
        return ContextFile(
            path=self._relative(resolved),
            content=content,
            lines=len(content.splitlines()),
            tokens=self._estimate_tokens(content),
        )

    def remove(self, path: str | Path) -> bool:
        key = self._relative(self._resolve(path))
        return self.files.pop(key, None) is not None

    def clear(self) -> None:
        self.files.clear()

    @property
    def total_chars(self) -> int:
        return sum(len(file.content) for file in self.files.values())

    def tree(self) -> list[str]:
        return sorted(self.files)

    def list_project_files(self, limit: int = 200) -> list[str]:
        files = []
        for path in sorted(self.root.rglob("*")):
            if len(files) >= limit:
                break
            if self._is_ignored(path) or not path.is_file():
                continue
            files.append(self._relative(path))
        return files

    def grep(self, pattern: str, limit: int = 50) -> list[tuple[str, int, str]]:
        regex = re.compile(pattern)
        results = []
        for path in sorted(self.root.rglob("*")):
            if len(results) >= limit:
                break
            if self._is_ignored(path) or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append((self._relative(path), lineno, line.strip()))
                    if len(results) >= limit:
                        break
        return results

    def build_prompt(self, user_text: str) -> str:
        if not self.files:
            return user_text
        blocks = ["Project context explicitly added by the user:"]
        for file in self.files.values():
            blocks.append(f"\n--- {file.path} ---\n{file.content}")
        return "\n".join(blocks) + f"\n\nUser request:\n{user_text}"

    def build_system_prompt(self) -> str | None:
        if not self.files:
            return None
        blocks = ["You are ZeroCoding, a helpful coding assistant.", "Project context explicitly added by the user:"]
        for file in self.files.values():
            blocks.append(f"\n--- {file.path} ---\n{file.content}")
        return "\n".join(blocks)

    def snapshot(self) -> list[dict[str, str]]:
        return [{"path": file.path, "content": file.content} for file in self.files.values()]

    def restore(self, files: list[dict[str, str]]) -> None:
        self.files.clear()
        for item in files:
            path = str(item.get("path", ""))
            content = str(item.get("content", ""))
            if not path:
                continue
            self.files[path] = ContextFile(
                path=path,
                content=content,
                lines=len(content.splitlines()),
                tokens=self._estimate_tokens(content),
            )

    def _resolve(self, path: str | Path) -> Path:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = self.root / resolved
        resolved = resolved.resolve()
        if self._is_ignored(resolved):
            raise ValueError(f"Ignored path: {path}")
        if not resolved.exists():
            raise FileNotFoundError(str(path))
        if not resolved.is_file():
            raise ValueError(f"Not a file: {path}")
        return resolved

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def _read_limited(self, path: Path) -> str:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if len(content) > self.max_file_chars:
            return content[: self.max_file_chars] + "\n[truncated]"
        return content

    def _is_ignored(self, path: Path) -> bool:
        parts = set(path.parts)
        return bool(parts & IGNORED_DIRS)

    def _estimate_tokens(self, content: str) -> int:
        return max(1, len(content) // 4) if content else 0
