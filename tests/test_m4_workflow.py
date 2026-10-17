import os
import tempfile
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.command_policy import CommandPolicy
from zerocoding.core.config import ConfigManager
from zerocoding.core.sessions import SessionManager
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn, ToolCall


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    def chat(self, messages, **kwargs):
        self.requests.append([dict(m) for m in messages])
        return self.turns.pop(0)


class Workspace(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name).resolve()
        self.prompts = []

    def registry(self, answer=True, **kwargs):
        def approve(action, preview):
            self.prompts.append((action, preview))
            return answer
        return ToolRegistry(self.root, approve=approve, **kwargs)


class TestEditFile(Workspace):
    def test_edit_applies_after_approval_and_shows_diff(self):
        target = self.root / "a.py"
        target.write_text("x = 1\ny = 2\n", encoding="utf-8")
        result = self.registry(True).execute("edit_file", {"path": "a.py", "old_text": "y = 2", "new_text": "y = 3"})
        self.assertEqual(result, "Edited a.py.")
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\ny = 3\n")
        self.assertEqual(self.prompts[0][0], "Edit file")
        self.assertIn("-y = 2", self.prompts[0][1])
        self.assertIn("+y = 3", self.prompts[0][1])

    def test_denied_edit_changes_nothing(self):
        target = self.root / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = self.registry(False).execute("edit_file", {"path": "a.py", "old_text": "1", "new_text": "2"})
        self.assertIn("denied", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\n")

    def test_edit_without_approver_is_denied(self):
        target = self.root / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = ToolRegistry(self.root).execute("edit_file", {"path": "a.py", "old_text": "1", "new_text": "2"})
        self.assertIn("denied", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\n")

    def test_ambiguous_missing_and_empty_old_text_are_rejected_without_prompt(self):
        target = self.root / "a.py"
        target.write_text("a = 1\na = 1\n", encoding="utf-8")
        registry = self.registry(True)
        with self.assertRaisesRegex(ValueError, "matches 2 places"):
            registry.execute("edit_file", {"path": "a.py", "old_text": "a = 1", "new_text": "a = 2"})
        with self.assertRaisesRegex(ValueError, "not found"):
            registry.execute("edit_file", {"path": "a.py", "old_text": "zzz", "new_text": "a = 2"})
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            registry.execute("edit_file", {"path": "a.py", "old_text": "", "new_text": "a"})
        self.assertEqual(self.prompts, [])
        self.assertEqual(target.read_text(encoding="utf-8"), "a = 1\na = 1\n")

    def test_edit_blocked_in_plan_mode_and_outside_workspace(self):
        target = self.root / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        registry = self.registry(True)
        self.assertIn("blocked in Plan mode", registry.execute(
            "edit_file", {"path": "a.py", "old_text": "1", "new_text": "2"}, plan_mode=True))
        with self.assertRaisesRegex(ValueError, "outside"):
            registry.execute("edit_file", {"path": "../escape.py", "old_text": "1", "new_text": "2"})
        self.assertEqual(self.prompts, [])

    def test_edit_refuses_if_file_changes_while_approval_is_open(self):
        target = self.root / "a.py"
        target.write_text("value = 1\n", encoding="utf-8")

        def approve(_action, _preview):
            target.write_text("concurrent update\n", encoding="utf-8")
            return True

        with self.assertRaisesRegex(ValueError, "changed after approval"):
            ToolRegistry(self.root, approve=approve).execute(
                "edit_file", {"path": "a.py", "old_text": "value = 1", "new_text": "value = 2"}
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "concurrent update\n")


class TestWriteFile(Workspace):
    def test_write_refuses_if_existing_file_changes_during_approval(self):
        target = self.root / "a.txt"
        target.write_text("original\n", encoding="utf-8")

        def approve(_action, _preview):
            target.write_text("concurrent update\n", encoding="utf-8")
            return True

        with self.assertRaisesRegex(ValueError, "changed after approval"):
            ToolRegistry(self.root, approve=approve).execute(
                "write_file", {"path": "a.txt", "content": "model update\n"}
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "concurrent update\n")

    def test_write_does_not_replace_file_created_during_approval(self):
        target = self.root / "new.txt"

        def approve(_action, _preview):
            target.write_text("created while waiting\n", encoding="utf-8")
            return True

        with self.assertRaisesRegex(ValueError, "appeared after approval"):
            ToolRegistry(self.root, approve=approve).execute(
                "write_file", {"path": "new.txt", "content": "model update\n"}
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "created while waiting\n")


class TestPathSandbox(Workspace):
    def test_symlink_escaping_workspace_is_rejected(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        secret = Path(outside.name, "secret.txt")
        secret.write_text("top secret\n", encoding="utf-8")
        os.symlink(secret, self.root / "link.txt")
        registry = self.registry(True)
        with self.assertRaisesRegex(ValueError, "outside"):
            registry.execute("read_file", {"path": "link.txt"})
        with self.assertRaisesRegex(ValueError, "outside"):
            registry.execute("write_file", {"path": "link.txt", "content": "x"})
        self.assertEqual(secret.read_text(encoding="utf-8"), "top secret\n")

    def test_search_does_not_follow_file_or_directory_symlinks(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        external_file = Path(outside.name, "secret.txt")
        external_file.write_text("OUTSIDE_SEARCH_SENTINEL", encoding="utf-8")
        os.symlink(external_file, self.root / "linked-file.txt")
        os.symlink(outside.name, self.root / "linked-directory", target_is_directory=True)

        result = self.registry().execute("search_files", {"pattern": "OUTSIDE_SEARCH_SENTINEL"})

        self.assertEqual(result, "No matches found.")

    def test_absolute_and_excluded_paths_are_rejected(self):
        registry = self.registry(True)
        with self.assertRaisesRegex(ValueError, "outside"):
            registry.execute("read_file", {"path": "/etc/passwd"})
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "excluded"):
            registry.execute("read_file", {"path": ".git/config"})


class TestRunCommandPolicy(Workspace):
    def test_denied_executable_is_blocked_before_any_prompt(self):
        result = self.registry(True).execute("run_command", {"command": "sudo ls"})
        self.assertIn("blocked by policy", result)
        self.assertIn("Nothing was executed", result)
        self.assertEqual(self.prompts, [])

    def test_recursive_rm_outside_project_or_of_root_is_blocked(self):
        registry = self.registry(True)
        for command in ("rm -rf /", "rm -rf ..", "rm -r .", "rm -rf ~"):
            self.assertIn("blocked by policy", registry.execute("run_command", {"command": command}), command)
        (self.root / "build_out").mkdir()
        self.assertTrue(self.root.exists())

    def test_allow_list_restricts_executables(self):
        registry = self.registry(True, policy=CommandPolicy.from_dict({"allow": ["echo"]}))
        self.assertIn("not in the allowed list", registry.execute("run_command", {"command": "ls"}))
        self.assertTrue(registry.execute("run_command", {"command": "echo hi"}).endswith("hi"))

    def test_denial_by_user_runs_nothing(self):
        marker = self.root / "marker"
        result = self.registry(False).execute("run_command", {"command": f"touch {marker}"})
        self.assertIn("denied", result)
        self.assertFalse(marker.exists())

    def test_environment_is_minimal(self):
        os.environ["ZC_TEST_SECRET"] = "hunter2"
        self.addCleanup(os.environ.pop, "ZC_TEST_SECRET", None)
        result = self.registry(True).execute("run_command", {"command": "env"})
        self.assertNotIn("ZC_TEST_SECRET", result)
        passthrough = CommandPolicy.from_dict({"env_passthrough": ["ZC_TEST_SECRET"]})
        self.assertIn("ZC_TEST_SECRET", self.registry(True, policy=passthrough).execute("run_command", {"command": "env"}))

    def test_timeout_missing_binary_and_output_truncation_are_readable(self):
        policy = CommandPolicy.from_dict({"timeout": 1, "max_output_chars": 500})
        registry = self.registry(True, policy=policy)
        self.assertIn("timed out after 1s", registry.execute("run_command", {"command": "sleep 5"}))
        self.assertIn("Command not found", registry.execute("run_command", {"command": "definitely-not-a-binary"}))
        long = registry.execute("run_command", {"command": "seq 1 5000"})
        self.assertIn("characters omitted", long)

    def test_policy_loads_from_yaml_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory, "config.yaml")
            config_path.write_text("command_policy:\n  deny: [curl]\n  timeout: 5\n", encoding="utf-8")
            config = ConfigManager(user_config_path=config_path, env_file=str(Path(directory, ".env"))).load()
        self.assertIn("curl", config.command_policy.deny)
        self.assertIn("sudo", config.command_policy.deny)
        self.assertEqual(config.command_policy.timeout, 5)


class TestToolErrorsAreUnderstandable(Workspace):
    def test_missing_unknown_and_bad_arguments(self):
        registry = self.registry(True)
        with self.assertRaisesRegex(ValueError, "Missing required argument.*path"):
            registry.execute("read_file", {})
        with self.assertRaisesRegex(ValueError, "Unknown tool 'rm_rf'.*Available tools"):
            registry.execute("rm_rf", {})
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            registry.execute("list_files", {"limit": "many"})
        with self.assertRaisesRegex(ValueError, "Invalid regular expression"):
            registry.execute("search_files", {"pattern": "("})

    def test_agent_turns_tool_failures_into_results_for_the_model(self):
        provider = ScriptedProvider([
            ProviderTurn(tool_calls=[ToolCall("read_file", {}, "c1")]),
            ProviderTurn(content="I need a path."),
        ])
        agent = Agent(provider, tools=self.registry(True))
        self.assertEqual(agent.ask("read", use_tools=True), "I need a path.")
        tool_message = provider.requests[1][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertIn("Tool error: Missing required argument", tool_message["content"])

    def test_identical_repeated_tool_calls_stop_the_loop(self):
        calls = [ProviderTurn(tool_calls=[ToolCall("list_files", {}, f"c{i}")]) for i in range(10)]
        agent = Agent(ScriptedProvider(calls), tools=self.registry(True))
        result = agent.ask("loop", use_tools=True)
        self.assertIn("repeated the same list_files call", result)

    def test_round_limit_message_is_actionable(self):
        calls = [ProviderTurn(tool_calls=[ToolCall("list_files", {}, f"c{i}")]) for i in range(10)]
        agent = Agent(ScriptedProvider(calls), tools=self.registry(True), max_tool_rounds=2)
        agent.set_session_controls(effort="medium")
        result = agent.ask("loop", use_tools=True)
        self.assertIn("Tool round limit reached", result)
        self.assertIn("Ask me to continue", result)

    def test_provider_failure_propagates_as_a_clear_error(self):
        class Broken:
            def chat(self, messages, **kwargs):
                raise RuntimeError("OpenAI-compatible connection failed: refused")
        agent = Agent(Broken(), tools=self.registry(True))
        with self.assertRaisesRegex(RuntimeError, "connection failed"):
            agent.ask("hello", use_tools=True)
        self.assertEqual(agent.context.history, [])


class TestEndToEndCycle(Workspace):
    def test_read_search_then_proposed_edit_with_refusal_and_approval(self):
        (self.root / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
        edit = {"path": "app.py", "old_text": "return 'hi'", "new_text": "return 'hello'"}
        provider = ScriptedProvider([
            ProviderTurn(tool_calls=[ToolCall("search_files", {"pattern": "greet"}, "s1")]),
            ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "app.py"}, "r1")]),
            ProviderTurn(tool_calls=[ToolCall("edit_file", edit, "e1")]),
            ProviderTurn(content="Proposed the change; it was refused."),
            ProviderTurn(tool_calls=[ToolCall("edit_file", edit, "e2")]),
            ProviderTurn(content="Edit applied."),
        ])
        answers = iter([False, True])
        agent = Agent(provider, tools=ToolRegistry(self.root, approve=lambda a, p: next(answers)))
        events = []

        first = agent.ask("make greet friendlier", use_tools=True, on_event=lambda e: events.append(e.kind))
        self.assertEqual(first, "Proposed the change; it was refused.")
        self.assertIn("return 'hi'", (self.root / "app.py").read_text(encoding="utf-8"))
        self.assertIn("tool_denied", events)

        second = agent.ask("ok, apply it", use_tools=True)
        self.assertEqual(second, "Edit applied.")
        self.assertIn("return 'hello'", (self.root / "app.py").read_text(encoding="utf-8"))

    def test_sessions_do_not_share_history(self):
        with tempfile.TemporaryDirectory() as home:
            manager = SessionManager(Path(home))
            a = manager.create("p", "m", "code", str(self.root))
            b = manager.create("p", "m", "code", str(self.root))
            a.history.append({"role": "user", "content": "secret of session A"})
            manager.save(a)
            reloaded_b = manager.load(b.id)
            self.assertNotIn("secret of session A", str(reloaded_b.history))


if __name__ == "__main__":
    unittest.main()
