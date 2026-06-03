import tempfile
import unittest
from pathlib import Path

from zerocoding.core.project_context import ProjectContext


class TestProjectContext(unittest.TestCase):
    def test_add_clear_and_prompt_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "main.py"
            path.write_text("print('hello')\n", encoding="utf-8")

            context = ProjectContext(root)
            item = context.add("main.py")

            self.assertEqual(item.path, "main.py")
            self.assertEqual(context.tree(), ["main.py"])
            self.assertIn("print('hello')", context.build_prompt("Explique"))

            context.clear()
            self.assertEqual(context.tree(), [])

    def test_grep_ignores_configured_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("needle\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "ignored").write_text("needle\n", encoding="utf-8")

            context = ProjectContext(root)
            results = context.grep("needle")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][0], "src/app.py")


if __name__ == "__main__":
    unittest.main()
