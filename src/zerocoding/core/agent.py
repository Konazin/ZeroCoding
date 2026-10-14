from __future__ import annotations

import json
import re
import time
import uuid
from typing import Generator

from .context import ConversationContext
from .events import AgentEvent
from .prompt import build_messages
from .relevance import select_skills, select_tool_schemas
from .tools import READ_ONLY_TOOL_NAMES
from ..providers.base import ProviderTurn, ToolCall, normalize_turn


COMPACT_CALL = re.compile(r"<tool_call>\s*(\{.*\})\s*</tool_call>", re.DOTALL)


def estimate_tokens(value) -> int:
    return max(1, (len(json.dumps(value, ensure_ascii=False)) + 3) // 4)


def fit_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """Fit a prompt while keeping the current request and its tool results."""
    result = [dict(message) for message in messages]
    while estimate_tokens(result) > max_tokens:
        latest_user = max((i for i, msg in enumerate(result) if msg.get("role") == "user"), default=-1)
        removable = next((i for i, msg in enumerate(result)
                          if msg.get("role") != "system" and i != latest_user and i < latest_user), None)
        if removable is None:
            break
        result.pop(removable)
    if estimate_tokens(result) > max_tokens:
        # Tool outputs are expendable once they have been returned to the model.
        outputs = [msg for msg in result if msg.get("role") == "tool"]
        while outputs and estimate_tokens(result) > max_tokens:
            largest = max(outputs, key=lambda msg: len(str(msg.get("content", ""))))
            content = str(largest.get("content", ""))
            if len(content) <= 80:
                outputs.remove(largest)
                result.remove(largest)
            else:
                largest["content"] = content[: max(80, len(content) // 2)]
    if estimate_tokens(result) > max_tokens and result:
        system = next((m for m in result if m.get("role") == "system"), {"role": "system", "content": ""})
        current = next((m for m in reversed(result) if m.get("role") == "user"), result[-1])
        available_chars = max(80, (max_tokens - 80) * 3)
        current["content"] = str(current.get("content", ""))[-max(80, available_chars // 2):]
        system["content"] = str(system.get("content", ""))[:available_chars // 2]
        result = [system, current]
    return result


class Agent:
    def __init__(self, provider, memory=None, skills=None, max_input_tokens=4096,
                 max_output_tokens=1024, max_tool_rounds=6, tools=None,
                 effort_profiles=None, effort="medium", plan_mode=False, ultrathink=False,
                 dynamic_context=False):
        self.provider = provider
        self.dynamic_context = bool(dynamic_context)
        self.memory = memory  # retained for API compatibility; global history is never injected.
        self.skills = skills or []
        self.active_skills = []
        self.context = ConversationContext()
        self.max_input_tokens = max(256, int(max_input_tokens))
        self.max_output_tokens = max(128, int(max_output_tokens))
        self.max_tool_rounds = max(1, min(12, int(max_tool_rounds)))
        self.tools = tools
        self.effort_profiles = effort_profiles or {
            "low": {"max_output_tokens": 512, "max_tool_rounds": 3},
            "medium": {"max_output_tokens": self.max_output_tokens, "max_tool_rounds": self.max_tool_rounds},
            "high": {"max_output_tokens": self.max_output_tokens * 2, "max_tool_rounds": min(12, self.max_tool_rounds + 2)},
        }
        self.set_session_controls(plan_mode=plan_mode, ultrathink=ultrathink, effort=effort)

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

    def set_session_controls(self, *, plan_mode=None, ultrathink=None, effort=None) -> None:
        if plan_mode is not None:
            self.plan_mode = bool(plan_mode)
        if ultrathink is not None:
            self.ultrathink = bool(ultrathink)
        if effort is not None:
            value = str(effort).lower()
            self.effort = value if value in {"low", "medium", "high"} else "medium"

    def effective_budgets(self) -> tuple[int, int]:
        profile = self.effort_profiles.get(self.effort, self.effort_profiles.get("medium", {}))
        if isinstance(profile, dict):
            output_tokens = int(profile.get("max_output_tokens", self.max_output_tokens))
            tool_rounds = int(profile.get("max_tool_rounds", self.max_tool_rounds))
        else:
            output_tokens = int(getattr(profile, "max_output_tokens", self.max_output_tokens))
            tool_rounds = int(getattr(profile, "max_tool_rounds", self.max_tool_rounds))
        if self.ultrathink:
            output_tokens += 1024
            tool_rounds += 2
        return max(128, output_tokens), max(1, min(12, tool_rounds))

    def native_effort_supported(self) -> bool:
        method = getattr(self.provider, "native_effort_kwargs", None)
        return bool(method and method(self.effort))

    def native_effort_status(self) -> str:
        method = getattr(self.provider, "native_effort_kwargs", None)
        if not method or not method(self.effort):
            return "budget only (not declared by provider)"
        describe = getattr(self.provider, "native_effort_status", None)
        return str(describe(self.effort)) if callable(describe) else "supported by provider"

    def _messages(self, text, system_prompt):
        instructions = []
        if self.plan_mode:
            instructions.append(
                "Plan mode is read-only. Explore with available read-only project tools and return a concise plan; do not modify files or run commands."
            )
        if self.ultrathink:
            instructions.append(
                "Analyze the task carefully and check the result for important edge cases before answering. Keep the response concise and do not reveal private reasoning steps."
            )
        if instructions:
            base_prompt = system_prompt or (
                "You are ZeroCoding, a concise coding assistant. Use project tools to inspect files. "
                "Propose changes clearly; file writes and commands require user approval."
            )
            system_prompt = base_prompt + "\n\n" + "\n".join(instructions)
        skills = select_skills(text, self.active_skills) if self.dynamic_context else self.active_skills
        messages = build_messages(text, system_prompt, history=self.context.history, skills=skills)
        return fit_messages(messages, self.max_input_tokens)

    @staticmethod
    def _kwargs(output_tokens):
        return {"max_tokens": output_tokens}

    def ask(self, text, system_prompt=None, use_tools=False, on_event=None):
        output_tokens, tool_round_limit = self.effective_budgets()
        messages = self._messages(text, system_prompt)
        if use_tools and self.tools:
            tool_schemas = self.tools.read_only_schemas if self.plan_mode else self.tools.schemas
            if self.dynamic_context and not self.plan_mode:
                tool_schemas = select_tool_schemas(text, tool_schemas)
        else:
            tool_schemas = None
        tool_budget = self.max_input_tokens
        if tool_schemas:
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] += ' When native calls are unavailable, emit one exact <tool_call>{"name":"tool_name","arguments":{}}</tool_call> marker.'
            tool_budget = max(256, self.max_input_tokens - estimate_tokens(tool_schemas))
            messages = fit_messages(messages, tool_budget)
        native_tools = bool(tool_schemas)

        def request_turn():
            nonlocal native_tools
            self._emit(on_event, AgentEvent("thinking"))
            kwargs = {"num_ctx": self.max_input_tokens + output_tokens, **self._kwargs(output_tokens)}
            effort_level = "high" if self.ultrathink else self.effort
            native_effort = getattr(self.provider, "native_effort_kwargs", lambda _level: None)(effort_level)
            if native_effort:
                kwargs.update(native_effort)
            if native_tools:
                try:
                    return normalize_turn(self.provider.chat(messages=messages, tools=tool_schemas, **kwargs))
                except RuntimeError as exc:
                    reason = str(exc).lower()
                    if not any(term in reason for term in ("tool", "unsupported", "not support")):
                        raise
                    native_tools = False
            return normalize_turn(self.provider.chat(messages=messages, tools=None, **kwargs))

        turn = request_turn()
        if not turn.tool_calls and not turn.content.strip():
            turn = request_turn()
            if not turn.tool_calls and not turn.content.strip():
                raise RuntimeError(
                    "The model returned an empty response twice. Check the llama.cpp chat template and reasoning settings, then try again."
                )
        rounds = 0
        tool_round_completed = False
        while True:
            turn = self._parse_compact(turn)
            if not turn.tool_calls or not tool_schemas or rounds >= tool_round_limit:
                response_text = turn.content or ("Tool round limit reached." if turn.tool_calls else "")
                if tool_round_completed and not response_text.strip():
                    raise RuntimeError(
                        "The model returned an empty response after a tool result. Check the llama.cpp chat template and reasoning settings."
                    )
                break
            calls = [call for call in turn.tool_calls if call.name]
            if not calls:
                if turn.content.strip():
                    response_text = turn.content
                    break
                raise RuntimeError("The model returned a tool call without a valid function name.")
            call_ids = [call.call_id or f"call_{uuid.uuid4().hex[:10]}" for call in calls]
            assistant_message = {
                "role": "assistant",
                "content": turn.content or "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call, call_id in zip(calls, call_ids)
                ],
            }
            if turn.reasoning_content:
                assistant_message["reasoning_content"] = turn.reasoning_content
            messages.append(assistant_message)
            for call, call_id in zip(calls, call_ids):
                started_at = time.monotonic()
                target = self._tool_target(call.name, call.arguments)
                self._emit(on_event, AgentEvent("tool_started", call.name, target))
                if self.plan_mode and call.name not in READ_ONLY_TOOL_NAMES:
                    result = f"Tool '{call.name}' is blocked in Plan mode. No action was taken."
                    event_kind = "tool_denied"
                else:
                    try:
                        execute_with_events = getattr(self.tools, "execute_with_events", None)
                        if on_event and callable(execute_with_events):
                            result = execute_with_events(
                                call.name, call.arguments, on_event, plan_mode=self.plan_mode
                            )
                        else:
                            result = self.tools.execute(call.name, call.arguments, plan_mode=self.plan_mode)
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                        event_kind = "tool_error"
                    else:
                        result_text = str(result)
                        event_kind = "tool_denied" if "denied" in result_text.lower() or "nothing was executed" in result_text.lower() else "tool_completed"
                self._emit(on_event, AgentEvent(
                    event_kind,
                    call.name,
                    target,
                    self._tool_summary(call.name, str(result)),
                    time.monotonic() - started_at,
                ))
                format_result = getattr(self.provider, "tool_result_message", None)
                if format_result:
                    tool_message = format_result(call_id, call.name, str(result)[:8000])
                else:
                    tool_message = {"role": "tool", "tool_call_id": call_id,
                                    "name": call.name, "content": str(result)[:8000]}
                messages.append(tool_message)
            rounds += 1
            tool_round_completed = True
            messages = fit_messages(messages, tool_budget)
            turn = request_turn()
        self.context.add_message("user", text)
        self.context.add_message("assistant", response_text)
        return response_text

    @staticmethod
    def _emit(callback, event: AgentEvent) -> None:
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            # A presentation callback must never break the agent's tool loop.
            return

    @staticmethod
    def _tool_target(name: str, arguments: dict) -> str:
        value = arguments.get("path") or arguments.get("pattern") or arguments.get("command") or ""
        target = " ".join(str(value).split())
        return target if len(target) <= 96 else target[:93] + "…"

    @staticmethod
    def _tool_summary(name: str, result: str) -> str:
        value = result.strip()
        lower = value.lower()
        if "denied by user" in lower or "nothing was executed" in lower:
            return "Denied · no action taken"
        if value.startswith("Tool error:"):
            return "Tool error"
        lines = [line for line in value.splitlines() if line.strip()]
        if name == "read_file":
            return f"{len(lines)} lines read"
        if name == "list_files":
            if lower == "no files found.":
                return "0 files"
            return f"{len(lines)} files listed"
        if name == "search_files":
            if lower == "no matches found.":
                return "0 matches"
            return f"{len(lines)} matches"
        if name == "run_command":
            exit_code = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("exit code:")), "unknown")
            output_lines = max(0, len(lines) - 1)
            return f"exit {exit_code} · {output_lines} output lines"
        if name == "write_file":
            return "File written" if value.lower().startswith("wrote ") else "Completed"
        if len(lines) > 1:
            return f"Completed · {len(lines)} lines"
        return f"Completed · {len(value)} characters" if value else "Completed"

    @staticmethod
    def _parse_compact(turn: ProviderTurn) -> ProviderTurn:
        if turn.tool_calls:
            return turn
        match = COMPACT_CALL.search(turn.content)
        if not match:
            return turn
        try:
            payload = json.loads(match.group(1))
            name = payload.get("name") or payload.get("tool")
            args = payload.get("arguments", payload.get("parameters", {}))
            if name and isinstance(args, dict):
                content = (turn.content[:match.start()] + turn.content[match.end():]).strip()
                return ProviderTurn(
                    content=content,
                    tool_calls=[ToolCall(str(name), args)],
                    usage=turn.usage,
                    thinking_present=turn.thinking_present,
                    reasoning_content=turn.reasoning_content,
                )
        except (ValueError, TypeError):
            pass
        return turn

    def ask_stream(self, text, system_prompt=None, use_tools=False, on_event=None) -> Generator[str, None, None]:
        """Compatibility wrapper that yields the complete answer as one item."""
        response = self.ask(text, system_prompt=system_prompt, use_tools=use_tools, on_event=on_event)
        yield response
