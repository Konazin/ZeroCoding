import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.agent import Agent
from zerocoding.core.config import ConfigManager
from zerocoding.core.headless import HeadlessOptions, make_approver, run_headless
from zerocoding.core.tools import ToolRegistry
from zerocoding.core.verify import Verifier, VerifyConfig
from zerocoding.providers.base import ProviderTurn, ToolCall

TEST_COMMAND = f"{sys.executable} -m unittest discover -s tests"
BUGGY = "def double(x):\n    return x * 3\n"
FIXED = "def double(x):\n    return x * 2\n"
TEST = "import unittest\nfrom calc import double\n\n\nclass T(unittest.TestCase):\n    def test_double(self):\n        self.assertEqual(double(4), 8)\n"


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)

    def chat(self, messages, **kwargs):
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def write(path, content, call_id="c"):
    return ProviderTurn(tool_calls=[ToolCall("write_file", {"path": path, "content": content}, call_id)])


class HeadlessCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root / "calc.py").write_text(BUGGY)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_calc.py").write_text(TEST)

    def run_task(self, turns, options=None, verify=False):
        agent = Agent(Scripted(turns), tools=ToolRegistry(self.root))
        if verify:
            agent.verifier = Verifier(self.root, VerifyConfig(True, (TEST_COMMAND,), 2, 60))
        out, err = io.StringIO(), io.StringIO()
        code = run_headless(agent, "fix calc", self.root, options or HeadlessOptions(), out, err)
        return code, out.getvalue(), err.getvalue(), agent


class TestPermissions(HeadlessCase):
    def test_default_is_read_only_and_a_write_attempt_changes_nothing(self):
        code, out, err, _ = self.run_task([write("calc.py", FIXED), ProviderTurn(content="could not write")])

        self.assertEqual(code, 0)
        self.assertIn("could not write", out)
        self.assertEqual((self.root / "calc.py").read_text(), BUGGY)
        self.assertIn("read-only", err)

    def test_write_flag_approves_edits_and_reports_the_changed_files(self):
        code, out, err, _ = self.run_task([write("calc.py", FIXED), ProviderTurn(content="fixed")], HeadlessOptions(write=True))

        self.assertEqual(code, 0)
        self.assertEqual((self.root / "calc.py").read_text(), FIXED)
        self.assertIn("● write_file calc.py", err)

    def test_the_approver_never_approves_commits_network_or_installs(self):
        denied = []
        auto = make_approver(self.root, HeadlessOptions(write=True, commands="auto"), denied)
        none = make_approver(self.root, HeadlessOptions(write=True), [])

        self.assertTrue(auto("Write file", "diff") and auto("Edit file", "diff"))
        self.assertTrue(auto("Run command", "ls -la") and auto("Run command", "git status"))
        self.assertTrue(auto("Run verification", "python -m pytest -q"))
        for command in ("curl https://x", "pip install x", "rm a.py", "git push", "cat /etc/passwd", "ls ../.."):
            self.assertFalse(auto("Run command", command), command)
        self.assertFalse(auto("Git commit", "msg") or none("Git commit", "msg"))
        self.assertFalse(auto("Run external tool", "x"))
        self.assertFalse(none("Run command", "ls") or none("Run verification", "python -m pytest"))
        self.assertTrue(len(denied) >= 7)

    def test_without_write_the_agent_is_in_plan_mode(self):
        _, _, _, agent = self.run_task([ProviderTurn(content="ok")])
        self.assertTrue(agent.plan_mode)
        _, _, _, agent = self.run_task([ProviderTurn(content="ok")], HeadlessOptions(write=True))
        self.assertFalse(agent.plan_mode)


class TestVerificationAndOutput(HeadlessCase):
    def test_a_verified_fix_exits_zero_with_json_describing_the_run(self):
        code, out, _, _ = self.run_task([
            write("calc.py", BUGGY + "# still wrong\n", "a"), ProviderTurn(content="done"),
            write("calc.py", FIXED, "b"), ProviderTurn(content="now it is fixed"),
        ], HeadlessOptions(write=True, as_json=True, quiet=True), verify=True)

        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((data["outcome"], data["verified"], data["files_changed"]), ("ok", True, ["calc.py"]))
        self.assertEqual(data["answer"], "now it is fixed")
        self.assertEqual(data["stats"]["verify_runs"], 2)
        self.assertEqual(data["stats"]["verify_failures"], 1)

    def test_a_fix_that_stays_broken_exits_two_so_ci_can_fail(self):
        wrong = "def double(x):\n    return 0\n"
        code, out, _, _ = self.run_task([
            write("calc.py", wrong, "a"), ProviderTurn(content="done"),
            write("calc.py", wrong + "\n", "b"), ProviderTurn(content="done"),
            write("calc.py", wrong + "\n\n", "c"), ProviderTurn(content="done"),
        ], HeadlessOptions(write=True, as_json=True, quiet=True), verify=True)

        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertIs(data["verified"], False)
        self.assertIn("Not verified", data["answer"])

    def test_a_provider_failure_is_a_clean_error_exit(self):
        code, out, err, _ = self.run_task([RuntimeError("model server is down")])

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("model server is down", err)

    def test_json_error_report_and_round_cap(self):
        code, out, _, agent = self.run_task([RuntimeError("boom")], HeadlessOptions(as_json=True, quiet=True, max_rounds=3))

        data = json.loads(out)
        self.assertEqual((code, data["outcome"], data["error"]), (1, "error", "boom"))
        self.assertEqual(agent.max_tool_rounds, 3)

    def test_denied_actions_are_listed_in_json(self):
        code, out, _, _ = self.run_task([
            ProviderTurn(tool_calls=[ToolCall("run_command", {"command": "ls"}, "a")]), ProviderTurn(content="no")],
            HeadlessOptions(write=True, as_json=True, quiet=True))

        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(any("Run command" in item for item in data["denied"]))


class TestCommandLine(unittest.TestCase):
    def main(self, argv, turns=()):
        from zerocoding import cli
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "work").mkdir()
            manager = ConfigManager(user_config_path=home / "c.yaml", env_file=str(home / "none"))
            out, err = io.StringIO(), io.StringIO()
            previous = os.getcwd()
            os.chdir(home / "work")
            try:
                with patch.object(cli, "ConfigManager", lambda: manager), \
                        patch.object(cli, "build_provider", lambda config: Scripted(turns)), \
                        patch.object(cli, "load_env", lambda: None), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(argv)
            finally:
                os.chdir(previous)
            return code, out.getvalue(), err.getvalue()

    def test_run_needs_a_task(self):
        code, _, err = self.main(["run"])

        self.assertEqual(code, 2)
        self.assertIn("needs the task", err)

    def test_run_answers_a_question_end_to_end_through_the_cli(self):
        code, out, _ = self.main(["run", "-m", "say hi", "--json", "--quiet"], [ProviderTurn(content="hi there")])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["answer"], "hi there")


if __name__ == "__main__":
    unittest.main()
