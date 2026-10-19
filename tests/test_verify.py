import json
import sys
import tempfile
import unittest
from pathlib import Path

from zerocoding.commands import handle_verify
from zerocoding.core.agent import Agent
from zerocoding.core.command_policy import CommandPolicy
from zerocoding.core.permissions import PermissionPolicy
from zerocoding.core.tools import ToolRegistry
from zerocoding.core.verify import Verifier, VerifyConfig, detect_command, trim_output
from zerocoding.providers.base import ProviderTurn, ToolCall

TEST_COMMAND = f"{sys.executable} -m unittest discover -s tests"
BUGGY = "def double(x):\n    return x * 3\n"
FIXED = "def double(x):\n    return x * 2\n"
TEST = "import unittest\nfrom calc import double\n\n\nclass T(unittest.TestCase):\n    def test_double(self):\n        self.assertEqual(double(4), 8)\n"


class Scripted:
    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def chat(self, messages, **kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.turns.pop(0)


def write(path, content, call_id="c"):
    return ProviderTurn(tool_calls=[ToolCall("write_file", {"path": path, "content": content}, call_id)])


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root / "calc.py").write_text(BUGGY)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_calc.py").write_text(TEST)
        self.asked = []

    def agent(self, turns, *, commands=(TEST_COMMAND,), attempts=2, approve=True, policy=None, enabled=True):
        def ask(action, preview):
            self.asked.append((action, preview))
            return approve
        registry = ToolRegistry(self.root, approve=ask, policy=policy or CommandPolicy())
        provider = Scripted(turns)
        agent = Agent(provider, tools=registry)
        agent.verifier = Verifier(self.root, VerifyConfig(enabled, tuple(commands), attempts, 60))
        self.provider = provider
        self.events = []
        return agent

    def ask(self, agent, text="fix calc"):
        return agent.ask(text, use_tools=True, on_event=self.events.append)

    def kinds(self):
        return [e.kind for e in self.events if e.kind.startswith("verify")]


