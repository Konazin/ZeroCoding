import tempfile
import unittest

from zerocoding.core.sessions import SessionManager


class TestSessionManager(unittest.TestCase):
    def test_create_list_and_resume_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SessionManager(tmp)
            session = manager.create("ollama_local", "deepseek-coder-v2", "code", "/project")
            session.skills = ["spring"]
            session.history = [{"role": "user", "content": "oi"}]
            manager.save(session)

            recent = manager.list_recent()
            loaded = manager.load(session.id)

            self.assertEqual(recent[0].id, session.id)
            self.assertEqual(loaded.provider, "ollama_local")
            self.assertEqual(loaded.skills, ["spring"])
            self.assertEqual(loaded.history[0]["content"], "oi")


if __name__ == "__main__":
    unittest.main()
