import tempfile
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.budget import fit_messages
from zerocoding.core.toolcalls import parse_compact_call
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
    def test_tool_error_summary_includes_the_reason(self):
        from zerocoding.core.toolcalls import tool_summary
        self.assertEqual(tool_summary("list_files", "Tool error: Path does not exist: calculadora"),
                         "Tool error · Path does not exist: calculadora")
        self.assertEqual(tool_summary("list_files", "Tool error:"), "Tool error")

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
        turn = parse_compact_call(ProviderTurn(content='<tool_call>{"name":"list_files","arguments":{}}</tool_call>'))
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


class TestShellBlockFallback(unittest.TestCase):
    def convert(self, text):
        from zerocoding.core.toolcalls import shell_calls_from_text
        from zerocoding.providers.base import ProviderTurn
        return shell_calls_from_text(ProviderTurn(content=text))

    def test_bash_block_becomes_run_command_and_leaves_the_prose(self):
        turn = self.convert("Vou criar a pasta:\n\n```bash\nmkdir calculadora\n```\n")
        self.assertEqual([(c.name, c.arguments) for c in turn.tool_calls], [("run_command", {"command": "mkdir calculadora"})])
        self.assertEqual(turn.content, "Vou criar a pasta:")

    def test_multiple_lines_comments_and_prompts(self):
        turn = self.convert("```sh\n# setup\n$ mkdir a\ntouch a/b.txt\n```")
        self.assertEqual([c.arguments["command"] for c in turn.tool_calls], ["mkdir a", "touch a/b.txt"])

    def test_blocks_that_need_a_shell_or_are_not_shell_are_left_alone(self):
        for text in ("```bash\nmkdir a && cd a\n```", "```bash\ncd project\n```", "```bash\nls | wc -l\n```",
                     "```python\nprint('x')\n```", "```\nmkdir a\n```", "no code here"):
            self.assertEqual(self.convert(text).tool_calls, [], text)

    def test_number_of_converted_commands_is_capped(self):
        turn = self.convert("```bash\n" + "\n".join(f"mkdir d{i}" for i in range(10)) + "\n```")
        self.assertEqual(len(turn.tool_calls), 4)

    def agent(self, texts, approve=True, **kwargs):
        from zerocoding.core.agent import Agent
        from zerocoding.core.tools import ToolRegistry
        from zerocoding.providers.base import ProviderTurn

        class Provider:
            def __init__(self):
                self.turns = iter(texts)

            def chat(self, messages, **kw):
                return ProviderTurn(content=next(self.turns))

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        asked = []
        tools = ToolRegistry(self.directory.name, approve=lambda action, preview: asked.append((action, preview)) or approve)
        return Agent(Provider(), tools=tools, **kwargs), asked

    def test_printed_command_is_proposed_for_approval_run_and_announced(self):
        agent, asked = self.agent(["Vou criar:\n```bash\nmkdir calculadora\n```", "Pasta criada."])
        events = []
        answer = agent.ask("modularize", use_tools=True, on_event=events.append)
        self.assertEqual(asked, [("Run command", "mkdir calculadora")])
        self.assertTrue((Path(self.directory.name) / "calculadora").is_dir())
        self.assertEqual(answer, "Pasta criada.")
        preamble = [e for e in events if e.kind == "preamble"]
        self.assertEqual([e.summary for e in preamble], ["Vou criar:"])

    def test_refused_command_does_not_run(self):
        agent, asked = self.agent(["```bash\nmkdir calculadora\n```", "Ok, não vou criar."], approve=False)
        agent.ask("modularize", use_tools=True)
        self.assertFalse((Path(self.directory.name) / "calculadora").exists())

    def test_disabled_by_config_and_in_plan_mode(self):
        agent, asked = self.agent(["```bash\nmkdir x\n```"], shell_block_fallback=False)
        self.assertIn("mkdir x", agent.ask("go", use_tools=True))
        self.assertEqual(asked, [])
        agent, asked = self.agent(["```bash\nmkdir x\n```"], plan_mode=True)
        agent.ask("go", use_tools=True)
        self.assertEqual(asked, [])

    def test_no_conversion_after_the_model_already_changed_something(self):
        agent, asked = self.agent(["```bash\nmkdir first\n```", "Done. Run it with:\n```bash\npython main.py\n```"])
        answer = agent.ask("go", use_tools=True)
        self.assertEqual([preview for _, preview in asked], ["mkdir first"])
        self.assertIn("python main.py", answer)


if __name__ == "__main__":
    unittest.main()

