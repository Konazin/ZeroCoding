from __future__ import annotations

import json
import time
import uuid
from typing import Generator

from .budget import compact_tool_results, count_prompt, digest_turns, fit_messages, turn_groups
from .cancel import TurnCancelled
from .context import ConversationContext
from .events import AgentEvent
from .prompt import DEFAULT_SYSTEM_PROMPT, build_messages
from .relevance import select_skills, select_tool_schemas
from .tokens import TokenCounter
from .toolcalls import CHANGING_TOOLS, emit_event, parse_compact_call, shell_calls_from_text, tool_summary, tool_target, tool_was_denied
from .tools import READ_ONLY_TOOL_NAMES
from .config import MAX_TOOL_ROUNDS
from ..providers.base import normalize_turn

__all__ = ["Agent", "fit_messages"]

REPEAT_LIMIT = 3  # identical consecutive tool calls tolerated before the loop is stopped
COMPACT_AT = 0.7  # fraction of the input budget that triggers compaction
WINDOW_MARGIN = 128  # tokens kept free for template overhead and counting error


class Agent:
    def __init__(self, provider, memory=None, skills=None, max_input_tokens=4096,
                 context_window=0, max_output_tokens=1024, max_tool_rounds=40, tools=None,
                 effort_profiles=None, effort="medium", plan_mode=False, ultrathink=False,
                 dynamic_context=False, streaming_enabled=False, shell_block_fallback=True):
        self.provider = provider
        self.token_counter = TokenCounter(provider)
        self.metrics_sink = None  # optional callable(dict): receives one stats dict per turn
        self.last_turn: dict = {}
        self.extensions = None  # core.extensions.Extensions, set by the CLI
        self.instructions = None  # core.instructions.Instructions | None, loaded from the workspace by the CLI
        self.last_verification = None  # the last VerifyResult of the most recent request, for headless exit codes
        self.verifier = None  # core.verify.Verifier | None: re-runs the project's checks after the agent edits files
        self.hooks = None  # core.hooks.HookRunner | None
        self._stats: dict = self._new_stats()
        self.dynamic_context = bool(dynamic_context)
        self.streaming_enabled = bool(streaming_enabled)
        self.shell_block_fallback = bool(shell_block_fallback)
        self.memory = memory  # retained for API compatibility; global history is never injected.
        self.skills = skills or []
        self.active_skills = []
        self.context = ConversationContext()
        self.max_input_tokens = max(256, int(max_input_tokens))
        self.context_window = max(0, int(context_window or 0))
        self.max_output_tokens = max(128, int(max_output_tokens))
        self.max_tool_rounds = max(1, min(MAX_TOOL_ROUNDS, int(max_tool_rounds)))
        self.tools = tools
        self.effort_profiles = effort_profiles or {
            "low": {"max_output_tokens": 512, "max_tool_rounds": 3},
            "medium": {"max_output_tokens": self.max_output_tokens, "max_tool_rounds": self.max_tool_rounds},
            "high": {"max_output_tokens": self.max_output_tokens * 2, "max_tool_rounds": self.max_tool_rounds},
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
        else:
            output_tokens = int(getattr(profile, "max_output_tokens", self.max_output_tokens))
        if self.ultrathink:
            output_tokens += 1024
        # Tool rounds are a safety cap only; effort and ultrathink do not change it.
        return max(128, output_tokens), self.max_tool_rounds

    def native_effort_supported(self) -> bool:
        method = getattr(self.provider, "native_effort_kwargs", None)
        return bool(method and method(self.effort))

    def native_effort_status(self) -> str:
        method = getattr(self.provider, "native_effort_kwargs", None)
        if not method or not method(self.effort):
            return "budget only (not declared by provider)"
        describe = getattr(self.provider, "native_effort_status", None)
        return str(describe(self.effort)) if callable(describe) else "supported by provider"

    def window_tokens(self) -> int | None:
        """Configured or server-reported context window, if known."""
        if self.context_window:
            return self.context_window
        detect = getattr(self.provider, "context_window", None)
        try:
            return detect() if callable(detect) else None
        except Exception:
            return None

    def input_budget(self, output_tokens: int | None = None) -> int:
        """Prompt tokens allowed: the whole window minus the output budget and a safety margin."""
        window = self.window_tokens()
        if not window:
            return self.max_input_tokens
        output = output_tokens if output_tokens is not None else self.effective_budgets()[0]
        return max(256, window - output - WINDOW_MARGIN)

    def _messages(self, text, system_prompt, tool_schemas=None):
        instructions = []
        if self.plan_mode:
            instructions.append(
                "Plan mode is read-only. Explore with available read-only project tools and return a concise plan; do not modify files or run commands."
            )
        if self.ultrathink:
            instructions.append(
                "Analyze the task carefully and check the result for important edge cases before answering. Keep the response concise and do not reveal private reasoning steps."
            )
        if self.instructions is not None:
            system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT) + "\n\n" + self.instructions.prompt_block()
        if instructions:
            system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT) + "\n\n" + "\n".join(instructions)
        skills = select_skills(text, self.active_skills) if self.dynamic_context else self.active_skills
        messages = build_messages(text, system_prompt, history=self.context.history, skills=skills)
        if tool_schemas and messages and messages[0].get("role") == "system":
            messages[0]["content"] += ' When native calls are unavailable, emit one exact <tool_call>{"name":"tool_name","arguments":{}}</tool_call> marker.'
        return self._fit(messages, self.input_budget(), tool_schemas)

    def compact_history(self, keep_messages: int = 4) -> tuple[int, int]:
        """Fold older history into one deterministic digest; returns (tokens before, tokens after)."""
        history = self.context.history
        count = lambda items: count_prompt(self.token_counter, list(items), None)
        before = count(history)
        old, recent = history[:-keep_messages] if keep_messages else history, history[-keep_messages:] if keep_messages else []
        if len(old) < 2:
            return before, before
        note = digest_turns(turn_groups(old))
        if not note:
            return before, before
        self.context.history = [
            {"role": "user", "content": note},
            {"role": "assistant", "content": "Noted. I will use that summary of the earlier turns."},
            *recent,
        ]
        return before, count(self.context.history)

    def _verify(self, on_event, cancel):
        """Run the verifier once, with events for the UI. Returns a VerifyResult, or None when it was skipped."""
        if cancel:
            cancel.check()
        commands = self.verifier.commands(self.tools) if self.tools is not None else []
        command = commands[0] if commands else ""
        emit_event(on_event, AgentEvent("verify_started", "verify", command))
        outcome = self.verifier.run(self.tools)
        if outcome is None:
            emit_event(on_event, AgentEvent("verify_skipped", "verify", command, "not run"))
            return None
        self._stats["verify_runs"] = self._stats.get("verify_runs", 0) + 1
        if not outcome.ok:
            self._stats["verify_failures"] = self._stats.get("verify_failures", 0) + 1
        emit_event(on_event, AgentEvent("verify_passed" if outcome.ok else "verify_failed", "verify", command,
                                        outcome.summary, outcome.seconds))
        return outcome

    def _compact_if_needed(self, messages, budget, tool_schemas, on_event):
        """Shrink old tool outputs once the prompt passes COMPACT_AT of the budget, before it overflows."""
        before = count_prompt(self.token_counter, messages, tool_schemas)
        if before <= budget * COMPACT_AT:
            return messages
        messages = [dict(m) for m in messages]
        if not compact_tool_results(messages):
            return messages
        after = count_prompt(self.token_counter, messages, tool_schemas)
        self._stats["compactions"] = self._stats.get("compactions", 0) + 1
        emit_event(on_event, AgentEvent("compacted", summary=f"{before} → {after} tokens"))
        return messages

    def _fit(self, messages, budget, tool_schemas=None):
        fitted = fit_messages(messages, budget, self.token_counter, tools=tool_schemas)
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
        self._last_stop = {"finish_reason": turn.finish_reason, "reasoning_chars": len(turn.reasoning_content or ""),
                           "reasoning_tokens": turn.reasoning_tokens, "output_tokens": output_tokens}
        if turn.finish_reason == "length":
            self._stats["length_stops"] += 1
        self._stats["llm_calls"] += 1
        self._stats["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        self._stats["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        return turn

    def _chat_once(self, messages, tool_schemas, output_tokens, state):
        kwargs = {"num_ctx": self.input_budget(output_tokens) + output_tokens, **self._kwargs(output_tokens)}
        effort_level = "high" if self.ultrathink else self.effort
        native_effort = getattr(self.provider, "native_effort_kwargs", lambda _level: None)(effort_level)
        if native_effort:
            kwargs.update(native_effort)

        def request(tools):
            stream = getattr(self.provider, "chat_stream_turn", None)
            if not (state.get("streaming") and callable(stream)):
                return normalize_turn(self.provider.chat(messages=messages, tools=tools, **kwargs))

            def on_delta(content):
                if state.get("cancel"):
                    state["cancel"].check()
                if self._stats["ttft_ms"] is None:
                    self._stats["ttft_ms"] = round((time.monotonic() - state["started_at"]) * 1000, 1)
                if state.get("on_event"):
                    state["stream_visible"] = True
                    emit_event(state["on_event"], AgentEvent("response_delta", summary=content))

            try:
                turn = normalize_turn(stream(
                    messages=messages, tools=tools, on_delta=on_delta,
                    cancel=state.get("cancel"), **kwargs,
                ))
                if not turn.content.strip() and not turn.tool_calls:
                    if state.get("stream_visible"):
                        emit_event(state.get("on_event"), AgentEvent("response_reset"))
                        state["stream_visible"] = False
                    state["streaming"] = False
                    return normalize_turn(self.provider.chat(messages=messages, tools=tools, **kwargs))
                if state.get("stream_visible"):
                    # Text that precedes a tool call is not the final answer: tell the UI to keep it on screen.
                    emit_event(state.get("on_event"), AgentEvent(
                        "response_end", summary="before_tools" if turn.tool_calls else ""))
                    state["stream_visible"] = False
                return turn
            except (KeyboardInterrupt, TurnCancelled):
                if state.get("stream_visible"):
                    emit_event(state.get("on_event"), AgentEvent("response_reset"))
                    state["stream_visible"] = False
                raise
            except Exception:
                if state.get("stream_visible"):
                    emit_event(state.get("on_event"), AgentEvent("response_reset"))
                    state["stream_visible"] = False
                # Streaming stays off for the rest of this turn after a transport/protocol failure.
                state["streaming"] = False
                return normalize_turn(self.provider.chat(messages=messages, tools=tools, **kwargs))

        if state["native_tools"]:
            try:
                return request(tool_schemas)
            except RuntimeError as exc:
                reason = str(exc).lower()
                if not any(term in reason for term in ("tool", "unsupported", "not support")):
                    raise
                state["native_tools"] = False
        return request(None)

    def _chat_non_empty(self, *args):
        """Ask once more if the first turn is empty; raise a clear error if it stays empty."""
        for _attempt in range(2):
            turn = self._chat(*args)
            if turn.tool_calls or turn.content.strip():
                return turn
        raise RuntimeError(
            "The model returned an empty response twice. " + self._stop_cause()
            + " Check the chat template and reasoning settings, then try again."
        )

    def _stop_cause(self) -> str:
        """Say why the last turn stopped when the backend told us (the usual culprit is reasoning eating the limit)."""
        info = getattr(self, "_last_stop", None) or {}
        if info.get("finish_reason") == "length":
            used = info.get("reasoning_tokens") or 0
            reasoning = f"{used} tokens" if used else (f"~{info.get('reasoning_chars', 0)} characters" if info.get("reasoning_chars") else "")
            spent = f" ({reasoning} of private reasoning)" if reasoning else ""
            return (f"It stopped at the output limit of {info.get('output_tokens')} tokens before answering{spent}. "
                    "Raise /effort, or turn thinking off for this provider (providers.<name>.thinking: off).")
        if info.get("finish_reason"):
            return f"The backend reported finish_reason={info['finish_reason']!r}."
        return "The backend did not say why it stopped."

    def _run_tool_call(self, call, call_id, on_event, cancel=None) -> dict:
        """Execute one tool call (Plan-mode guarded), emit events and return the tool message."""
        if cancel:
            cancel.check()
        self._stats["tool_calls"] += 1
        started_at = time.monotonic()
        target = tool_target(call.name, call.arguments)
        emit_event(on_event, AgentEvent("tool_started", call.name, target))
        is_read_only = getattr(self.tools, "is_read_only", lambda n: n in READ_ONLY_TOOL_NAMES)
        plan_blocked = self.plan_mode and not is_read_only(call.name)
        blocked_by_hook = self.hooks.pre_tool(call.name, target, call.arguments) if self.hooks and not plan_blocked else None
        if plan_blocked:
            result = f"Tool '{call.name}' is blocked in Plan mode. No action was taken."
            event_kind = "tool_denied"
        elif blocked_by_hook:
            result = blocked_by_hook
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
                event_kind = "tool_denied" if tool_was_denied(call.name, result) else "tool_completed"
                if event_kind == "tool_completed" and self.hooks:
                    note = self.hooks.post_tool(call.name, target, call.arguments)
                    if note:
                        result = f"{result}\n{note}"
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

    def turn_tokens(self) -> tuple[int, int]:
        """(prompt, completion) tokens reported by the provider for the current or last task."""
        return int(self._stats.get("prompt_tokens", 0)), int(self._stats.get("completion_tokens", 0))

    @staticmethod
    def _new_stats() -> dict:
        return {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0, "tool_rounds": 0,
                "tool_errors": 0, "tool_denied": 0, "trimmed_messages": 0, "length_stops": 0, "ttft_ms": None}

    def ask(self, text, system_prompt=None, use_tools=False, on_event=None, cancel=None):
        """Answer one request. ``cancel`` (CancelToken) is checked between provider calls and tool calls;
        a cancelled or failed turn leaves the session history untouched."""
        self._stats = self._new_stats()
        journal = getattr(self.tools, "journal", None)
        if journal is not None:
            journal.begin_turn(text)
        started = time.monotonic()
        outcome = "error"
        try:
            result = self._ask(text, system_prompt, use_tools, on_event, cancel)
            outcome = "ok"
            if self.hooks:
                self.hooks.turn_end(outcome)
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
        tool_schemas = self._tool_schemas_for(text, use_tools)
        messages = self._messages(text, system_prompt, tool_schemas)
        state = {"native_tools": bool(tool_schemas), "cancel": cancel,
                 "streaming": self.streaming_enabled, "stream_visible": False,
                 "on_event": on_event, "started_at": time.monotonic()}

        turn = self._chat_non_empty(messages, tool_schemas, output_tokens, state, on_event)
        rounds = 0
        tool_round_completed = False
        retried_compact = False
        last_signature, repeats = None, 0
        changed = False  # a write, edit or command already ran this turn
        edited_since_verify = False
        verify_attempts = 0
        last_verify = None
        self.last_verification = None
        while True:
            turn = parse_compact_call(turn)
            if (self.shell_block_fallback and not turn.tool_calls and not changed and tool_schemas
                    and any(spec.get("function", {}).get("name") == "run_command" for spec in tool_schemas)):
                converted = shell_calls_from_text(turn)
                if converted.tool_calls:
                    if converted.content.strip():
                        emit_event(on_event, AgentEvent("preamble", summary=converted.content))
                    turn = converted
            if (not turn.tool_calls and tool_schemas and self.verifier is not None and self.verifier.enabled and edited_since_verify
                    and verify_attempts <= self.verifier.config.max_attempts and rounds < tool_round_limit):
                edited_since_verify = False
                outcome = self._verify(on_event, cancel)
                if outcome is not None:
                    verify_attempts += 1
                    last_verify = self.last_verification = outcome
                    # Only a failing check is worth another model call, and only while fix rounds remain.
                    if not outcome.ok and not outcome.problem and verify_attempts <= self.verifier.config.max_attempts:
                        messages.append({"role": "assistant", "content": turn.content or "(finished the edits)"})
                        messages.append({"role": "user", "content": outcome.feedback()})
                        budget = self.input_budget(output_tokens)
                        messages = self._compact_if_needed(messages, budget, tool_schemas, on_event)
                        messages = self._fit(messages, budget, tool_schemas)
                        turn = self._chat(messages, tool_schemas, output_tokens, state, on_event)
                        rounds += 1
                        tool_round_completed = True
                        continue
            if not turn.tool_calls or not tool_schemas or rounds >= tool_round_limit:
                response_text = turn.content or (
                    f"Tool round limit reached ({tool_round_limit} rounds). Ask me to continue."
                    if turn.tool_calls else ""
                )
                if tool_round_completed and not response_text.strip() and not retried_compact:
                    # An empty reply after a tool result often means the prompt filled the window:
                    # shrink every tool output once and ask again before giving up.
                    retried_compact = True
                    messages = [dict(m) for m in messages]
                    if compact_tool_results(messages, keep_last_round=False):
                        emit_event(on_event, AgentEvent("compacted", summary="retrying after an empty reply"))
                        self._stats["compactions"] = self._stats.get("compactions", 0) + 1
                        turn = self._chat(messages, tool_schemas, output_tokens, state, on_event)
                        continue
                if tool_round_completed and not response_text.strip():
                    raise RuntimeError(
                        "The model returned an empty response after a tool result. " + self._stop_cause()
                        + " Check the chat template and reasoning settings."
                    )
                break
            calls = [call for call in turn.tool_calls if call.name]
            if not calls:
                if turn.content.strip():
                    response_text = turn.content
                    break
                raise RuntimeError("The model returned a tool call without a valid function name.")
            signature = tuple((call.name, json.dumps(call.arguments, sort_keys=True, default=str)) for call in calls)
            repeats = repeats + 1 if signature == last_signature else 1
            last_signature = signature
            if repeats > REPEAT_LIMIT:
                response_text = (f"Stopped: the model repeated the same {calls[0].name} call {repeats} times "
                                 "without progress. Rephrase the request or give it more detail.")
                break
            self._stats["tool_rounds"] += 1
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
                result_message = self._run_tool_call(call, call_id, on_event, cancel)
                messages.append(result_message)
                if call.name in CHANGING_TOOLS and not tool_was_denied(call.name, result_message.get("content", "")):
                    changed = True
                    if call.name in {"write_file", "edit_file"}:
                        edited_since_verify = True
            rounds += 1
            tool_round_completed = True
            budget = self.input_budget(output_tokens)
            messages = self._compact_if_needed(messages, budget, tool_schemas, on_event)
            messages = self._fit(messages, budget, tool_schemas)
            turn = self._chat(messages, tool_schemas, output_tokens, state, on_event)
        if last_verify is not None and not last_verify.ok:
            response_text = (f"{response_text}\n\n⚠ Not verified: `{last_verify.command}` "
                             f"{last_verify.summary}. Review the changes before relying on them.").strip()
        self.context.add_message("user", text)
        self.context.add_message("assistant", response_text)
        return response_text

    def ask_stream(self, text, system_prompt=None, use_tools=False, on_event=None, cancel=None) -> Generator[str, None, None]:
        """Compatibility wrapper that yields the complete answer as one item."""
        response = self.ask(text, system_prompt=system_prompt, use_tools=use_tools, on_event=on_event, cancel=cancel)
        yield response
