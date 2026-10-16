#!/usr/bin/env python3
"""Small read-only Qwen-Agent reference probes against an OpenAI-compatible Ollama."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import time

from qwen_agent.agents import Assistant
import qwen_agent.agents.fncall_agent as fncall_agent
from qwen_agent.tools.base import BaseTool, register_tool


# A read-only probe should need one tool call and one final answer at most.
# The framework's default permits many more rounds and makes a tiny diagnostic
# surprisingly expensive on local hardware.
MAX_LLM_CALLS_PER_PROBE = 2
fncall_agent.MAX_LLM_CALL_PER_RUN = MAX_LLM_CALLS_PER_PROBE


@register_tool("zc_reference_read_fixture")
class ReferenceReadFixture(BaseTool):
    description = "Read the fixed synthetic source file used by the ZeroCoding model study."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The only supported path is src/calculations.py.",
            },
        },
        "required": ["path"],
    }

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json.loads(params)
        except (TypeError, ValueError):
            return "Invalid arguments."
        if args.get("path") != "src/calculations.py":
            return "Path not found. This read-only reference tool exposes only src/calculations.py."
        return (
            'def format_total(items):\n'
            '    """Return the sum of item prices formatted as dollars."""\n'
            '    return f"${sum(item[\'price\'] for item in items):.2f}"\n'
        )


def _llm_config(base_url: str, model: str) -> dict:
    return {
        "model": model,
        # Qwen-Agent's official Qwen3.5 example uses the raw OpenAI-compatible
        # path so native tool calls are passed through instead of converted to
        # the framework's legacy prompt-based function-call format.
        "model_type": "qwenvl_oai",
        "model_server": base_url.rstrip("/") + "/v1",
        "api_key": "EMPTY",
        "generate_cfg": {
            "use_raw_api": True,
            "temperature": 0.6,
            "top_p": 0.95,
            "presence_penalty": 0.0,
            "max_tokens": 512,
            "seed": 31416,
            # Ollama's OpenAI Chat Completions endpoint exposes thinking
            # control as reasoning_effort; `think` belongs to /v1/responses.
            "extra_body": {"top_k": 20, "repeat_penalty": 1.0, "reasoning_effort": "none"},
        },
    }


def _clean_final_content(value: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL)
    value = re.sub(r"<think>.*$", "", value, flags=re.DOTALL)
    return value.strip()


def _message_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        result = model_dump()
        return result if isinstance(result, dict) else {}
    return {}


def _run_probe(name: str, prompt: str, base_url: str, model: str, with_tool: bool) -> dict:
    functions = ["zc_reference_read_fixture"] if with_tool else []
    assistant = Assistant(
        llm=_llm_config(base_url, model),
        system_message=(
            "You are a concise coding assistant. Use only the provided read-only fixture tool. "
            "Never modify files or run commands. Return a concise final answer."
        ),
        function_list=functions,
    )
    started = time.perf_counter()
    emitted_messages = []
    for batch in assistant.run(messages=[{"role": "user", "content": prompt}]):
        if isinstance(batch, list):
            # Qwen-Agent yields cumulative response snapshots. Keep the newest
            # snapshot so repeated tool messages are not counted as new calls.
            emitted_messages = [message for item in batch if (message := _message_dict(item))]
        elif isinstance(batch, dict):
            emitted_messages = [batch]
        else:
            message = _message_dict(batch)
            if message:
                emitted_messages = [message]
    final_messages = [message for message in emitted_messages if message.get("role") == "assistant"]
    final_content = next(
        (str(message.get("content") or "") for message in reversed(final_messages) if message.get("content")),
        "",
    )
    tool_names = []
    for message in emitted_messages:
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            if function.get("name"):
                tool_names.append(function["name"])
        function_call = message.get("function_call")
        if isinstance(function_call, dict) and function_call.get("name"):
            tool_names.append(function_call["name"])
    reasoning_present = any(
        bool(message.get("reasoning_content") or message.get("thinking"))
        for message in emitted_messages
    )
    final_content = _clean_final_content(final_content)
    tool_call_count = len(tool_names)
    final_content_nonempty = bool(final_content)
    return {
        "probe": name,
        "status": "passed" if final_content_nonempty and (not with_tool or tool_call_count > 0) else "incomplete",
        "tool_names": tool_names,
        "tool_call_count": tool_call_count,
        "final_content": final_content,
        "final_content_nonempty": final_content_nonempty,
        "reasoning_present": reasoning_present,
        "duration_seconds": time.perf_counter() - started,
        "emitted_roles": [message.get("role") for message in emitted_messages],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    probes = [
        _run_probe(
            "direct_answer",
            "Using a project tax rate of 8%, calculate tax on $250. Return only the amount.",
            args.base_url, args.model, False,
        ),
        _run_probe(
            "tool_read_and_answer",
            "Read src/calculations.py, then explain what format_total sums and how it formats the result.",
            args.base_url, args.model, True,
        ),
        _run_probe(
            "read_only_plan",
            "Read src/calculations.py and give a short plan for reviewing a requested change to its output format. Do not modify files.",
            args.base_url, args.model, True,
        ),
    ]
    result = {
        "status": "complete",
        "qwen_agent_version": importlib.metadata.version("qwen-agent"),
        "qwen_agent_llm_mode": "qwenvl_oai with use_raw_api=True",
        "reasoning_effort": "none",
        "max_tokens": 512,
        "max_llm_calls_per_probe": MAX_LLM_CALLS_PER_PROBE,
        "model": args.model,
        "base_url": args.base_url,
        "probes": probes,
        "all_probes_passed": all(probe["status"] == "passed" for probe in probes),
        "limitations": [
            "Diagnostic sample only; prompts, tool schemas, and harness differ from ZeroCoding.",
            "Tool access is read-only and returns fixed synthetic source; no user workspace is accessible.",
            "Ollama OpenAI Chat Completions received reasoning_effort=none to match the best-performing ZeroCoding matrix condition; thinking content is not retained.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
