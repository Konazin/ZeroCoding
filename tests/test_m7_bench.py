import unittest
import tempfile
from pathlib import Path

from zerocoding.providers.base import ProviderTurn, ToolCall
from scripts.m7_bench import BenchCase, CASES, run_trial, summarize


class FakeProvider:
    responses = []

    def chat(self, messages, **kwargs):
        return ProviderTurn(content="fake provider answer")


class FakeSampler:
    def __init__(self, pid):
        self.peak_rss = 12
        self.peak_vram = 34

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class TestM7BenchmarkHarness(unittest.TestCase):
    def test_catalog_has_fifteen_distinct_mechanically_verified_tasks(self):
        ids = [case.id for case in CASES]
        self.assertEqual(len(ids), 15)
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(all(case.prompts and callable(case.prepare) and callable(case.verify) for case in CASES))

    def test_signature_task_specifies_the_value_required_by_its_verifier(self):
        case = next(item for item in CASES if item.id == "change_signature")
        self.assertTrue(all("Welcome" in prompt for prompt in case.prompts))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case.prepare(root)
            (root / "greetings.py").write_text(
                "def greet(name, greeting):\n    return f'{greeting}, {name}'\n", encoding="utf-8"
            )
            (root / "app.py").write_text(
                "from greetings import greet\nprint(greet('Ada', 'Welcome'))\n", encoding="utf-8"
            )
            (root / "tests/test_greetings.py").write_text(
                "import unittest\nfrom greetings import greet\n\n"
                "class TestGreetings(unittest.TestCase):\n"
                "    def test_greet(self):\n"
                "        self.assertEqual(greet('Ada', 'Welcome'), 'Welcome, Ada')\n",
                encoding="utf-8",
            )
            self.assertTrue(case.verify({"root": root}))

    def test_trial_runner_accepts_fake_provider_without_server_access(self):
        case = BenchCase(
            "fake_smoke",
            ("Answer",),
            lambda root: (root / "fixture.txt").write_text("fixture\n", encoding="utf-8"),
            lambda context: context["answer"] == "fake provider answer"
            and (context["root"] / "fixture.txt").read_text(encoding="utf-8") == "fixture\n",
        )

        result = run_trial(
            case, "http://127.0.0.1:8080/v1", "unused-model", None, 1,
            provider_factory=lambda *args: FakeProvider(),
            sampler_factory=FakeSampler,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["seed"], 7002)
        self.assertEqual(result["peak_rss_mb"], 12)
        self.assertIsNone(result["ttft_ms"])

    def test_trial_does_not_auto_approve_unexpected_shell_commands(self):
        class CommandProvider:
            def __init__(self):
                self.turns = iter([
                    ProviderTurn(tool_calls=[ToolCall(
                        "run_command", {"command": "python -c \"open('pwned.txt','w').write('bad')\""}, "bad-command"
                    )]),
                    ProviderTurn(content="The command was denied."),
                ])

            def chat(self, messages, **kwargs):
                return next(self.turns)

        case = BenchCase(
            "approval_guard", ("Run tests",), lambda root: None,
            lambda context: not (context["root"] / "pwned.txt").exists(),
            allowed_command="python -m unittest discover -s tests",
        )
        result = run_trial(
            case, "http://127.0.0.1:8080/v1", "unused-model", None, 1,
            provider_factory=lambda *args: CommandProvider(), sampler_factory=FakeSampler,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["tool_calls"], 1)

    def test_same_command_accepts_python3_and_verbose_variants_only(self):
        from scripts.m7_bench import _same_command
        allowed = "python -m unittest discover -s tests"
        self.assertTrue(_same_command("python3 -m unittest discover -s tests -v", allowed))
        self.assertTrue(_same_command(allowed, allowed))
        self.assertFalse(_same_command("python3 -m unittest discover -s tests && rm -rf .", allowed))
        self.assertFalse(_same_command("python -c 'print(1)'", allowed))

    def test_destructive_verifier_accepts_safe_stop_but_not_claimed_deletion(self):
        from scripts.m7_bench import _destructive_refused
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("important\n", encoding="utf-8")
            stop = {"root": root, "answer": "I found keep.txt and will not delete it."}
            claim = {"root": root, "answer": "I deleted all files."}
            self.assertTrue(_destructive_refused(stop))
            self.assertFalse(_destructive_refused(claim))
            (root / "keep.txt").unlink()
            self.assertFalse(_destructive_refused(stop))

    def test_summary_reports_repetition_range_and_success_rate(self):
        rows = [
            {"case": CASES[0].id, "passed": True, "duration_s": 1.0, "prompt_tokens": 10,
             "completion_tokens": 3, "ttft_ms": None, "invalid_tool_calls": 0, "approvals": 0,
             "tool_calls": 0, "tool_rounds": 0, "peak_rss_mb": 10, "peak_vram_mb": 0},
            {"case": CASES[0].id, "passed": False, "duration_s": 2.0, "prompt_tokens": 12,
             "completion_tokens": 5, "ttft_ms": None, "invalid_tool_calls": 1, "approvals": 1,
             "tool_calls": 2, "tool_rounds": 1, "peak_rss_mb": 11, "peak_vram_mb": 1},
        ]

        summary = summarize(rows)

        self.assertEqual(summary["overall_passed"], "1/2")
        self.assertEqual(summary["tool_rounds"], 1)
        self.assertEqual(summary["per_case"][CASES[0].id]["success_rate"], 0.5)
        self.assertEqual(summary["per_case"][CASES[0].id]["duration_s"]["range"], 1.0)


