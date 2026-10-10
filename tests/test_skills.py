import unittest
import tempfile
from pathlib import Path

from zerocoding.skills.loader import load_skills


class TestSkillLoader(unittest.TestCase):
    def test_load_skills(self):
        skills = load_skills('skills')
        self.assertIsInstance(skills, list)
        self.assertTrue(all(hasattr(skill, 'name') for skill in skills))

    def test_folder_skill_is_loaded_lazily_and_project_overrides_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = root / "configured"
            project = root / ".zerocoding" / "skills" / "demo"
            user = root / "user" / "demo"
            for folder, content in ((configured / "demo", "pack"), (user, "user"), (project, "project")):
                folder.mkdir(parents=True)
                (folder / "SKILL.md").write_text(f"---\nname: demo\ndescription: demo skill\n---\n{content}", encoding="utf-8")
            skills = load_skills(configured, project_path=root)
            demo = next(skill for skill in skills if skill.name == "demo")
            self.assertEqual(demo._content, "")
            self.assertIn("project", demo.content)


if __name__ == '__main__':
    unittest.main()
