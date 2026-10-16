import tempfile
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent, fit_messages
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn, ToolCall


class DummyProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    def chat(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return self.turns.pop(0)


class TestAgentTools(unittest.TestCase):
    def test_tool_loop_and_session_history_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "hello.py").write_text("print('hello')\n", encoding="utf-8")
            provider = DummyProvider([
                ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "hello.py"}, "read-1")]),
                ProviderTurn(content="The file prints hello."),
            ])
            agent = Agent(provider, max_input_tokens=4096)
            agent.tools = ToolRegistry(directory)
            agent.memory = type("LegacyMemory", (), {"get_history": lambda self: [{"role": "user", "content": "unrelated"}]})()

            result = agent.ask("What does this file do?", use_tools=True)

            self.assertEqual(result, "The file prints hello.")
            self.assertEqual(len(provider.requests), 2)
            self.assertNotIn("unrelated", str(provider.requests[0][0]))
            self.assertEqual([item["role"] for item in agent.context.history], ["user", "assistant"])
            self.assertEqual(provider.requests[1][0][-1]["role"], "tool")

    def test_multiple_tool_calls_keep_matching_ids_and_results(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "one.txt").write_text("one\n", encoding="utf-8")
            Path(directory, "two.txt").write_text("two\n", encoding="utf-8")
            provider = DummyProvider([
                ProviderTurn(tool_calls=[
                    ToolCall("read_file", {"path": "one.txt"}, "read-one"),
                    ToolCall("read_file", {"path": "two.txt"}, "read-two"),
                ]),
                ProviderTurn(content="Both files were read."),
            ])
            agent = Agent(provider)
            agent.tools = ToolRegistry(directory)

            self.assertEqual(agent.ask("Read both files", use_tools=True), "Both files were read.")
            assistant_message = next(message for message in provider.requests[1][0] if message.get("tool_calls"))
            tool_messages = [message for message in provider.requests[1][0] if message.get("role") == "tool"]
            self.assertEqual([call["id"] for call in assistant_message["tool_calls"]], ["read-one", "read-two"])
            self.assertEqual([message["tool_call_id"] for message in tool_messages], ["read-one", "read-two"])
            self.assertIn("one", tool_messages[0]["content"])
            self.assertIn("two", tool_messages[1]["content"])

    def test_private_reasoning_is_passed_only_for_tool_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "hello.py").write_text("print('hello')\n", encoding="utf-8")
            provider = DummyProvider([
                ProviderTurn(
                    tool_calls=[ToolCall("read_file", {"path": "hello.py"}, "read-1")],
                    reasoning_content="private model reasoning",
                    thinking_present=True,
                ),
                ProviderTurn(content="The file prints hello."),
            ])
            agent = Agent(provider)
            agent.tools = ToolRegistry(directory)

            result = agent.ask("Read the file", use_tools=True)

            self.assertEqual(result, "The file prints hello.")
            assistant_message = next(message for message in provider.requests[1][0] if message.get("tool_calls"))
            self.assertEqual(assistant_message["reasoning_content"], "private model reasoning")
            self.assertNotIn("private model reasoning", str(agent.context.history))
            self.assertNotIn("private model reasoning", result)

    def test_write_requires_approval_and_displays_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "file.txt")
            target.write_text("old\n", encoding="utf-8")
            shown = []
            registry = ToolRegistry(directory, approve=lambda action, preview: shown.append((action, preview)) or False)
            result = registry.execute("write_file", {"path": "file.txt", "content": "new\n"})
            self.assertIn("denied", result)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertIn("-old", shown[0][1])
            self.assertIn("+new", shown[0][1])

    def test_plan_mode_blocks_write_even_when_called_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "file.txt")
            target.write_text("old\n", encoding="utf-8")
            registry = ToolRegistry(directory)

            result = registry.execute(
                "write_file", {"path": "file.txt", "content": "new\n"}, plan_mode=True
            )

            self.assertIn("blocked in Plan mode", result)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")

    def test_paths_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ToolRegistry(directory)
            with self.assertRaises(ValueError):
                registry.execute("read_file", {"path": "../outside.txt"})

    def test_compact_marker_is_a_tool_call(self):
        turn = Agent._parse_compact(ProviderTurn(content='<tool_call>{"name":"list_files","arguments":{}}</tool_call>'))
        self.assertEqual(turn.tool_calls[0].name, "list_files")

    def test_native_rejection_uses_compact_fallback(self):
        class FallbackProvider:
            def __init__(self):
                self.native_attempted = False
                self.responses = iter([
                    '<tool_call>{"name":"list_files","arguments":{"limit":1}}</tool_call>',
                    "Done.",
                ])

            def chat(self, messages, **kwargs):
                if kwargs.get("tools"):
                    self.native_attempted = True
                    raise RuntimeError("server does not support tools")
                return next(self.responses)

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "one.txt").write_text("1", encoding="utf-8")
            provider = FallbackProvider()
            agent = Agent(provider)
            agent.tools = ToolRegistry(directory)
            self.assertEqual(agent.ask("list a file", use_tools=True), "Done.")
            self.assertTrue(provider.native_attempted)

    def test_initial_empty_response_is_retried_once(self):
        provider = DummyProvider([ProviderTurn(), ProviderTurn(content="Recovered answer.")])
        agent = Agent(provider)
        self.assertEqual(agent.ask("Answer briefly"), "Recovered answer.")
        self.assertEqual(len(provider.requests), 2)

    def test_repeated_empty_response_has_clear_error(self):
        provider = DummyProvider([ProviderTurn(), ProviderTurn()])
        agent = Agent(provider)
        with self.assertRaisesRegex(RuntimeError, "empty response twice"):
            agent.ask("Answer briefly")
        self.assertEqual(len(provider.requests), 2)

    def test_empty_response_after_tool_result_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "hello.py").write_text("print('hello')\n", encoding="utf-8")
            provider = DummyProvider([
                ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "hello.py"}, "read-1")]),
                ProviderTurn(),
            ])
            agent = Agent(provider)
            agent.tools = ToolRegistry(directory)

            with self.assertRaisesRegex(RuntimeError, "empty response after a tool result"):
                agent.ask("Read the file", use_tools=True)
            self.assertEqual(len(provider.requests), 2)

    def test_ultrathink_requests_high_native_effort(self):
        class NativeEffortProvider(DummyProvider):
            def native_effort_kwargs(self, level):
                return {"reasoning_effort": level}

        provider = NativeEffortProvider([ProviderTurn(content="Done.")])
        agent = Agent(provider)
        agent.set_session_controls(ultrathink=True)

        self.assertEqual(agent.ask("Check carefully"), "Done.")
        self.assertEqual(provider.requests[0][1]["reasoning_effort"], "high")
        self.assertEqual(provider.requests[0][1]["max_tokens"], 2048)

    def test_budget_drops_old_history_first(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old" * 500},
            {"role": "assistant", "content": "old" * 500},
            {"role": "user", "content": "current request"},
        ]
        fitted = fit_messages(messages, 100)
        self.assertEqual(fitted[0]["role"], "system")
        self.assertIn("current", fitted[-1]["content"])
        self.assertLessEqual(len(fitted), 2)


if __name__ == "__main__":
    unittest.main()
