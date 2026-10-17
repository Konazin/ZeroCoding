"""Minimal MCP client over stdio (newline-delimited JSON-RPC 2.0). Local servers only; no SDK dependency."""
from __future__ import annotations

import json
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

PROTOCOL_VERSION = "2025-03-26"


class McpError(Exception):
    """Transport, protocol or server failure with a message safe to show the user and the model."""


class McpClient:
    def __init__(self, name: str, argv: list[str], env: dict[str, str], cwd: str | Path,
                 startup_timeout: float = 10, call_timeout: float = 30):
        self.name, self.argv, self.env, self.cwd = name, list(argv), dict(env), str(cwd)
        self.startup_timeout, self.call_timeout = startup_timeout, call_timeout
        self.server_info: dict = {}
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Condition()
        self._responses: dict[int, dict] = {}
        self._next_id = 0
        self._eof = False
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._write_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------------------------------
    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.cwd, env=self.env, text=True, bufsize=1, shell=False,
            )
        except FileNotFoundError:
            raise McpError(f"command not found: {self.argv[0]}") from None
        except OSError as exc:
            raise McpError(f"could not start server: {exc}") from None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            result = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "zerocoding", "version": "0.2.0"},
            }, self.startup_timeout)
            self.server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
            self._notify("notifications/initialized")
        except McpError:
            self.close()
            raise

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._eof

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    # -- protocol ------------------------------------------------------------------------------------
    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _page in range(20):  # pagination guard
            result = self._request("tools/list", {"cursor": cursor} if cursor else {}, self.startup_timeout)
            tools.extend(t for t in (result.get("tools") or []) if isinstance(t, dict) and t.get("name"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool: str, arguments: dict) -> tuple[str, bool]:
        """Return (text, is_error). Raises McpError on transport/protocol failure."""
        result = self._request("tools/call", {"name": tool, "arguments": arguments or {}}, self.call_timeout)
        parts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict):
                parts.append(f"[{item.get('type', 'unknown')} content omitted]")
        return "\n".join(parts), bool(result.get("isError"))

    def _send(self, message: dict) -> None:
        if not self.alive:
            raise McpError(f"server '{self.name}' is not running{self._stderr_hint()}")
        try:
            with self._write_lock:
                self._proc.stdin.write(json.dumps(message) + "\n")
                self._proc.stdin.flush()
        except (OSError, ValueError):
            raise McpError(f"server '{self.name}' closed its input{self._stderr_hint()}") from None

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def _request(self, method: str, params: dict, timeout: float) -> dict:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        with self._lock:
            while request_id not in self._responses:
                if self._eof or not self.alive:
                    raise McpError(f"server '{self.name}' exited during {method}{self._stderr_hint()}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpError(f"{method} timed out after {timeout:g}s")
                self._lock.wait(min(remaining, 0.5))
            message = self._responses.pop(request_id)
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise McpError(f"{method} failed: {str(error.get('message', 'unknown error'))[:300]}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    # -- reader threads ----------------------------------------------------------------------------
    def _read_stdout(self) -> None:
        proc = self._proc
        try:
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # servers may print non-protocol noise
                if not isinstance(message, dict):
                    continue
                if "method" in message and "id" in message:  # server-to-client request
                    self._answer_server_request(message)
                elif "id" in message and ("result" in message or "error" in message):
                    with self._lock:
                        self._responses[message["id"]] = message
                        self._lock.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self._eof = True
                self._lock.notify_all()

    def _answer_server_request(self, message: dict) -> None:
        if message.get("method") == "ping":
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        else:  # we advertise no capabilities, so refuse everything else
            reply = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Method not supported"}}
        try:
            self._send(reply)
        except McpError:
            pass

    def _read_stderr(self) -> None:
        try:
            for line in self._proc.stderr:
                self._stderr_tail.append(line.rstrip()[:200])
        except (OSError, ValueError, AttributeError):
            pass

    def _stderr_hint(self) -> str:
        return f" (stderr: {' | '.join(list(self._stderr_tail)[-3:])})" if self._stderr_tail else ""
