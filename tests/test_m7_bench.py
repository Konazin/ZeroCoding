import unittest

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
