"""Small Linux command sandbox for unattended local tool calls."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path


class SandboxUnavailable(RuntimeError):
    pass


def build_bwrap_command(argv: list[str], cwd: str | Path, *, network_access: bool = False, executable: str = "bwrap", readonly_paths: tuple[Path, ...] = (), extra_path: tuple[Path, ...] = ()) -> list[str]:
    root = Path(cwd).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Sandbox root must be a directory.")
    command = [executable, "--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid", "--unshare-uts", "--unshare-ipc"]
    if not network_access:
        command.append("--unshare-net")
    command.extend(["--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib"])
    if Path("/usr/lib64").exists():
        command.extend(["--symlink", "usr/lib64", "/lib64"])
    command.extend(["--dev", "/dev", "--proc", "/proc", "--dir", "/etc"])
    for host_file in ("/etc/ld.so.cache", "/etc/passwd", "/etc/group", "/etc/nsswitch.conf"):
        if Path(host_file).is_file():
            command.extend(["--ro-bind", host_file, host_file])
    command.extend(["--dir", "/workspace", "--bind", str(root), "/workspace"])
    directories = {path for mount in readonly_paths for path in (mount, *mount.parents) if path != Path("/")}
    for directory in sorted(directories, key=lambda path: (len(path.parts), str(path))):
        command.extend(["--dir", str(directory)])
    for path in readonly_paths:
        command.extend(["--ro-bind", str(path), str(path)])
    command.extend(["--tmpfs", "/tmp"])
    if network_access:
        command.extend(["--dir", "/etc/ssl"])
        certs = Path("/etc/ssl/certs")
        if certs.exists():
            command.extend(["--ro-bind", str(certs), str(certs)])
        for host_file in ("/etc/resolv.conf", "/etc/hosts"):
            if Path(host_file).is_file():
                command.extend(["--ro-bind", host_file, host_file])
    command.extend([
        "--setenv", "HOME", "/tmp",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "PATH", ":".join([*(str(path) for path in extra_path), "/usr/local/bin", "/usr/bin", "/bin"]),
        "--chdir", "/workspace", "--", *argv,
    ])
    return command


def run_workspace_command(argv: list[str], cwd: str | Path, *, network_access: bool = False, timeout: int = 60, env: dict[str, str] | None = None):
    executable = shutil.which("bwrap") if platform.system() == "Linux" else None
    if not executable:
        raise SandboxUnavailable("Full access and automatic approval require Linux bubblewrap (bwrap).")
    root = Path(cwd).expanduser().resolve(strict=True)
    argv, readonly_paths, extra_path = _resolve_volta_command(argv)
    argv = _resolve_standard_command(argv)
    argv = _workspace_argv(argv, root)
    command = build_bwrap_command(argv, cwd, network_access=network_access, executable=executable, readonly_paths=readonly_paths, extra_path=extra_path)
    sandbox_env = {"PATH": ":".join([*(str(path) for path in extra_path), "/usr/local/bin", "/usr/bin", "/bin"]), "HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
    if env and env.get("PYTHONPATH"):
        paths = []
        for value in env["PYTHONPATH"].split(os.pathsep):
            path = Path(value).expanduser()
            if path.is_absolute() and path.is_relative_to(root):
                relative = path.relative_to(root).as_posix()
                paths.append("/workspace" + (f"/{relative}" if relative != "." else ""))
        if paths:
            sandbox_env["PYTHONPATH"] = os.pathsep.join(paths)
    try:
        return subprocess.run(command, cwd=cwd, env=sandbox_env, capture_output=True, text=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout} seconds.") from exc


def _workspace_argv(argv: list[str], root: Path) -> list[str]:
    rewritten = []
    for value in argv:
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(root):
            relative = path.relative_to(root).as_posix()
            rewritten.append("/workspace" + (f"/{relative}" if relative != "." else ""))
        else:
            rewritten.append(value)
    return rewritten


def _resolve_standard_command(argv: list[str]) -> list[str]:
    if argv and Path(argv[0]).is_absolute():
        executable = Path(argv[0]).resolve()
        if executable.is_relative_to(Path("/usr")):
            return [str(executable), *argv[1:]]
    return argv


def _resolve_volta_command(argv: list[str]) -> tuple[list[str], tuple[Path, ...], tuple[Path, ...]]:
    if not argv or Path(argv[0]).name not in {"node", "npm", "npx"}:
        return argv, (), ()
    host_command = shutil.which(argv[0])
    volta_bin = Path.home() / ".volta" / "bin"
    if not host_command or not Path(host_command).is_relative_to(volta_bin):
        return argv, (), ()
    images = volta_bin.parent / "tools" / "image" / "node"
    versions = [path for path in images.iterdir() if path.is_dir() and (path / "bin" / "node").is_file()] if images.is_dir() else []
    if not versions:
        raise SandboxUnavailable("Nenhuma instalação Node gerenciada pelo Volta foi encontrada para o sandbox.")
    def version_key(path: Path):
        return tuple(int(part) if part.isdigit() else 0 for part in path.name.split("."))
    image = max(versions, key=version_key)
    node = image / "bin" / "node"
    cli = image / "lib" / "node_modules" / "npm" / "bin" / ("npx-cli.js" if Path(argv[0]).name == "npx" else "npm-cli.js")
    if Path(argv[0]).name == "node":
        resolved = [str(node), *argv[1:]]
    elif cli.is_file():
        resolved = [str(node), str(cli), *argv[1:]]
    else:
        raise SandboxUnavailable("npm não está disponível no runtime Node do Volta.")
    return resolved, (image,), (image / "bin",)


@lru_cache(maxsize=1)
def workspace_sandbox_available() -> bool:
    if platform.system() != "Linux" or not shutil.which("bwrap"):
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="zc-sandbox-check-") as root:
            result = run_workspace_command(["/usr/bin/true"], root, timeout=5)
        return result.returncode == 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return False