class TestVerifyLoop(ProjectCase):
    def test_a_failing_check_is_shown_to_the_model_which_fixes_it_and_passes(self):
        agent = self.agent([
            write("calc.py", "def double(x):\n    return x + x + 1\n", "c1"),  # still wrong
            ProviderTurn(content="done, it is fixed"),
            write("calc.py", FIXED, "c2"),
            ProviderTurn(content="really fixed now"),
        ])

        answer = self.ask(agent)

        self.assertEqual(answer, "really fixed now")
        self.assertEqual(self.kinds(), ["verify_started", "verify_failed", "verify_started", "verify_passed"])
        feedback = [m for m in self.provider.seen[2] if m["role"] == "user" and "Verification failed" in m["content"]]
        self.assertEqual(len(feedback), 1)
        self.assertIn("AssertionError", feedback[0]["content"])
        self.assertEqual(agent.last_turn["verify_runs"], 2)
        self.assertEqual(agent.last_turn["verify_failures"], 1)
        self.assertEqual((self.root / "calc.py").read_text(), FIXED)

    def test_a_passing_check_adds_nothing_to_the_conversation(self):
        agent = self.agent([write("calc.py", FIXED), ProviderTurn(content="fixed")])

        self.assertEqual(self.ask(agent), "fixed")
        self.assertEqual(self.kinds(), ["verify_started", "verify_passed"])
        self.assertEqual(len(self.provider.turns), 0)
        self.assertFalse(any("Verification" in str(m.get("content")) for m in self.provider.seen[-1]))

    def test_no_edits_means_no_verification(self):
        agent = self.agent([ProviderTurn(content="just an answer")])

        self.assertEqual(self.ask(agent, "what is 1+1"), "just an answer")
        self.assertEqual(self.kinds(), [])

    def test_a_denied_edit_does_not_trigger_verification(self):
        agent = self.agent([write("calc.py", FIXED), ProviderTurn(content="could not write")], approve=False)

        self.ask(agent)

        self.assertEqual(self.kinds(), [])
        self.assertEqual((self.root / "calc.py").read_text(), BUGGY)

    def test_attempts_are_bounded_and_the_answer_says_it_is_unverified(self):
        wrong = "def double(x):\n    return 0\n"
        agent = self.agent([write("calc.py", wrong, "c1"), ProviderTurn(content="done"),
                            write("calc.py", wrong + "\n", "c2"), ProviderTurn(content="done again")], attempts=1)

        answer = self.ask(agent)

        self.assertIn("done again", answer)
        self.assertIn("Not verified", answer)
        self.assertEqual(self.kinds().count("verify_started"), 2)  # first run + one re-run after one fix round
        self.assertEqual(self.provider.turns, [])  # and no model call is wasted after the last failing run

    def test_a_command_the_policy_blocks_is_reported_without_looping(self):
        policy = CommandPolicy(allow=frozenset({"ls"}))
        agent = self.agent([write("calc.py", FIXED), ProviderTurn(content="written, but I could not verify")], policy=policy)

        answer = self.ask(agent)

        self.assertIn("Not verified", answer)
        self.assertIn("blocked by policy", answer)
        self.assertEqual(self.kinds().count("verify_started"), 1)

    def test_a_missing_executable_is_a_problem_not_a_crash(self):
        agent = self.agent([write("calc.py", FIXED), ProviderTurn(content="ok")], commands=("definitely-not-a-binary",))

        self.assertIn("Not verified", self.ask(agent))

    def test_disabled_verifier_and_plan_mode_stay_quiet(self):
        agent = self.agent([write("calc.py", FIXED), ProviderTurn(content="ok")], enabled=False)
        self.ask(agent)
        self.assertEqual(self.kinds(), [])

    def test_the_conversation_after_a_failure_stays_in_order(self):
        agent = self.agent([write("calc.py", BUGGY + "# touched\n"), ProviderTurn(content="done"),
                            write("calc.py", FIXED), ProviderTurn(content="ok")])

        self.ask(agent)

        roles = [m["role"] for m in self.provider.seen[2]]
        self.assertEqual(roles[-2:], ["assistant", "user"])  # the finished reply, then the failure report


class TestVerifierApproval(ProjectCase):
    def detected_verifier(self, approve):
        registry = ToolRegistry(self.root, approve=lambda a, p: (self.asked.append((a, p)) or approve))
        return Verifier(self.root, VerifyConfig()), registry

    def test_a_configured_command_is_trusted_and_never_asks(self):
        agent = self.agent([write("calc.py", FIXED), ProviderTurn(content="ok")])

        self.ask(agent)

        self.assertNotIn("Run verification", [a for a, _ in self.asked])

    def test_a_detected_command_is_asked_once_then_remembered(self):
        verifier, registry = self.detected_verifier(True)

        first = verifier.run(registry)
        second = verifier.run(registry)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual([a for a, _ in self.asked].count("Run verification"), 1)
        self.assertIn("unittest", self.asked[0][1])

    def test_refusing_switches_verification_off_until_the_user_turns_it_on(self):
        verifier, registry = self.detected_verifier(False)

        self.assertIsNone(verifier.run(registry))
        self.assertFalse(verifier.enabled)
        self.assertIsNone(verifier.run(registry))
        self.assertEqual([a for a, _ in self.asked].count("Run verification"), 1)
        verifier.reset(enabled=True)
        self.assertTrue(verifier.enabled)
        self.assertIsNone(verifier.approved)


