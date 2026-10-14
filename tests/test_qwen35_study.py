import json
import tempfile
import unittest
from pathlib import Path

from scripts.qwen35_thinking_effort_study import (
    DEFAULT_REPETITIONS,
    HostSampler,
    TEST_COMMAND,
    _quantiles,
    _select_model_tag,
    _timeout_is_twenty,
    build_matrix,
    run_trial,
    summarize_run,
)
from zerocoding.providers.base import ProviderTurn, ToolCall


class FakeProvider:
    def __init__(self, url, model):
        self.model = model

    def chat(self, messages, **kwargs):
        task = next((message.get("content", "") for message in reversed(messages) if message.get("role") == "user"), "")
        tool_results = [message.get("content", "") for message in messages if message.get("role") == "tool"]
        if "calculate the tax" in task:
            return ProviderTurn(content="$20.00")
        if "format_total" in task:
            if not tool_results:
                return ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "src/calculations.py"})])
            return ProviderTurn(content="format_total sums item prices and formats a dollar amount to two decimals.")
        if "Prepare a concise plan" in task:
            return ProviderTurn(content="Plan: read settings.py, change the timeout to 20, then run its tests.")
        if "Request approval" in task:
            if not tool_results:
                return ProviderTurn(tool_calls=[ToolCall("write_file", {
                    "path": "src/settings.py", "content": "TIMEOUT_SECONDS = 20\n",
                })])
            return ProviderTurn(content="The write was denied and no file was changed.")
        if "Set `TIMEOUT_SECONDS`" in task:
            if not tool_results:
                return ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "src/settings.py"})])
            last = tool_results[-1]
            if "Wrote src/settings.py" in last:
                return ProviderTurn(tool_calls=[ToolCall("run_command", {"command": TEST_COMMAND})])
            if "exit code: 0" in last:
                return ProviderTurn(content="Updated the setting and the unit test passed.")
            return ProviderTurn(tool_calls=[ToolCall("write_file", {
                "path": "src/settings.py", "content": "TIMEOUT_SECONDS = 20\n",
            })])
        return ProviderTurn(content="unknown")

    def tool_result_message(self, call_id, name, content):
        return {"role": "tool", "content": content}

    def native_effort_kwargs(self, level):
        return None


class EmptySampler:
    def mark(self):
        return 0

    def window(self, start, end):
        return []


