import subprocess
from pathlib import Path

from ..core.project_context import ProjectContext
from ..core.permissions import requires_network_access
from .registry import ToolRegistry, ToolSpec
from .sandbox import run_workspace_command


def create_builtin_tools(root: str | Path) -> ToolRegistry:
    root = Path(root).resolve()
    context = ProjectContext(root)
    registry = ToolRegistry()

    def resolve(path: str) -> Path:
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Path must stay inside the project.")
        if any(part in {".git", "node_modules", ".venv", "venv", "__pycache__"} for part in resolved.parts):
            raise ValueError("Path is inside an ignored directory.")
        return resolved

    registry.register(ToolSpec(
        "read_file", "Read a UTF-8 file inside the project.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        lambda args: _read(resolve(args["path"])),
        permission_scope="project",
    ))

    def search(args):
        matches = context.grep(args["pattern"], limit=50)
        return "\n".join(f"{path}:{line}: {text[:400]}" for path, line, text in matches) or "No matches."

    registry.register(ToolSpec(
        "search_files", "Search project text files with a regular expression.",
        {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
        search,
        permission_scope="project",
    ))
    registry.register(ToolSpec(
        "list_files", "List files in the project, excluding generated and dependency directories.",
        {"type": "object", "properties": {"limit": {"type": "integer", "default": 200}}},
        lambda args: "\n".join(context.list_project_files(limit=max(1, min(int(args.get("limit", 200)), 500)))),
        permission_scope="project",
    ))

    registry.register(ToolSpec(
        "write_file", "Create or replace a UTF-8 file inside the project.",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        lambda args: _write(resolve(args["path"]), args["content"]),
        confirmation=True,
        permission_scope="project",
    ))

    def run_command(args, sandboxed=False):
        argv = args["argv"]
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv must be a non-empty list of strings.")
        network_access = args.get("network_access", False)
        if not isinstance(network_access, bool):
            raise ValueError("network_access must be a boolean.")
        if sandboxed:
            result = run_workspace_command(argv, cwd=root, network_access=network_access or requires_network_access(argv), timeout=60)
        else:
            result = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=60, shell=False)
        return f"exit={result.returncode}\nstdout:\n{result.stdout[:4000]}\nstderr:\n{result.stderr[:4000]}"

    registry.register(ToolSpec(
        "run_command", "Run a command in the project directory (argv array; no shell expansion).",
        {"type": "object", "properties": {
            "argv": {"type": "array", "items": {"type": "string"}},
            "network_access": {"type": "boolean", "default": False},
        }, "required": ["argv"], "additionalProperties": False},
        lambda args: run_command(args),
        confirmation=True,
        permission_scope="command",
        sandbox_handler=lambda args: run_command(args, sandboxed=True),
    ))

    registry.register(ToolSpec(
        "git_status", "Show the current Git working tree status.",
        {"type": "object", "properties": {}},
        lambda _: _git(root, ["status", "--short"]),
        permission_scope="project",
    ))
    registry.register(ToolSpec(
        "git_diff", "Show the current Git diff (unstaged and staged).",
        {"type": "object", "properties": {}},
        lambda _: _git_diff(root),
        permission_scope="project",
    ))
    return registry


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {path}"


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace") as file:
        content = file.read(20_001)
    return content[:20_000] + ("\n[truncated]" if len(content) > 20_000 else "")


def _git(root: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
    if result.returncode:
        return result.stderr.strip() or f"git exited with status {result.returncode}"
    return result.stdout[:6000] or "No output."


def _git_diff(root: Path) -> str:
    parts = []
    for args in (["diff", "--", "."], ["diff", "--cached", "--", "."]):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
        if result.returncode:
            return result.stderr.strip() or f"git exited with status {result.returncode}"
        if result.stdout:
            parts.append(result.stdout)
    return "\n".join(parts)[:6000] or "No diff."
