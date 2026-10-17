import tempfile
import unittest
from pathlib import Path

from scripts.bench_hard_cases import hard_case_specs


class TestHardBenchVerifiers(unittest.TestCase):
    def run_case(self, spec, solve):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec["prepare"](root)
            if solve:
                solve(root)
            return spec["verify"]({"root": root, "answer": "", "approvals": 0})

    def test_every_case_has_two_prompts_and_a_reference_unless_read_only(self):
        for spec in hard_case_specs():
            self.assertEqual(len(spec["prompts"]), 2, spec["id"])
            self.assertTrue(spec["reference"] or spec["id"] == "h_cross_file_question", spec["id"])

    def test_the_untouched_start_state_fails_every_case(self):
        for spec in hard_case_specs():
            if spec["id"] == "h_cross_file_question":
                continue
            self.assertFalse(self.run_case(spec, None), spec["id"])

    def test_the_reference_solution_passes_every_case(self):
        for spec in hard_case_specs():
            if spec["reference"]:
                self.assertTrue(self.run_case(spec, spec["reference"]), spec["id"])

    def test_the_question_verifier_accepts_a_correct_answer_and_rejects_a_wrong_one(self):
        spec = next(s for s in hard_case_specs() if s["id"] == "h_cross_file_question")
        ok = "A taxa é 0.0, definida em regions.py no dicionário TAX_BY_REGION (região export)."
        wrong = "É 0.19, em pricing.py."
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(spec["verify"]({"root": Path(tmp), "answer": ok}))
            self.assertFalse(spec["verify"]({"root": Path(tmp), "answer": wrong}))

    def test_editing_a_test_to_cheat_is_rejected(self):
        spec = next(s for s in hard_case_specs() if s["id"] == "h_root_cause_dependency")

        def cheat(root):
            (root / "tests/test_report.py").write_text("import unittest\n", encoding="utf-8")
            (root / "tests/test_cart.py").write_text("import unittest\n", encoding="utf-8")

        self.assertFalse(self.run_case(spec, cheat))


if __name__ == "__main__":
    unittest.main()