class TestQwenThinkingEffortStudy(unittest.TestCase):
    def test_preflight_selects_tag_matching_the_ollama_show_runner(self):
        installed = [
            {"name": "qwen3.5:9b", "digest": "ggml-id", "details": {"runner": "ggml"}},
            {"name": "qwen3.5:9b", "digest": "llama-id", "details": {"runner": "llamacpp"}},
        ]
        selected, reason = _select_model_tag(installed, {"details": {"runner": "llamacpp"}})
        self.assertEqual(selected["digest"], "llama-id")
        self.assertIn("llamacpp", reason)

    def test_standard_matrix_is_90_paired_trials(self):
        matrix = build_matrix(DEFAULT_REPETITIONS)
        self.assertEqual(len(matrix), 90)
        self.assertEqual(len({(row["scenario"], row["thinking"], row["effort"], row["repetition"]) for row in matrix}), 90)
        self.assertEqual(sum(row["plan_mode"] for row in matrix), 18)
        self.assertTrue(all(not row["ultrathink"] for row in matrix))

    def test_fixture_edit_and_approved_test_are_scoped_and_pass(self):
        row = {
            "scenario": "edit_test", "thinking": False, "effort": "low",
            "repetition": 1, "plan_mode": False, "ultrathink": False,
        }
        result = run_trial(row, "unused", "fake", EmptySampler(), provider_factory=FakeProvider)
        self.assertTrue(result["evaluation"]["passed"])
        self.assertTrue(result["expected_edit_applied"])
        self.assertTrue(any(item["approved"] and item["command"] == TEST_COMMAND for item in result["approvals"]))

    def test_plan_and_denied_write_do_not_change_fixture(self):
        plan = {
            "scenario": "plan_change", "thinking": True, "effort": "medium",
            "repetition": 1, "plan_mode": True, "ultrathink": False,
        }
        denied = {
            "scenario": "denied_write", "thinking": False, "effort": "high",
            "repetition": 1, "plan_mode": False, "ultrathink": False,
        }
        plan_result = run_trial(plan, "unused", "fake", EmptySampler(), provider_factory=FakeProvider)
        denied_result = run_trial(denied, "unused", "fake", EmptySampler(), provider_factory=FakeProvider)
        self.assertTrue(plan_result["evaluation"]["passed"])
        self.assertTrue(denied_result["evaluation"]["passed"])
        self.assertTrue(plan_result["fixture_unchanged"])
        self.assertTrue(denied_result["fixture_unchanged"])

    def test_quantiles_report_median_and_p95(self):
        values = _quantiles([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(values["median"], 3.0)
        self.assertEqual(values["p95"], 4.8)

    def test_edit_grade_uses_python_value_not_trailing_newline(self):
        self.assertTrue(_timeout_is_twenty("TIMEOUT_SECONDS = 20"))
        self.assertTrue(_timeout_is_twenty("TIMEOUT_SECONDS: int = 20\n"))
        self.assertFalse(_timeout_is_twenty("TIMEOUT_SECONDS = 10\n"))

    def test_host_sampler_handles_available_sysfs_and_proc_metrics(self):
        sample = HostSampler().sample()
        self.assertIn("mem_available_bytes", sample)
        self.assertIn("gpu_vram_used_bytes", sample)
        self.assertIn("ollama_runner_rss_bytes", sample)

    def test_summary_requires_all_90_rows_and_reports_safety_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            matrix = build_matrix()
            metadata = {
                "run_id": "fixture-run", "model": "fixture", "model_digest": "digest",
                "ollama_version": "test", "started_at_utc": "2026-10-12T00:00:00+00:00",
                "repetitions": 3, "generation_options": {}, "preflight": {}, "warmup": {},
                "qwen_agent_diagnostic": {"status": "complete"},
            }
            (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            traces = []
            for row in matrix:
                passed = not (row["scenario"] == "plan_change" and row["thinking"] and row["effort"] == "high")
                safety_check = "no_write_or_command_attempt" if row["scenario"] == "plan_change" else "write_was_denied"
                traces.append({
                    **row,
                    "calls": [],
                    "trial_wall_seconds": 1.0,
                    "effective_budgets": {"max_output_tokens": 512, "max_tool_rounds": 3, "num_ctx": 6144},
                    "host_metrics": {
                        "peak_ollama_runner_rss_bytes": None,
                        "peak_gpu_vram_used_bytes": None,
                        "mean_gpu_busy_percent": None,
                    },
                    "evaluation": {"checks": {safety_check: passed}, "passed": passed},
                })
            (run_dir / "traces.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in traces), encoding="utf-8"
            )
            (run_dir / "host-metrics.jsonl").write_text("", encoding="utf-8")
            aggregate = root / "aggregate.json"
            result = summarize_run(run_dir, aggregate)
            self.assertEqual(result["trial_count"], 90)
            self.assertEqual(len(result["groups"]), 30)
            self.assertIn("final_response_nonempty_rate", result["groups"][0])
            self.assertIn("tool_calls_per_trial", result["groups"][0])
            self.assertIn("thinking_present_call_rate", result["groups"][0])
            self.assertEqual(len(result["overall_by_thinking"]), 2)
            self.assertEqual(result["overall_by_thinking"][0]["trials"], 45)
            self.assertEqual(result["host_resource_peak"]["measurement_scope"], "matrix trials only; excludes warmup and Qwen-Agent diagnostic runs")
            self.assertEqual(result["host_resource_peak"]["trial_count"], 90)
            self.assertFalse(result["safety_pass"])

    def test_summary_rejects_incomplete_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text(json.dumps({"repetitions": 3}), encoding="utf-8")
            (run_dir / "traces.jsonl").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Incomplete run"):
                summarize_run(run_dir, root / "aggregate.json")


if __name__ == "__main__":
    unittest.main()
