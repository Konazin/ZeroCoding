import json
import time
from threading import Event
from typing import Callable, Generator

from .context import ConversationContext
from .events import AgentEvent
from .permissions import approval_route, normalize_permission_mode, review_action
from .prompt import PROMPT_BUDGET_TOKENS, build_messages, estimate_tokens
from ..tools.registry import ToolRegistry
from ..tools.sandbox import SandboxUnavailable, workspace_sandbox_available


class Agent:
    def __init__(self, provider, skills=None, tools: ToolRegistry | None = None, max_tool_steps: int = 6, input_budget_tokens: int = 2048, output_budget_tokens: int = 512, prefer_text_tool_calls: bool = False, permission_mode: str = "manual"):
        self.provider = provider
        self.skills = skills or []
        self.active_skills = []
        self.context = ConversationContext()
        self.tools = tools or ToolRegistry()
        self.max_tool_steps = max_tool_steps
        self.input_budget_tokens = input_budget_tokens
        self.output_budget_tokens = output_budget_tokens
        self.prefer_text_tool_calls = prefer_text_tool_calls
        self.permission_mode = "manual"
        self.permission_warning = ""
        try:
            self.set_permission_mode(permission_mode)
        except SandboxUnavailable as exc:
            self.permission_warning = str(exc)
        self.last_metrics = {}

    def set_mode(self, mode):
        self.input_budget_tokens = mode.input_budget_tokens
        self.max_tool_steps = mode.max_tool_steps
        self.output_budget_tokens = mode.output_budget_tokens

    def set_permission_mode(self, mode: str) -> None:
        mode = normalize_permission_mode(mode)
        if mode == "full_access" and not workspace_sandbox_available():
            raise SandboxUnavailable("Full access exige Linux com bubblewrap (bwrap) funcional.")
        self.permission_mode = mode
        self.permission_warning = ""

    def use_skill(self, name: str) -> bool:
        return self.add_skill(name)

    def add_skill(self, name: str) -> bool:
        for skill in self.skills:
            if skill.name == name:
                if skill not in self.active_skills:
                    self.active_skills.append(skill)
                return True
        return False

    def remove_skill(self, name: str) -> bool:
        before = len(self.active_skills)
        self.active_skills = [skill for skill in self.active_skills if skill.name != name]
        return len(self.active_skills) != before

    def clear_skills(self) -> None:
        self.active_skills = []

    def set_active_skills(self, names: list[str]) -> list[str]:
        self.clear_skills()
        missing = []
        for name in names:
            if not self.add_skill(name):
                missing.append(name)
        return missing

    def active_skill_names(self) -> list[str]:
        return [skill.name for skill in self.active_skills]

    def ask(self, text, system_prompt=None, context_text="", approve: Callable | None = None, on_tool: Callable | None = None):
        response = []
        run = self._run(text, system_prompt, context_text, approve, on_tool)
        try:
            while True:
                response.append(next(run))
        except StopIteration as finished:
            return finished.value

    def ask_stream(self, text, system_prompt=None, context_text="", approve=None, on_tool=None, cancel_event: Event | None = None) -> Generator[str, None, None]:
        yield from self._run(text, system_prompt, context_text, approve, on_tool, cancel_event)

    def run_events(self, text, system_prompt=None, context_text="", approve=None, cancel_event=None, on_event=None):
        """Provider- and UI-independent typed stream; ask_stream remains a compatibility adapter."""
        event_started = time.perf_counter()
        pending = []
        def tool_event(event, tool, arguments, output=""):
            if event == "review":
                pending.append(AgentEvent("approval_result", {
                    "name": tool.name, "arguments": arguments, "output": output[:500],
                }))
                return
            pending.append(AgentEvent("tool_start" if event == "start" else "tool_result", {
                "event": event, "name": tool.name, "arguments": arguments, "output": output[:1200],
            }))
        tool_event.include_output = True
        def request_approval(tool, arguments):
            if on_event and approval_route(self.permission_mode, tool, arguments) == "manual":
                on_event(AgentEvent("approval_request", {"name": tool.name, "arguments": arguments}))
            return approve(tool, arguments) if approve else False
        stream = self.ask_stream(text, system_prompt, context_text, request_approval, tool_event, cancel_event)
        try:
            for token in stream:
                while pending:
                    yield pending.pop(0)
                yield AgentEvent("token", {"text": token})
            while pending:
                yield pending.pop(0)
            yield AgentEvent("metrics", dict(self.last_metrics))
            yield AgentEvent("cancelled" if cancel_event and cancel_event.is_set() else "done", {})
        except GeneratorExit:
            raise
        except Exception as exc:
            self.last_metrics.setdefault("duration_ms", round((time.perf_counter() - event_started) * 1000, 1))
            yield AgentEvent("metrics", dict(self.last_metrics))
            yield AgentEvent("error", {"message": str(exc)})

    def _run(self, text, system_prompt, context_text, approve, on_tool, cancel_event=None):
        started = time.perf_counter()
        tool_schemas = self.tools.schemas()
        native_tools = bool(getattr(self.provider, "supports_tools", False)) and not self.prefer_text_tool_calls
        schema_tokens = estimate_tokens(json.dumps(tool_schemas, ensure_ascii=False)) if native_tools and tool_schemas else 0
        output_reserve = self.output_budget_tokens
        prompt_instructions = system_prompt
        if tool_schemas and not native_tools:
            prompt_instructions = (system_prompt + "\n" if system_prompt else "") + (
                "If a tool is needed, return only strict JSON as {\"name\": tool_name, \"arguments\": {...}}. "
                "Available tools: " + json.dumps(tool_schemas, ensure_ascii=False)
            )
        messages = build_messages(
            user_text=text,
            system_prompt=prompt_instructions,
            context_text=context_text,
            history=self.context.history,
            skills=self.active_skills,
            budget_tokens=max(128, min(self.input_budget_tokens - schema_tokens, PROMPT_BUDGET_TOKENS - schema_tokens)),
        )
        build_ms = (time.perf_counter() - started) * 1000
        self.last_metrics = {"request_build_ms": round(build_ms, 1), "input_tokens_estimated": sum(estimate_tokens(m.get("content") or "") for m in messages) + schema_tokens, "input_budget": self.input_budget_tokens, "output_reserve": output_reserve, "tool_calls": 0, "first_token_ms": None, "duration_ms": None}
        calls_done = 0
        full_response = []
        for _ in range(self.max_tool_steps + 1):
            if cancel_event and cancel_event.is_set():
                self.last_metrics["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
                return ""
            response_parts = []
            calls = []
            deferred_text = []
            defer_json = False
            if tool_schemas and native_tools and hasattr(self.provider, "chat_stream_with_tools"):
                for event in self.provider.chat_stream_with_tools(messages, tool_schemas, max_output_tokens=self.output_budget_tokens):
                    if "usage" in event:
                        previous = self.last_metrics.setdefault("provider_usage", {})
                        for key, value in event["usage"].items():
                            if isinstance(value, (int, float)) and not isinstance(value, bool):
                                previous[key] = previous.get(key, 0) + value
                            else:
                                previous[key] = value
                    token = event.get("content", "")
                    if token:
                        if self.last_metrics["first_token_ms"] is None:
                            self.last_metrics["first_token_ms"] = round((time.perf_counter() - started) * 1000, 1)
                        response_parts.append(token)
                        candidate = "".join(response_parts)
                        if defer_json or not candidate.strip() or candidate.lstrip().startswith("{"):
                            defer_json = True
                            deferred_text.append(token)
                            if not candidate.lstrip().startswith("{") and candidate.strip():
                                defer_json = False
                                for part in deferred_text:
                                    full_response.append(part)
                                    yield part
                                deferred_text.clear()
                        else:
                            full_response.append(token)
                            yield token
                    if "tool_calls" in event:
                        calls = event["tool_calls"] or []
                if not calls:
                    text_calls = self._text_tool_calls("".join(response_parts))
                    if text_calls:
                        calls = text_calls
                        response_parts.clear()
                    else:
                        for part in deferred_text:
                            full_response.append(part)
                            yield part
            elif tool_schemas and native_tools:
                result = self.provider.chat_with_tools(messages, tool_schemas, max_output_tokens=self.output_budget_tokens)
                token = result.get("content", "") or ""
                if token:
                    response_parts.append(token)
                    if not result.get("tool_calls"):
                        text_calls = self._text_tool_calls(token)
                        if text_calls:
                            result["tool_calls"] = text_calls
                            response_parts.clear()
                    if not result.get("tool_calls"):
                        full_response.append(token)
                        yield token
                calls = result.get("tool_calls", []) or []
            else:
                stream = getattr(self.provider, "chat_stream", None)
                tokens = stream(messages=messages, max_output_tokens=self.output_budget_tokens) if stream else [self.provider.chat(messages=messages, max_output_tokens=self.output_budget_tokens)]
                deferred_text = []
                defer_json = False
                buffer_tool_text = bool(tool_schemas and self.prefer_text_tool_calls)
                for token in tokens:
                    if cancel_event and cancel_event.is_set():
                        return ""
                    if self.last_metrics["first_token_ms"] is None:
                        self.last_metrics["first_token_ms"] = round((time.perf_counter() - started) * 1000, 1)
                    response_parts.append(token)
                    candidate = "".join(response_parts)
                    if buffer_tool_text or defer_json or candidate.lstrip().startswith("{"):
                        defer_json = True
                        deferred_text.append(token)
                    else:
                        full_response.append(token)
                        yield token
                provider_usage = getattr(self.provider, "last_usage", None)
                if provider_usage:
                    previous = self.last_metrics.setdefault("provider_usage", {})
                    for key, value in provider_usage.items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            previous[key] = previous.get(key, 0) + value
                        else:
                            previous[key] = value
                if tool_schemas:
                    text_calls = self._text_tool_calls("".join(response_parts))
                    if text_calls:
                        calls = text_calls
                        response_parts.clear()
                    else:
                        for part in deferred_text:
                            full_response.append(part)
                            yield part
                elif deferred_text:
                    for part in deferred_text:
                        full_response.append(part)
                        yield part

            if not calls:
                answer = "".join(full_response)
                self.context.add_message("user", text)
                self.context.add_message("assistant", answer)
                self.last_metrics.update({"output_tokens_estimated": estimate_tokens(answer), "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
                return answer

            messages.append({"role": "assistant", "content": "".join(response_parts) or None, "tool_calls": calls})
            for raw_call in calls:
                call = raw_call.get("function", raw_call)
                name = call.get("name", "")
                tool = self.tools.get(name)
                call_id = raw_call.get("id", name)
                self.last_metrics["tool_calls"] += 1
                arguments = {}
                try:
                    if calls_done >= self.max_tool_steps:
                        raise ValueError("Tool-step limit reached; no further actions were run.")
                    arguments = call.get("arguments", {})
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be an object.")
                    if tool is None:
                        raise ValueError(f"Unknown tool: {name}")
                    self._validate_arguments(tool, arguments)
                    calls_done += 1
                    route = approval_route(self.permission_mode, tool, arguments)
                    sandboxed = self.permission_mode != "manual" and tool.permission_scope == "command" and workspace_sandbox_available()
                    if route == "review" and tool.permission_scope == "command" and not sandboxed:
                        route = "manual"
                    approved = route == "allow"
                    denial_reason = "Action declined by user."
                    if route == "manual":
                        approved = bool(approve and approve(tool, arguments))
                    elif route == "review":
                        approved, denial_reason = review_action(self.provider, text, tool, arguments)
                        if on_tool:
                            self._notify_tool(on_tool, "review", tool, arguments, f"Revisor {'aprovou' if approved else 'negou'}: {denial_reason}")
                    if route != "manual" and self.permission_mode != "manual" and tool.permission_scope == "command":
                        if tool.sandbox_handler is None:
                            approved = False
                            denial_reason = "Comando bloqueado: a ferramenta não oferece execução em sandbox."
                    if not approved:
                        output = f"{denial_reason} Nada foi executado."
                        if on_tool:
                            self._notify_tool(on_tool, "denied", tool, arguments, output)
                    else:
                        if on_tool:
                            self._notify_tool(on_tool, "start", tool, arguments)
                        handler = tool.sandbox_handler if sandboxed and tool.sandbox_handler else tool.handler
                        output = str(handler(arguments))
                        if on_tool:
                            self._notify_tool(on_tool, "done", tool, arguments, output)
                except Exception as exc:
                    output = f"Tool error: {exc}"
                    if on_tool and tool:
                        self._notify_tool(on_tool, "error", tool, arguments, output)
                messages.append({"role": "tool", "tool_call_id": call_id, "name": name, "content": output[:6000]})

        message = "Stopped after reaching the tool-step limit."
        self.context.add_message("user", text)
        self.context.add_message("assistant", message)
        self.last_metrics.update({"output_tokens_estimated": estimate_tokens("".join(full_response)), "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        yield message
        return message

    def _text_tool_call(self, content):
        """Compatibility helper for consumers that expect one text tool call."""
        calls = self._text_tool_calls(content)
        return calls[0] if len(calls) == 1 else None

    def _text_tool_calls(self, content):
        """Parse strict tool-call JSON, allowing surrounding text only in local text-tool mode."""
        if not isinstance(content, str) or not content.strip():
            return []

        decoder = json.JSONDecoder()
        calls = []
        position = 0
        while position < len(content):
            if self.prefer_text_tool_calls:
                start = content.find("{", position)
                if start < 0:
                    break
            else:
                while position < len(content) and content[position].isspace():
                    position += 1
                if position == len(content):
                    break
                start = position
            try:
                value, end = decoder.raw_decode(content, start)
            except json.JSONDecodeError:
                if self.prefer_text_tool_calls:
                    position = start + 1
                    continue
                return []
            position = end
            if not isinstance(value, dict) or set(value) != {"name", "arguments"}:
                if not self.prefer_text_tool_calls:
                    return []
                continue
            name, arguments = value["name"], value["arguments"]
            tool = self.tools.get(name) if isinstance(name, str) else None
            if tool is None or not isinstance(arguments, dict):
                if not self.prefer_text_tool_calls:
                    return []
                continue
            try:
                self._validate_arguments(tool, arguments)
            except ValueError:
                if not self.prefer_text_tool_calls:
                    return []
                continue
            calls.append({
                "id": f"text-{name}-{len(calls)}",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            })
        return calls

    @staticmethod
    def _validate_arguments(tool, arguments):
        schema = tool.input_schema or {}
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in arguments]
        if missing:
            raise ValueError("Missing required argument(s): " + ", ".join(missing))
        if schema.get("additionalProperties") is False and set(arguments) - set(properties):
            raise ValueError("Unknown argument(s): " + ", ".join(sorted(set(arguments) - set(properties))))
        expected = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
        for key, value in arguments.items():
            rule = properties.get(key, {})
            kind = rule.get("type")
            if kind in expected:
                types = expected[kind]
                if not isinstance(value, types) or (kind in {"integer", "number"} and isinstance(value, bool)):
                    raise ValueError(f"Argument {key!r} must be {kind}.")
            if kind == "array" and isinstance(value, list) and rule.get("items", {}).get("type") == "string" and not all(isinstance(item, str) for item in value):
                raise ValueError(f"Argument {key!r} must contain only strings.")

    @staticmethod
    def _notify_tool(callback, event, tool, arguments, output=""):
        if getattr(callback, "include_output", False):
            callback(event, tool, arguments, output)
        else:
            callback(event, tool, arguments)
