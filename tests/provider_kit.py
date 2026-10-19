"""Fake model servers for provider conformance tests (llama.cpp, generic OpenAI-compatible, native Ollama).

Each backend speaks the real wire format of the thing it imitates, scripts the model's turns, and records
every request body so tests can check what the provider actually sent. No model, no network beyond localhost.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeBackend:
    def __init__(self, kind: str, *, n_ctx: int | None = 8192, props: bool = True, model_max: int | None = None,
                 lmstudio_loaded: int | None = None):
        self.kind = kind  # "llama_cpp" | "openai" | "ollama"
        self.n_ctx, self.props, self.model_max, self.lmstudio_loaded = n_ctx, props, model_max, lmstudio_loaded
        self.script: list[dict] = []
        self.requests: list[tuple[str, dict]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)

    # ---------------------------------------------------------------- lifecycle
    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @property
    def root(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    @property
    def base_url(self) -> str:
        return self.root if self.kind == "ollama" else self.root + "/v1"

    def next_turn(self) -> dict:
        return self.script.pop(0) if self.script else {"content": "ok"}

    def bodies(self, path: str) -> list[dict]:
        return [body for p, body in self.requests if p == path]

    # ---------------------------------------------------------------- wire formats
    def _openai_message(self, turn: dict) -> dict:
        message = {"role": "assistant", "content": turn.get("content", "")}
        if turn.get("reasoning"):
            message["reasoning_content"] = turn["reasoning"]
        if turn.get("tool_calls"):
            message["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                                      "function": {"name": name, "arguments": json.dumps(args)}}
                                     for i, (name, args) in enumerate(turn["tool_calls"])]
        return message

    def _openai_body(self, turn: dict) -> dict:
        usage = {"prompt_tokens": 10, "completion_tokens": 5, **turn.get("usage", {})}
        finish = turn.get("finish", "tool_calls" if turn.get("tool_calls") else "stop")
        return {"choices": [{"message": self._openai_message(turn), "finish_reason": finish}], "usage": usage}

    def _openai_stream(self, turn: dict) -> list[str]:
        events = []
        if turn.get("reasoning"):
            events.append({"choices": [{"delta": {"reasoning_content": turn["reasoning"]}}]})
        for piece in [turn.get("content", "")[:3], turn.get("content", "")[3:]]:
            if piece:
                events.append({"choices": [{"delta": {"content": piece}}]})
        for index, (name, args) in enumerate(turn.get("tool_calls", [])):
            raw = json.dumps(args)
            events.append({"choices": [{"delta": {"tool_calls": [{"index": index, "id": f"call_{index}",
                           "function": {"name": name, "arguments": raw[:5]}}]}}]})
            events.append({"choices": [{"delta": {"tool_calls": [{"index": index, "function": {"arguments": raw[5:]}}]}}]})
        finish = turn.get("finish", "tool_calls" if turn.get("tool_calls") else "stop")
        events.append({"choices": [{"delta": {}, "finish_reason": finish}]})
        events.append({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, **turn.get("usage", {})}})
        return [f"data: {json.dumps(event)}\n\n" for event in events] + ["data: [DONE]\n\n"]

    def _ollama_body(self, turn: dict) -> dict:
        message = {"role": "assistant", "content": turn.get("content", "")}
        if turn.get("reasoning"):
            message["thinking"] = turn["reasoning"]
        if turn.get("tool_calls"):
            message["tool_calls"] = [{"function": {"name": name, "arguments": args}} for name, args in turn["tool_calls"]]
        return {"message": message, "done": True, "done_reason": turn.get("finish", "stop"),
                "prompt_eval_count": 10, "eval_count": 5}

    # ---------------------------------------------------------------- routing
    def _handler(self):
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body, content_type="application/json"):
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                backend.requests.append((self.path, {}))
                if self.path == "/health" and backend.kind == "llama_cpp":
                    return self._send(200, {"status": "ok"})
                if self.path == "/props" and backend.kind == "llama_cpp" and backend.props:
                    return self._send(200, {"default_generation_settings": {"n_ctx": backend.n_ctx}, "total_slots": 1,
                                            "model_alias": "fake"})
                if self.path == "/v1/models":
                    entry = {"id": "fake"}
                    if backend.kind == "openai" and backend.model_max:
                        entry["max_model_len"] = backend.model_max
                    return self._send(200, {"data": [entry]})
                if self.path == "/api/v0/models/fake" and backend.lmstudio_loaded:
                    return self._send(200, {"id": "fake", "loaded_context_length": backend.lmstudio_loaded})
                if self.path == "/api/tags" and backend.kind == "ollama":
                    return self._send(200, {"models": [{"name": "fake"}]})
                if self.path == "/api/ps" and backend.kind == "ollama":
                    loaded = [{"name": "fake", "context_length": backend.n_ctx}] if backend.n_ctx else []
                    return self._send(200, {"models": loaded})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                backend.requests.append((self.path, body))
                if self.path == "/v1/chat/completions" and backend.kind in {"llama_cpp", "openai"}:
                    turn = backend.next_turn()
                    if body.get("stream"):
                        return self._send(200, "".join(backend._openai_stream(turn)), "text/event-stream")
                    return self._send(200, backend._openai_body(turn))
                if self.path == "/api/chat" and backend.kind == "ollama":
                    return self._send(200, backend._ollama_body(backend.next_turn()))
                if self.path == "/api/show" and backend.kind == "ollama":
                    info = {"general.architecture": "fake"}
                    if backend.model_max:
                        info["fake.context_length"] = backend.model_max
                    return self._send(200, {"model_info": info})
                if self.path == "/tokenize" and backend.kind == "llama_cpp":
                    return self._send(200, {"tokens": list(range(len(str(body.get("content", "")).split())))})
                if self.path == "/apply-template" and backend.kind == "llama_cpp":
                    return self._send(200, {"prompt": " ".join(m.get("content") or "" for m in body.get("messages", []))})
                self._send(404, {"error": "not found"})

        return Handler