class TestDetection(unittest.TestCase):
    def detect(self, files, pytest=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            return detect_command(root, lambda: pytest)

    def test_python_projects_pick_pytest_when_available_else_unittest(self):
        self.assertTrue(self.detect({"tests/test_a.py": ""}, pytest=True).endswith("-m pytest -q -x"))
        self.assertTrue(self.detect({"tests/test_a.py": ""}).endswith("-m unittest discover -s tests"))
        self.assertTrue(self.detect({"test_a.py": ""}).endswith("-m unittest discover"))
        self.assertTrue(self.detect({"pyproject.toml": "[tool.pytest.ini_options]\n"}, pytest=True).endswith("pytest -q -x"))

    def test_other_ecosystems(self):
        self.assertEqual(self.detect({"package.json": json.dumps({"scripts": {"test": "jest"}})}), "npm test --silent")
        self.assertIsNone(self.detect({"package.json": json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}})}))
        self.assertEqual(self.detect({"Cargo.toml": "[package]"}), "cargo test -q")
        self.assertEqual(self.detect({"go.mod": "module x"}), "go test ./...")

    def test_unrecognised_projects_verify_nothing(self):
        self.assertIsNone(self.detect({"README.md": "hi"}))


class TestOutputAndConfig(unittest.TestCase):
    def test_long_output_keeps_the_head_and_the_failing_tail(self):
        text = "collected 10 items\n" + "noise line\n" * 2000 + "FAILED tests/test_x.py::test_y - AssertionError\n1 failed"

        trimmed = trim_output(text)

        self.assertLessEqual(len(trimmed), 3100)
        self.assertIn("collected 10 items", trimmed)
        self.assertIn("FAILED tests/test_x.py::test_y", trimmed)
        self.assertIn("omitted", trimmed)

    def test_ansi_colours_are_stripped_and_short_output_is_untouched(self):
        self.assertEqual(trim_output("\x1b[31mred\x1b[0m failure"), "red failure")

    def test_config_parsing_is_forgiving_and_bounded(self):
        config = VerifyConfig.from_dict({"enabled": "false", "commands": "pytest -q", "max_attempts": 99, "timeout": 1})

        self.assertFalse(config.enabled)
        self.assertEqual(config.commands, ("pytest -q",))
        self.assertEqual((config.max_attempts, config.timeout), (5, 5))
        self.assertTrue(VerifyConfig.from_dict(None).enabled)
        self.assertEqual(VerifyConfig.from_dict({"commands": list("abcdef")}).commands, ("a", "b", "c"))


class TestPermissionsAndCommand(unittest.TestCase):
    def test_verification_follows_the_command_rules_of_each_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(PermissionPolicy(tmp, "ask").decide("Run verification", "python -m pytest -q -x"))
            self.assertIsNone(PermissionPolicy(tmp, "auto").decide("Run verification", "python -m pytest -q -x"))
            self.assertIsNotNone(PermissionPolicy(tmp, "auto", ("fs", "read", "git", "tests")).decide("Run verification", "python -m pytest -q"))
            self.assertIsNotNone(PermissionPolicy(tmp, "yolo").decide("Run verification", "python -m pytest -q -x"))
            self.assertIsNone(PermissionPolicy(tmp, "yolo").decide("Run verification", "pip install x"))

    def test_the_verify_command_shows_changes_and_validates_arguments(self):
        class Tui:
            def __init__(self): self.out = []
            def show_info(self, t): self.out.append(("info", t))
            def show_success(self, t): self.out.append(("ok", t))
            def show_error(self, t): self.out.append(("err", t))

        with tempfile.TemporaryDirectory() as tmp:
            agent = Agent(Scripted([]), tools=ToolRegistry(tmp))
            agent.verifier = Verifier(tmp, VerifyConfig())
            tui = Tui()
            handle_verify("", tui, agent)
            handle_verify("off", tui, agent)
            handle_verify("set make check", tui, agent)
            handle_verify("bogus", tui, agent)

            self.assertEqual([k for k, _ in tui.out], ["info", "ok", "ok", "err"])
            self.assertIn("make check", agent.verifier.status())
            self.assertTrue(agent.verifier.enabled and agent.verifier.trusted)
            agent.verifier = None
            handle_verify("", tui, agent)
            self.assertIn("disabled", tui.out[-1][1])


if __name__ == "__main__":
    unittest.main()
