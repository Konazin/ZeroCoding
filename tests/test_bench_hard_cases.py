import tempfile
import unittest
from pathlib import Path

from scripts.bench_hard_cases import hard_case_specs

READ_ONLY_CASES = {"h_cross_file_question", "h_git_status_question", "h_git_find_change"}


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
            self.assertTrue(spec["reference"] or spec["id"] in READ_ONLY_CASES, spec["id"])

    def test_the_untouched_start_state_fails_every_case(self):
        for spec in hard_case_specs():
            if spec["id"] in READ_ONLY_CASES:
                continue  # answered in prose; checked by the verifier tests below
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


class TestGitCaseVerifiers(unittest.TestCase):
    def check(self, case_id, answer):
        spec = next(s for s in hard_case_specs() if s["id"] == case_id)
        with tempfile.TemporaryDirectory() as tmp:
            spec["prepare"](Path(tmp))
            return spec["verify"]({"root": Path(tmp), "answer": answer})

    def test_status_question_needs_all_three_pending_files_and_no_clean_ones(self):
        self.assertTrue(self.check("h_git_status_question", "Pendentes: util.py (modificado), config.ini (stage) e todo.txt (novo)."))
        self.assertFalse(self.check("h_git_status_question", "Só util.py e config.ini."))
        self.assertFalse(self.check("h_git_status_question", "util.py, config.ini, todo.txt, notes.md e app.py."))

    def test_history_question_needs_the_retry_commit_and_not_a_decoy(self):
        self.assertTrue(self.check("h_git_find_change", "Foi o commit 'add retry loop to fetch', em net.py."))
        self.assertFalse(self.check("h_git_find_change", "Foi 'tweak cli banner'."))

    def test_commit_case_rejects_committing_everything_or_nothing(self):
        spec = next(s for s in hard_case_specs() if s["id"] == "h_git_commit_one_file")

        def everything(root):
            from scripts.bench_hard_cases import _git
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "commit everything now")

        with tempfile.TemporaryDirectory() as tmp:
            spec["prepare"](Path(tmp))
            self.assertFalse(spec["verify"]({"root": Path(tmp), "answer": ""}))  # nothing committed
        self.assertFalse(self.run_case_with(spec, everything))

    def run_case_with(self, spec, solve):
        with tempfile.TemporaryDirectory() as tmp:
            spec["prepare"](Path(tmp))
            solve(Path(tmp))
            return spec["verify"]({"root": Path(tmp), "answer": ""})
