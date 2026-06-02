import unittest

from zerocoding.skills.loader import load_skills


class TestSkillLoader(unittest.TestCase):
    def test_load_skills(self):
        skills = load_skills('skills')
        self.assertIsInstance(skills, list)
        self.assertTrue(all(hasattr(skill, 'name') for skill in skills))


if __name__ == '__main__':
    unittest.main()
