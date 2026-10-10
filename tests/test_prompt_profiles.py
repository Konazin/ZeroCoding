import unittest

from zerocoding.core.agent import Agent
from zerocoding.core.config import Config
from zerocoding.core.events import AgentEvent
from zerocoding.core.prompt import SYSTEM_PROMPT, build_messages, estimate_tokens
from zerocoding.tools.registry import ToolRegistry, ToolSpec


class Provider:
    def __init__(self):
        self.messages = None

    def chat(self, messages, **_):
        self.messages = messages
        return "ok"


class JsonToolProvider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def chat(self, messages, **_):
        self.calls += 1
        return self.text if self.calls == 1 else "finished"


class TestPromptProfiles(unittest.TestCase):
    def test_system_prompt_and_budget(self):
        self.assertLessEqual(estimate_tokens(SYSTEM_PROMPT), 64)
        messages = build_messages("fix this", system_prompt="extra rules", context_text="project notes", budget_tokens=64)
        self.assertEqual(messages[0], {"role": "system", "content": SYSTEM_PROMPT})
        self.assertLessEqual(sum(estimate_tokens(item["content"]) for item in messages), 64)

    def test_default_mode_budgets(self):
        modes = Config.load().modes
        self.assertEqual((modes["fast"].input_budget_tokens, modes["fast"].max_tool_steps), (1024, 3))
        self.assertEqual((modes["code"].input_budget_tokens, modes["code"].max_tool_steps), (2048, 6))
        self.assertEqual((modes["reason"].input_budget_tokens, modes["reason"].max_tool_steps), (3072, 8))
        self.assertEqual((modes["smart"].input_budget_tokens, modes["smart"].max_tool_steps), (3072, 8))
        self.assertEqual((modes["project"].input_budget_tokens, modes["project"].output_budget_tokens, modes["project"].max_tool_steps), (2048, 1024, 8))

    def test_agent_forwards_profile_output_budget_to_tool_provider(self):
        class BudgetProvider:
            supports_tools = True

            def __init__(self):
                self.output_budget = None

            def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
                self.output_budget = max_output_tokens
                yield {"tool_calls": []}

        provider = BudgetProvider()
        tools = ToolRegistry()
        tools.register(ToolSpec("read", "Read", {"type": "object", "properties": {}}, lambda _: "ok"))
        agent = Agent(provider, tools=tools, output_budget_tokens=1024)
        agent.ask("hello")

        self.assertEqual(provider.output_budget, 1024)

    def test_agent_forwards_profile_output_budget_to_regular_provider(self):
        class BudgetProvider:
            def __init__(self):
                self.output_budget = None

            def chat(self, messages, max_output_tokens=512):
                self.output_budget = max_output_tokens
                return "ok"

        provider = BudgetProvider()
        agent = Agent(provider, output_budget_tokens=1024)
        self.assertEqual(agent.ask("hello"), "ok")
        self.assertEqual(provider.output_budget, 1024)

    def test_provider_usage_accumulates_across_tool_rounds(self):
        class UsageProvider:
            supports_tools = True

            def __init__(self):
                self.requests = 0

            def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
                self.requests += 1
                if self.requests == 1:
                    yield {"usage": {"input_tokens": 20, "output_tokens": 4}}
                    yield {"tool_calls": [{"id": "r1", "type": "function", "function": {"name": "read", "arguments": {}}}]}
                else:
                    yield {"usage": {"input_tokens": 30, "output_tokens": 6}}
                    yield {"content": "done"}
                    yield {"tool_calls": []}

        tools = ToolRegistry()
        tools.register(ToolSpec("read", "Read", {"type": "object", "properties": {}}, lambda _: "content"))
        agent = Agent(UsageProvider(), tools=tools)
        agent.ask("inspect")

        self.assertEqual(agent.last_metrics["provider_usage"], {"input_tokens": 50, "output_tokens": 10})

    def test_text_tool_mode_buffers_calls_and_keeps_usage(self):
        class TextToolProvider:
            supports_tools = True

            def __init__(self):
                self.requests = 0
                self.last_usage = None

            def chat_stream_with_tools(self, *args, **kwargs):
                raise AssertionError("native tool streaming should be bypassed")

            def chat_stream(self, messages, max_output_tokens=512):
                self.requests += 1
                if self.requests == 1:
                    self.last_usage = {"input_tokens": 20, "output_tokens": 4}
                    yield 'I will update the file. {"name":"write","arguments":{"path":"a.txt"}} Summary: done.'
                else:
                    self.last_usage = {"input_tokens": 25, "output_tokens": 3}
                    yield "done"

        writes = []
        tools = ToolRegistry()
        tools.register(ToolSpec("write", "Write", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, lambda args: writes.append(args["path"]) or "written", True, permission_scope="project"))
        provider = TextToolProvider()
        agent = Agent(provider, tools=tools, prefer_text_tool_calls=True)

        self.assertEqual(agent.ask("update the file", approve=lambda *_: True), "done")
        self.assertEqual(writes, ["a.txt"])
        self.assertEqual(agent.last_metrics["tool_calls"], 1)
        self.assertEqual(agent.last_metrics["provider_usage"], {"input_tokens": 45, "output_tokens": 7})

    def test_fast_sends_half_the_request_tokens_for_large_context_free_prompt(self):
        prompt = "Implement the requested change. " * 400
        fast = build_messages(prompt, budget_tokens=1024)
        code = build_messages(prompt, budget_tokens=2048)
        fast_tokens = sum(estimate_tokens(item["content"]) for item in fast)
        code_tokens = sum(estimate_tokens(item["content"]) for item in code)
        self.assertLessEqual(fast_tokens, code_tokens // 2)

    def test_typed_events_and_request_metrics(self):
        provider = Provider()
        agent = Agent(provider)
        events = list(agent.run_events("hello"))
        self.assertEqual([item.type for item in events], ["token", "metrics", "done"])
        self.assertIsInstance(events[0], AgentEvent)
        self.assertEqual(agent.last_metrics["input_budget"], 2048)
        self.assertIsNotNone(agent.last_metrics["first_token_ms"])
        self.assertGreaterEqual(agent.last_metrics["duration_ms"], 0)

    def test_non_native_tool_fallback_requires_exact_valid_json(self):
        ran = []
        registry = ToolRegistry()
        registry.register(ToolSpec("read", "Read", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, lambda args: ran.append(args) or "content", permission_scope="project"))
        provider = JsonToolProvider('{"name":"read","arguments":{"path":"a.txt"}}')
        self.assertEqual(Agent(provider, tools=registry).ask("read a"), "finished")
        self.assertEqual(ran, [{"path": "a.txt"}])

        ran.clear()
        provider = JsonToolProvider('{"name":"read","arguments":{"path":1}}')
        answer = Agent(provider, tools=registry).ask("read a")
        self.assertIn('"name":"read"', answer)
        self.assertEqual(ran, [])

    def test_local_tool_fallback_accepts_multiple_adjacent_json_calls(self):
        written = []
        class MultiCallProvider:
            supports_tools = True

            def __init__(self):
                self.requests = 0

            def chat_stream(self, messages, max_output_tokens=512):
                self.requests += 1
                if self.requests == 1:
                    yield '{"name":"write","arguments":{"path":"a.txt"}}\n{"name":"write","arguments":{"path":"b.txt"}}\nSummary: both files are ready.'
                else:
                    yield "done"

        registry = ToolRegistry()
        registry.register(ToolSpec("write", "Write", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, lambda args: written.append(args["path"]) or "written", True, permission_scope="project"))
        result = Agent(MultiCallProvider(), tools=registry, prefer_text_tool_calls=True).ask("write both files", approve=lambda *_: True)

        self.assertEqual(result, "done")
        self.assertEqual(written, ["a.txt", "b.txt"])

    def test_local_tool_fallback_finds_strict_call_after_model_preamble(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("read", "Read", {"type": "object", "properties": {}}, lambda _: "secret", permission_scope="project"))
        agent = Agent(JsonToolProvider('I will inspect the project.\n{"name":"read","arguments":{}}\nSummary: finished.'), tools=registry, prefer_text_tool_calls=True)

        calls = agent._text_tool_calls('I will inspect the project.\n{"name":"read","arguments":{}}\nSummary: finished.')

        self.assertEqual([call["function"]["name"] for call in calls], ["read"])
        strict_agent = Agent(JsonToolProvider("unused"), tools=registry)
        self.assertEqual(strict_agent._text_tool_calls('I will inspect the project.\n{"name":"read","arguments":{}}'), [])

    def test_local_tool_fallback_ignores_unknown_or_malformed_json(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("read", "Read", {"type": "object", "properties": {}}, lambda _: "secret", permission_scope="project"))
        agent = Agent(JsonToolProvider("unused"), tools=registry, prefer_text_tool_calls=True)

        calls = agent._text_tool_calls('{"name":"delete_everything","arguments":{}} {"name":"read","arguments":{},"extra":true}')

        self.assertEqual(calls, [])

    def test_approval_is_exposed_as_typed_event(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("write", "Write", {"type": "object", "properties": {}}, lambda _: "ok", True))
        class NativeProvider:
            supports_tools = True
            def chat_with_tools(self, messages, tools, max_output_tokens=512):
                if not any(item["role"] == "tool" for item in messages):
                    return {"content": "", "tool_calls": [{"function": {"name": "write", "arguments": {}}}]}
                return {"content": "done", "tool_calls": []}
        seen = []
        list(Agent(NativeProvider(), tools=registry).run_events("write", approve=lambda *_: False, on_event=seen.append))
        self.assertEqual(seen[0].type, "approval_request")


if __name__ == "__main__":
    unittest.main()
