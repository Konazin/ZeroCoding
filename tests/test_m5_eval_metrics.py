import unittest

from scripts.m5_eval import CASES, summarize


class TestM5EvaluationMetrics(unittest.TestCase):
    def test_summary_includes_true_ttft_when_streaming_is_enabled(self):
        case = CASES[0]["id"]
        trials = [
            {"case": case, "passed": True, "duration_s": 1.0, "prompt_tokens": 20,
             "completion_tokens": 5, "first_prompt_ms": None, "ttft_ms": 100.0,
             "gen_tokens_per_s": None, "tool_calls": 0, "tool_rounds": 0, "tool_errors": 0,
             "peak_rss_mb": 10, "peak_vram_mb": 0},
            {"case": case, "passed": True, "duration_s": 1.5, "prompt_tokens": 22,
             "completion_tokens": 6, "first_prompt_ms": None, "ttft_ms": 125.0,
             "gen_tokens_per_s": None, "tool_calls": 0, "tool_rounds": 0, "tool_errors": 0,
             "peak_rss_mb": 11, "peak_vram_mb": 0},
        ]

        summary = summarize(trials)

        self.assertEqual(summary["per_case"][case]["ttft_ms"], {"median": 112.5, "worst": 125.0})


if __name__ == "__main__":
    unittest.main()
