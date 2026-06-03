import unittest
from types import SimpleNamespace

from zerocoding.core.agent import Agent


class DummyProvider:
    def chat(self, messages, **kwargs):
        return "ok"


class TestAgentSkills(unittest.TestCase):
    def test_add_remove_multiple_skills(self):
        skills = [
            SimpleNamespace(name="spring", description="", content="spring rules"),
            SimpleNamespace(name="python", description="", content="python rules"),
        ]
        agent = Agent(provider=DummyProvider(), skills=skills)

        self.assertTrue(agent.add_skill("spring"))
        self.assertTrue(agent.add_skill("python"))
        self.assertEqual(agent.active_skill_names(), ["spring", "python"])

        self.assertTrue(agent.remove_skill("spring"))
        self.assertEqual(agent.active_skill_names(), ["python"])

        agent.clear_skills()
        self.assertEqual(agent.active_skill_names(), [])


if __name__ == "__main__":
    unittest.main()