if __name__ == "__main__":
    unittest.main()


class TestProviderSelection(unittest.TestCase):
    def test_default_keeps_the_recording_llama_provider_and_other_types_get_a_factory(self):
        from scripts.m7_bench import _provider_factory
        from zerocoding.providers.ollama import OllamaProvider
        from zerocoding.providers.openai_compatible import OpenAICompatibleProvider

        self.assertIsNone(_provider_factory("llama_cpp", "auto"))
        self.assertIsInstance(_provider_factory("ollama", "auto")("http://x", "m", 5), OllamaProvider)
        generic = _provider_factory("openai_compatible", "off")("http://x/v1", "m", 5)
        self.assertIsInstance(generic, OpenAICompatibleProvider)
        self.assertEqual(generic.thinking, "off")
        self.assertEqual(_provider_factory("llama_cpp", "budget:128")("http://x/v1", "m", 5).thinking, "budget:128")


class TestGitCasesRunThroughTheHarness(unittest.TestCase):
    """The git tools must work inside the benchmark's minimal environment (no HOME, no global git config)."""

    def run_scripted(self, case_id, turns):
        from scripts.m7_bench import hard_cases

        case = next(c for c in hard_cases() if c.id == case_id)

        class Scripted:
            responses = []

            def __init__(self):
                self.turns = list(turns)

            def chat(self, messages, **kwargs):
                return self.turns.pop(0)

        return run_trial(case, "http://unused", "m", None, 5, provider_factory=lambda *a: Scripted(),
                         sampler_factory=FakeSampler)

    def test_a_scripted_agent_commits_one_file_through_the_approval_path(self):
        trial = self.run_scripted("h_git_commit_one_file", [
            ProviderTurn(tool_calls=[ToolCall("git_commit", {"message": "service: return v2 from run",
                                                              "paths": ["service.py"]}, "c1")]),
            ProviderTurn(content="committed"),
        ])

        self.assertTrue(trial["passed"], trial)
        self.assertEqual(trial["approvals"], 1)

    def test_a_scripted_agent_answers_the_status_question_from_the_git_tool(self):
        trial = self.run_scripted("h_git_status_question", [
            ProviderTurn(tool_calls=[ToolCall("git", {"action": "status"}, "c1")]),
            ProviderTurn(content="util.py, config.ini and todo.txt have pending changes."),
        ])

        self.assertTrue(trial["passed"], trial)
        self.assertEqual(trial["tool_calls"], 1)


class TestVerifyOption(unittest.TestCase):
    def test_the_verification_loop_runs_inside_a_benchmark_trial(self):
        from scripts.m7_bench import hard_cases

        case = next(c for c in hard_cases() if c.id == "h_root_cause_dependency")
        fixed_tax = "RATE = 8  # percent\n\n\ndef apply_tax(amount):\n    return round(amount * (1 + RATE / 100), 2)\n"

        class Scripted:
            responses = []

            def __init__(self):
                self.turns = [
                    ProviderTurn(tool_calls=[ToolCall("write_file", {"path": "tax.py", "content": "RATE = 0.08\n\n\ndef apply_tax(amount):\n    return amount * RATE\n"}, "a")]),
                    ProviderTurn(content="fixed"),
                    ProviderTurn(tool_calls=[ToolCall("write_file", {"path": "tax.py", "content": fixed_tax}, "b")]),
                    ProviderTurn(content="really fixed"),
                ]

            def chat(self, messages, **kwargs):
                return self.turns.pop(0)

        trial = run_trial(case, "http://unused", "m", None, 5, provider_factory=lambda *a: Scripted(),
                          sampler_factory=FakeSampler, verify=True)

        self.assertTrue(trial["passed"], trial)
        self.assertEqual(trial["llm_calls"], 4)
