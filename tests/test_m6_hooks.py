import json
import sys
import tempfile
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.command_policy import CommandPolicy
from zerocoding.core.hooks import HookRunner, parse_hooks
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn, ToolCall

PY = sys.executable


class Scripted:
    def __init__(self, turns):
        self.turns, self.requests = list(turns), []

    def chat(self, messages, **kwargs):
        self.requests.append([dict(m) for m in messages])
        return self.turns.pop(0)


class HookTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name).resolve()
        (self.root / "a.py").write_text("x = 1\n", encoding="utf-8")

    def runner(self, entries, **kwargs):
        hooks, errors = parse_hooks(entries)
        self.assertEqual(errors, [])
        return HookRunner(hooks, self.root, **kwargs)

    def agent(self, turns, hooks, approve=True):
        agent = Agent(Scripted(turns), tools=ToolRegistry(self.root, approve=lambda a, p: approve))
        agent.hooks = hooks
        return agent

    def edit_turns(self):
        return [ProviderTurn(tool_calls=[ToolCall("edit_file", {"path": "a.py", "old_text": "1", "new_text": "2"}, "e")]),
                ProviderTurn(content="done")]

    def test_parse_reports_invalid_entries_without_raising(self):
        hooks, errors = parse_hooks([
            {"event": "nope", "command": "x"}, {"event": "pre_tool"}, "text",
            {"event": "post_tool", "command": "true", "timeout": "abc"},
            {"event": "pre_tool", "command": "true", "blocking": True, "match": ["edit_*"]},
        ])
        self.assertEqual(len(hooks), 1)
        self.assertTrue(hooks[0].blocking)
        self.assertEqual(len(errors), 4)

    def test_blocking_pre_hook_refuses_call_before_approval_prompt(self):
        prompts = []
        hook = self.runner([{"event": "pre_tool", "name": "guard", "blocking": True, "match": "edit_file",
                             "command": f"{PY} -c \"import sys; print('protected'); sys.exit(1)\""}])
        agent = Agent(Scripted(self.edit_turns()), tools=ToolRegistry(self.root, approve=lambda a, p: prompts.append(a) or True))
        agent.hooks = hook
        events = []
        agent.ask("edit", use_tools=True, on_event=lambda e: events.append(e.kind))
        self.assertEqual((self.root / "a.py").read_text(encoding="utf-8"), "x = 1\n")
        self.assertEqual(prompts, [])
        self.assertIn("tool_denied", events)
        tool_msg = agent.provider.requests[1][-1]["content"]
        self.assertIn("Blocked by hook 'guard': exit 1: protected", tool_msg)

    def test_non_blocking_pre_hook_failure_does_not_stop_the_call(self):
        hook = self.runner([{"event": "pre_tool", "command": f"{PY} -c \"import sys; sys.exit(3)\""}])
        self.agent(self.edit_turns(), hook).ask("edit", use_tools=True)
        self.assertEqual((self.root / "a.py").read_text(encoding="utf-8"), "x = 2\n")
        self.assertTrue(hook.last_failures)

    def test_hook_cannot_approve_a_denied_write(self):
        hook = self.runner([{"event": "pre_tool", "command": "true"}, {"event": "post_tool", "command": "true"}])
        self.agent(self.edit_turns(), hook, approve=False).ask("edit", use_tools=True)
        self.assertEqual((self.root / "a.py").read_text(encoding="utf-8"), "x = 1\n")

    def test_post_hook_failure_is_reported_to_the_model_success_is_silent(self):
        failing = self.runner([{"event": "post_tool", "name": "lint", "match": "edit_file", "path": "*.py",
                                "command": f"{PY} -c \"import sys; print('E101 bad'); sys.exit(2)\""}])
        agent = self.agent(self.edit_turns(), failing)
        agent.ask("edit", use_tools=True)
        self.assertIn("[hook 'lint' failed — exit 2: E101 bad]", agent.provider.requests[1][-1]["content"])
        silent = self.runner([{"event": "post_tool", "command": f"{PY} -c \"print('noisy but ok')\""}])
        (self.root / "a.py").write_text("x = 1\n", encoding="utf-8")
        agent = self.agent(self.edit_turns(), silent)
        agent.ask("edit", use_tools=True)
        self.assertNotIn("noisy", agent.provider.requests[1][-1]["content"])

    def test_matching_by_tool_and_path(self):
        ran = self.root / "ran.txt"
        code = f"open(r'{ran}', 'a').write('x')"
        hook = self.runner([{"event": "post_tool", "match": ["read_file"], "path": "*.md", "command": f"{PY} -c \"{code}\""}])
        turns = [ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "a.py"}, "r")]), ProviderTurn(content="ok")]
        self.agent(turns, hook).ask("read", use_tools=True)
        self.assertFalse(ran.exists())

    def test_plan_mode_skips_hooks_for_blocked_tools(self):
        ran = self.root / "ran.txt"
        code = f"open(r'{ran}', 'a').write('x')"
        hook = self.runner([{"event": "pre_tool", "command": f"{PY} -c \"{code}\""}])
        agent = self.agent(self.edit_turns(), hook)
        agent.set_session_controls(plan_mode=True)
        agent.ask("edit", use_tools=True)
        self.assertFalse(ran.exists())
        self.assertEqual((self.root / "a.py").read_text(encoding="utf-8"), "x = 1\n")

    def test_hooks_run_under_command_policy_and_minimal_environment(self):
        denied = self.runner([{"event": "pre_tool", "blocking": True, "command": "sudo true"}])
        self.assertIn("command policy", denied.pre_tool("read_file", "a.py", {}))
        out = self.root / "env.json"
        code = f"import os, json; open(r'{out}', 'w').write(json.dumps({{k: v for k, v in os.environ.items() if k.startswith('ZC_')}}))"
        hook = self.runner([{"event": "post_tool", "command": f"{PY} -c \"{code}\""}])
        hook.post_tool("read_file", "a.py", {"path": "a.py"})
        env = json.loads(out.read_text())
        self.assertEqual(env, {"ZC_HOOK_EVENT": "post_tool", "ZC_TOOL_NAME": "read_file", "ZC_TOOL_TARGET": "a.py"})

    def test_timeout_and_missing_binary_fail_closed_for_blocking_hooks(self):
        hook = self.runner([{"event": "pre_tool", "blocking": True, "timeout": 1, "command": "sleep 5"}])
        self.assertIn("timed out", hook.pre_tool("read_file", "", {}))
        hook = self.runner([{"event": "pre_tool", "blocking": True, "command": "no-such-binary-zc"}])
        self.assertIn("command not found", hook.pre_tool("read_file", "", {}))

    def test_turn_end_hook_runs_and_receives_stdin_payload(self):
        out = self.root / "stdin.json"
        code = f"import sys; open(r'{out}', 'w').write(sys.stdin.read())"
        hook = self.runner([{"event": "turn_end", "command": f"{PY} -c \"{code}\""}])
        agent = Agent(Scripted([ProviderTurn(content="hi")]))
        agent.hooks = hook
        agent.ask("hello")
        self.assertEqual(json.loads(out.read_text())["event"], "turn_end")


if __name__ == "__main__":
    unittest.main()
