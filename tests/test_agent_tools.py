import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.agent import Agent
from zerocoding.core.prompt import build_messages
from zerocoding.tools.builtin import create_builtin_tools
from zerocoding.tools.registry import ToolRegistry, ToolSpec


class ToolProvider:
    supports_tools = True

    def __init__(self):
        self.calls = []

    def chat_with_tools(self, messages, tools, max_output_tokens=512):
        self.calls.append(messages)
        if not any(message["role"] == "tool" for message in messages):
            return {"content": "", "tool_calls": [{
                "id": "1", "type": "function", "function": {
                    "name": "write_file", "arguments": json.dumps({"path": "out.txt", "content": "created"}),
                },
            }]}
        return {"content": "Done.", "tool_calls": []}


class ChatProvider:
    def __init__(self):
        self.messages = []

    def chat(self, messages, **_):
        self.messages.append(messages)
        return "ok"


class ReviewToolProvider(ToolProvider):
    def chat(self, messages, **kwargs):
        self.review_messages = messages
        return '{"decision":"allow","reason":"Ação local solicitada"}'


class TestAgentTools(unittest.TestCase):
    def test_base_prompt_and_budget(self):
        messages = build_messages("request", history=[{"role": "user", "content": "old"}], context_text="ctx", budget_tokens=40)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("ZeroCoding", messages[0]["content"])
        self.assertLessEqual(sum(len(m["content"]) for m in messages) // 4, 41)

    def test_session_history_is_not_duplicated_or_shared(self):
        provider = ChatProvider()
        first, second = Agent(provider), Agent(provider)
        first.ask("first")
        first.ask("second")
        self.assertEqual([m["content"] for m in provider.messages[-1] if m["role"] == "user"], ["first", "second"])
        second.ask("private")
        self.assertEqual([m["content"] for m in provider.messages[-1] if m["role"] == "user"], ["private"])

    def test_write_requires_approval_and_stays_in_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = ToolProvider()
            agent = Agent(provider, tools=create_builtin_tools(root))
            self.assertEqual(agent.ask("create a file", approve=lambda *_: False), "Done.")
            self.assertFalse((root / "out.txt").exists())
            provider.calls.clear()
            self.assertEqual(agent.ask("create a file", approve=lambda *_: True), "Done.")
            self.assertEqual((root / "out.txt").read_text(), "created")

            outside = root.parent / (root.name + "-outside.txt")
            try:
                result = agent.tools.get("read_file").handler({"path": "../" + outside.name})
            except ValueError:
                pass
            else:
                self.fail(f"read outside root unexpectedly succeeded: {result}")

    def test_unapproved_tool_is_not_run_when_callback_missing(self):
        called = []
        provider = ToolProvider()
        registry = ToolRegistry()
        registry.register(ToolSpec("write_file", "write", {"type": "object"}, lambda _: called.append(True), True))
        Agent(provider, tools=registry).ask("write")
        self.assertEqual(called, [])

    def test_approve_for_me_reviews_local_actions_and_runs_approved_tool(self):
        with patch("zerocoding.core.agent.workspace_sandbox_available", return_value=True):
            provider = ReviewToolProvider()
            registry = ToolRegistry()
            called = []
            registry.register(ToolSpec("write_file", "write", {"type": "object"}, lambda _: called.append(True), True, permission_scope="project"))
            agent = Agent(provider, tools=registry, permission_mode="approve_for_me")

            agent.ask("create a local file", approve=lambda *_: self.fail("local action should use the reviewer"))

        self.assertEqual(called, [True])
        self.assertNotIn("tools", provider.review_messages[1])

    def test_review_result_is_emitted_for_the_tui(self):
        provider = ReviewToolProvider()
        registry = ToolRegistry()
        registry.register(ToolSpec("write_file", "write", {"type": "object"}, lambda _: "wrote", True, permission_scope="project"))
        agent = Agent(provider, tools=registry, permission_mode="approve_for_me")

        events = list(agent.run_events("write a file"))

        self.assertTrue(any(event.type == "approval_result" and "aprovou" in event.data["output"] for event in events))

    def test_full_access_uses_sandbox_handler_for_commands(self):
        with patch("zerocoding.core.agent.workspace_sandbox_available", return_value=True):
            provider = ToolProvider()
            registry = ToolRegistry()
            calls = []
            registry.register(ToolSpec(
                "write_file", "write", {"type": "object"}, lambda _: calls.append("host"), True,
                permission_scope="command", sandbox_handler=lambda _: calls.append("sandbox"),
            ))
            agent = Agent(provider, tools=registry, permission_mode="full_access")

            agent.ask("create a local file", approve=lambda *_: self.fail("local command should not prompt"))

        self.assertEqual(calls, ["sandbox"])

    def test_full_access_keeps_external_tools_manual(self):
        with patch("zerocoding.core.agent.workspace_sandbox_available", return_value=True):
            provider = ToolProvider()
            registry = ToolRegistry()
            called = []
            registry.register(ToolSpec("write_file", "write", {"type": "object"}, lambda _: called.append(True), True))
            Agent(provider, tools=registry, permission_mode="full_access").ask("external action")
        self.assertEqual(called, [])

    def test_approve_for_me_uses_manual_command_approval_without_sandbox(self):
        with patch("zerocoding.core.agent.workspace_sandbox_available", return_value=False):
            provider = ToolProvider()
            registry = ToolRegistry()
            called = []
            registry.register(ToolSpec("write_file", "write", {"type": "object"}, lambda _: called.append("manual"), True, permission_scope="command", sandbox_handler=lambda _: called.append("sandbox")))
            agent = Agent(provider, tools=registry, permission_mode="approve_for_me")

            agent.ask("run local command", approve=lambda *_: True)

        self.assertEqual(called, ["manual"])


if __name__ == "__main__":
    unittest.main()
