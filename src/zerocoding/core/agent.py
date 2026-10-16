from __future__ import annotations

import time
import uuid
from typing import Generator

from .budget import fit_messages
from .cancel import TurnCancelled
from .context import ConversationContext
from .events import AgentEvent
from .prompt import build_messages
from .relevance import select_skills, select_tool_schemas
from .tokens import TokenCounter
from .toolcalls import emit_event, parse_compact_call, tool_summary, tool_target
from .tools import READ_ONLY_TOOL_NAMES
from ..providers.base import normalize_turn

__all__ = ["Agent", "fit_messages"]


class Agent:
    def __init__(self, provider, memory=None, skills=None, max_input_tokens=4096,
                 max_output_tokens=1024, max_tool_rounds=6, tools=None,
                 effort_profiles=None, effort="medium", plan_mode=False, ultrathink=False,
                 dynamic_context=False):
        self.provider = provider
        self.token_counter = TokenCounter(provider)
        self.metrics_sink = None  # optional callable(dict): receives one stats dict per turn
        self.last_turn: dict = {}
        self.extensions = None  # core.extensions.Extensions, set by the CLI
        self._stats: dict = self._new_stats()
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
        return self._fit(messages, self.max_input_tokens)

    def _fit(self, messages, budget):
        fitted = fit_messages(messages, budget, self.token_counter)
        self._stats["trimmed_messages"] += max(0, len(messages) - len(fitted))
        return fitted

    @staticmethod
    def _kwargs(output_tokens):
        return {"max_tokens": output_tokens}

    def _tool_schemas_for(self, text, use_tools):
        if not (use_tools and self.tools):
            return None
        schemas = self.tools.read_only_schemas if self.plan_mode else self.tools.schemas
        if self.dynamic_context and not self.plan_mode:
            schemas = select_tool_schemas(text, schemas)
        return schemas

    def _chat(self, messages, tool_schemas, output_tokens, state, on_event):
        """One provider call; drops native tools for the rest of the ask if the server rejects them."""
        if state.get("cancel"):
            state["cancel"].check()
        emit_event(on_event, AgentEvent("thinking"))
        turn = self._chat_once(messages, tool_schemas, output_tokens, state)
        usage = turn.usage or {}
        self._stats["llm_calls"] += 1
        self._stats["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        self._stats["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        return turn

    def _chat_once(self, messages, tool_schemas, output_tokens, state):
        kwargs = {"num_ctx": self.max_input_tokens + output_tokens, **self._kwargs(output_tokens)}
        effort_level = "high" if self.ultrathink else self.effort
        native_effort = getattr(self.provider, "native_effort_kwargs", lambda _level: None)(effort_level)
        if native_effort:
            kwargs.update(native_effort)
        if state["native_tools"]:
            try:
                return normalize_turn(self.provider.chat(messages=messages, tools=tool_schemas, **kwargs))
            except RuntimeError as exc:
                reason = str(exc).lower()
                if not any(term in reason for term in ("tool", "unsupported", "not support")):
                    raise
                state["native_tools"] = False
        return normalize_turn(self.provider.chat(messages=messages, tools=None, **kwargs))

    def _chat_non_empty(self, *args):
        """Ask once more if the first turn is empty; raise a clear error if it stays empty."""
        for _attempt in range(2):
            turn = self._chat(*args)
            if turn.tool_calls or turn.content.strip():
                return turn
        raise RuntimeError(
            "The model returned an empty response twice. Check the llama.cpp chat template and reasoning settings, then try again."
        )

    def _run_tool_call(self, call, call_id, on_event, cancel=None) -> dict:
        """Execute one tool call (Plan-mode guarded), emit events and return the tool message."""
        if cancel:
            cancel.check()
        self._stats["tool_calls"] += 1
        started_at = time.monotonic()
        target = tool_target(call.name, call.arguments)
        emit_event(on_event, AgentEvent("tool_started", call.name, target))
        if self.plan_mode and call.name not in READ_ONLY_TOOL_NAMES:
            result = f"Tool '{call.name}' is blocked in Plan mode. No action was taken."
            event_kind = "tool_denied"
        else:
            try:
                execute_with_events = getattr(self.tools, "execute_with_events", None)
                if on_event and callable(execute_with_events):
                    result = execute_with_events(call.name, call.arguments, on_event, plan_mode=self.plan_mode)
                else:
                    result = self.tools.execute(call.name, call.arguments, plan_mode=self.plan_mode)
            except Exception as exc:
                result = f"Tool error: {exc}"
                event_kind = "tool_error"
            else:
                result_text = str(result).lower()
                event_kind = "tool_denied" if "denied" in result_text or "nothing was executed" in result_text else "tool_completed"
        if event_kind == "tool_error":
            self._stats["tool_errors"] += 1
        elif event_kind == "tool_denied":
            self._stats["tool_denied"] += 1
        emit_event(on_event, AgentEvent(
            event_kind, call.name, target, tool_summary(call.name, str(result)), time.monotonic() - started_at,
        ))
        format_result = getattr(self.provider, "tool_result_message", None)
        if format_result:
            return format_result(call_id, call.name, str(result)[:8000])
        return {"role": "tool", "tool_call_id": call_id, "name": call.name, "content": str(result)[:8000]}

    @staticmethod
    def _new_stats() -> dict:
        return {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0,
                "tool_errors": 0, "tool_denied": 0, "trimmed_messages": 0}

    def ask(self, text, system_prompt=None, use_tools=False, on_event=None, cancel=None):
        """Answer one request. ``cancel`` (CancelToken) is checked between provider calls and tool calls;
        a cancelled or failed turn leaves the session history untouched."""
        self._stats = self._new_stats()
        started = time.monotonic()
        outcome = "error"
        try:
            result = self._ask(text, system_prompt, use_tools, on_event, cancel)
            outcome = "ok"
            return result
        except (KeyboardInterrupt, TurnCancelled):
            outcome = "cancelled"
            raise
        finally:
            stats = {"ts": round(time.time()), "outcome": outcome, "duration_s": round(time.monotonic() - started, 2),
                     "effort": self.effort, "plan_mode": self.plan_mode, "ultrathink": self.ultrathink, **self._stats}
            self.last_turn = stats
            if self.metrics_sink:
                try:
                    self.metrics_sink(stats)
                except Exception:
                    pass

    def _ask(self, text, system_prompt, use_tools, on_event, cancel):
        output_tokens, tool_round_limit = self.effective_budgets()
        messages = self._messages(text, system_prompt)
        tool_schemas = self._tool_schemas_for(text, use_tools)
        tool_budget = self.max_input_tokens
        if tool_schemas:
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] += ' When native calls are unavailable, emit one exact <tool_call>{"name":"tool_name","arguments":{}}</tool_call> marker.'
            tool_budget = max(256, self.max_input_tokens - self.token_counter(tool_schemas))
            messages = self._fit(messages, tool_budget)
        state = {"native_tools": bool(tool_schemas), "cancel": cancel}

        turn = self._chat_non_empty(messages, tool_schemas, output_tokens, state, on_event)
        rounds = 0
        tool_round_completed = False
        while True:
            turn = parse_compact_call(turn)
            if not turn.tool_calls or not tool_schemas or rounds >= tool_round_limit:
                response_text = turn.content or (
                    f"Tool round limit reached ({tool_round_limit} rounds). Ask me to continue, or raise /effort."
                    if turn.tool_calls else ""
                )
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
                    {"id": call_id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                    for call, call_id in zip(calls, call_ids)
                ],
            }
            if turn.reasoning_content:
                assistant_message["reasoning_content"] = turn.reasoning_content
            messages.append(assistant_message)
            for call, call_id in zip(calls, call_ids):
                messages.append(self._run_tool_call(call, call_id, on_event, cancel))
            rounds += 1
            tool_round_completed = True
            messages = self._fit(messages, tool_budget)
            turn = self._chat(messages, tool_schemas, output_tokens, state, on_event)
        self.context.add_message("user", text)
        self.context.add_message("assistant", response_text)
        return response_text

    def ask_stream(self, text, system_prompt=None, use_tools=False, on_event=None, cancel=None) -> Generator[str, None, None]:
        """Compatibility wrapper that yields the complete answer as one item."""
        response = self.ask(text, system_prompt=system_prompt, use_tools=use_tools, on_event=on_event, cancel=cancel)
        yield response
