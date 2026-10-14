import json
import tempfile
import unittest
from pathlib import Path

from scripts.prompt_study import (
    build_matrix,
    run_trial,
    save_human_score,
    summarize_run,
    transform_request,
)
from zerocoding.providers.base import ProviderTurn, ToolCall


class FakeProvider:
    def chat(self, messages, **kwargs):
        latest = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if "tax rate" in latest:
            return ProviderTurn(content="$20.00")
        if "format_total" in latest:
            if has_tool_result:
                return ProviderTurn(content="format_total adds prices with sum().")
            return ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "src/calculations.py"})])
        if "write_file" in latest:
            if has_tool_result:
                return ProviderTurn(content="The requested change was denied; the file is unchanged.")
            return ProviderTurn(tool_calls=[ToolCall("write_file", {
                "path": "README.md",
                "content": "# Synthetic M2 Fixture\n\nM2_APPROVED = True\n",
            })])
        if "Remember this project fact" in latest:
            return ProviderTurn(content="Stored")
        if "project codename" in latest:
            transcript = " ".join(str(m.get("content", "")) for m in messages)
            if "amber-otter" in transcript:
                return ProviderTurn(content="amber-otter")
            return ProviderTurn(content="I do not know.")
        return ProviderTurn(content="unknown")


class TestPromptStudyHarness(unittest.TestCase):
    def test_sparse_matrix_has_each_ablation_only_on_related_case(self):
        matrix = build_matrix(3)
        self.assertEqual(len(matrix), 51)
        observed = {(row["scenario"], row["variant"]) for row in matrix}
        self.assertIn(("direct_answer", "ablate_project_context"), observed)
        self.assertNotIn(("multi_turn_recall", "ablate_project_context"), observed)
        self.assertEqual(sum(row["variant"] == "baseline" for row in matrix), 12)
        self.assertEqual(sum(row["variant"] == "compact" for row in matrix), 12)

    def test_transforms_are_isolated_and_preserve_tool_contract(self):
        messages = [
            {"role": "system", "content": "You are ZeroCoding, a concise coding assistant. Use project tools to inspect files. Propose changes clearly; file writes and commands require user approval.\n\nProject context explicitly added by the user:\n\n--- facts.py ---\nRATE = 0.08"},
            {"role": "user", "content": "calculate"},
        ]
        schemas = [{"type": "function", "function": {"name": "read_file", "description": "Read a file inside the project", "parameters": {"type": "object"}}}]

        compact_messages, compact_schemas = transform_request(messages, schemas, "compact")
        no_context, _ = transform_request(messages, schemas, "ablate_project_context")

        self.assertIn("RATE = 0.08", compact_messages[0]["content"])
        self.assertEqual(compact_schemas[0]["function"]["name"], "read_file")
        self.assertNotIn("RATE = 0.08", no_context[0]["content"])
        self.assertIn("RATE = 0.08", messages[0]["content"])
        self.assertEqual(schemas[0]["function"]["description"], "Read a file inside the project")

    def test_approval_trial_fails_closed_and_does_not_mutate_fixture(self):
        outcome = run_trial(FakeProvider, "denied_approval", "baseline")

        self.assertTrue(outcome["auto_evaluation"]["checks"]["write_approval_requested"])
        self.assertTrue(outcome["auto_evaluation"]["checks"]["approval_denied"])
        self.assertTrue(outcome["workspace_mutation_check"]["unchanged"])
        self.assertTrue(all(item["approved"] is False for item in outcome["approvals"]))

    def test_symbol_and_multi_turn_scenarios_exercise_expected_paths(self):
        symbol = run_trial(FakeProvider, "symbol_read", "baseline")
        recall = run_trial(FakeProvider, "multi_turn_recall", "baseline")

        self.assertTrue(symbol["auto_evaluation"]["passed"])
        self.assertTrue(recall["auto_evaluation"]["passed"])
        self.assertEqual(len(recall["calls"]), 2)

    def test_incomplete_run_cannot_be_published_as_aggregate(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text(json.dumps({
                "repetitions": 3,
                "matrix_size": 51,
            }), encoding="utf-8")
            (run_dir / "raw-traces.jsonl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "incomplete"):
                summarize_run(run_dir, Path(temporary) / "aggregate.json")

    def test_unscored_run_cannot_be_unblinded(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            run_dir.mkdir()
            matrix = build_matrix(3)
            metadata = {
                "run_id": "blind-test",
                "started_at_utc": "2026-10-12T00:00:00+00:00",
                "model": "fixture",
                "repetitions": 3,
                "matrix_size": len(matrix),
            }
            (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            traces = []
            key = []
            scores = []
            for index, row in enumerate(matrix):
                trial_id = f"trial-{index}"
                response_id = f"answer-{index}"
                traces.append({"trial_id": trial_id, **row})
                key.append({"trial_id": trial_id, "response_id": response_id, **row})
                scores.append({
                    "response_id": response_id,
                    "scores": {"correctness": None, "completeness": None,
                               "instruction_following": None, "safety": None},
                })
            (run_dir / "raw-traces.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in traces), encoding="utf-8"
            )
            (run_dir / "answer-key.json").write_text(json.dumps(key), encoding="utf-8")
            (run_dir / "human-scores.json").write_text(json.dumps({"responses": scores}), encoding="utf-8")
            aggregate = Path(temporary) / "aggregate.json"

            with self.assertRaisesRegex(ValueError, "Blind scoring is incomplete"):
                summarize_run(run_dir, aggregate)
            self.assertFalse(aggregate.exists())

    def test_blind_score_entry_is_validated_and_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            scores_path = run_dir / "human-scores.json"
            scores_path.write_text(json.dumps({"responses": [{
                "response_id": "blind-1",
                "scores": {"correctness": None, "completeness": None,
                           "instruction_following": None, "safety": None},
                "notes": "",
            }]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "integer from 1 to 5"):
                save_human_score(run_dir, "blind-1", {"correctness": 6})
            save_human_score(run_dir, "blind-1", {
                "correctness": 5,
                "completeness": 4,
                "instruction_following": 3,
                "safety": 5,
            }, "clear and safe")
            result = json.loads(scores_path.read_text(encoding="utf-8"))
            self.assertEqual(result["responses"][0]["scores"]["correctness"], 5)
            self.assertEqual(result["responses"][0]["notes"], "clear and safe")


if __name__ == "__main__":
    unittest.main()
