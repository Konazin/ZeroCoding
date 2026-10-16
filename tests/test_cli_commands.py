"""Characterization tests for the interactive slash-command handlers in cli.py."""
import os
import tempfile
import unittest
from pathlib import Path

from zerocoding.commands import handle_command, refresh_tui_state, save_session_state
from zerocoding.core.agent import Agent
from zerocoding.core.config import ConfigManager
from zerocoding.core.project_context import ProjectContext
from zerocoding.core.sessions import SessionManager
from zerocoding.core.tools import ToolRegistry


class FakeTUI:
    """Records output instead of rendering; mirrors the attributes the handlers set."""

    def __init__(self):
        self.messages = []
        self.provider_name = self.model = self.mode = self.session_id = ""
        self.skills = []
        self.plan_mode = self.ultrathink = False
        self.effort = "medium"
        self.connection_status = "unknown"
        self.runtime = {}

    def _log(self, kind, text):
        self.messages.append((kind, str(text)))

    def show_info(self, text): self._log("info", text)
    def show_success(self, text): self._log("success", text)
    def show_error(self, text): self._log("error", text)
    def show_warning(self, text): self._log("warning", text)
    def show_help(self): self._log("help", "")
    def show_status(self): self._log("status", "")
    def show_skills(self, skills): self._log("skills", ",".join(s.name for s in skills))
    def clear(self): self._log("clear", "")
    def render_tool_call(self, name, target=""): self._log("tool", f"{name} {target}")
    def render_tool_done(self, *args): self._log("tool_done", args)
    def set_runtime_state(self, **kwargs): self.runtime = kwargs

    def kinds(self):
        return [kind for kind, _ in self.messages]

    def text(self):
        return "\n".join(text for _, text in self.messages)


class Skill:
    def __init__(self, name, description="", content=""):
        self.name, self.description, self.content = name, description, content


class DummyProvider:
    def __init__(self, healthy=True):
        self.healthy = healthy

    def chat(self, messages, **kwargs):
        return "ok"

    def healthcheck(self):
        return self.healthy

    def list_models(self):
        return ["alpha", "beta"]


class CliCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "hello.py").write_text("print('hello')\n", encoding="utf-8")
        previous = os.getcwd()
        os.chdir(self.workspace)
        self.addCleanup(os.chdir, previous)

        self.manager = ConfigManager(user_config_path=root / "config.yaml", env_file=str(root / "missing.env"))
        self.config = self.manager.load()
        self.skills = [Skill("python", "Python style", "Use hints."), Skill("spring", "Spring Boot")]
        self.agent = Agent(DummyProvider(), skills=self.skills)
        self.agent.tools = ToolRegistry(self.workspace)
        self.project_context = ProjectContext(self.workspace)
        self.session_manager = SessionManager(root / "sessions")
        self.session = self.session_manager.create(
            self.config.provider, self.config.model, self.config.mode, str(self.workspace)
        )
        self.tui = FakeTUI()
        refresh_tui_state(self.tui, self.config, self.agent, session=self.session)

    def run_command(self, command):
        should_exit, provider, session = handle_command(
            command, self.tui, self.agent, self.config, self.manager, self.skills,
            self.project_context, self.session_manager, self.session,
        )
        self.session = session
        return should_exit, provider

    # --- basic flow -------------------------------------------------
    def test_exit_aliases(self):
        for command in ("/exit", "/quit", "/q"):
            self.assertTrue(self.run_command(command)[0])

    def test_unknown_command_reports_error_and_continues(self):
        should_exit, provider = self.run_command("/nope")
        self.assertFalse(should_exit)
        self.assertIsNone(provider)
        self.assertEqual(self.tui.kinds(), ["error"])
        self.assertIn("/nope", self.tui.text())

    def test_help_status_clear_dispatch(self):
        for command, kind in (("/help", "help"), ("/status", "status"), ("/clear", "clear")):
            self.run_command(command)
            self.assertEqual(self.tui.messages[-1][0], kind)

    # --- plan / ultrathink / effort ---------------------------------
    def test_plan_toggle_on_off_and_session_persistence(self):
        self.run_command("/plan")
        self.assertTrue(self.agent.plan_mode)
        self.assertTrue(self.session.plan_mode)
        self.assertTrue(self.tui.plan_mode)
        self.assertTrue(self.session_manager.load(self.session.id).plan_mode)
        self.run_command("/plan off")
        self.assertFalse(self.agent.plan_mode)
        self.run_command("/plan on")
        self.assertTrue(self.agent.plan_mode)

    def test_plan_rejects_bad_argument_without_changing_state(self):
        self.run_command("/plan maybe")
        self.assertFalse(self.agent.plan_mode)
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.run_command("/plan on off")
        self.assertFalse(self.agent.plan_mode)

    def test_ultrathink_toggle(self):
        self.run_command("/ultrathink on")
        self.assertTrue(self.agent.ultrathink)
        self.assertTrue(self.session.ultrathink)
        self.assertEqual(self.tui.runtime["max_output_tokens"], self.agent.effective_budgets()[0])

    def test_effort_set_show_and_reject(self):
        self.run_command("/effort")
        self.assertIn("Medium", self.tui.text())
        self.run_command("/effort high")
        self.assertEqual(self.agent.effort, "high")
        self.assertEqual(self.session.effort, "high")
        self.run_command("/effort extreme")
        self.assertEqual(self.agent.effort, "high")
        self.assertEqual(self.tui.messages[-1][0], "error")

    # --- skills -----------------------------------------------------
    def test_skill_add_remove_clear_and_missing(self):
        self.run_command("/skill add python")
        self.assertEqual(self.agent.active_skill_names(), ["python"])
        self.assertEqual(self.session_manager.load(self.session.id).skills, ["python"])
        self.run_command("/skill add ghost")
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.run_command("/skill remove python")
        self.assertEqual(self.agent.active_skill_names(), [])
        self.run_command("/skill remove python")
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.run_command("/skill add spring")
        self.run_command("/skill clear")
        self.assertEqual(self.agent.active_skill_names(), [])

    # --- mode / model / provider ------------------------------------
    def test_mode_switch_sets_effort_and_session_values(self):
        _, provider = self.run_command("/mode fast")
        self.assertIsNotNone(provider)
        self.assertEqual(self.session.mode, "fast")
        self.assertEqual(self.agent.effort, "low")
        self.assertEqual(self.session.effort, "low")
        self.run_command("/mode reason")
        self.assertEqual(self.agent.effort, "high")
        self.run_command("/mode code")
        self.assertEqual(self.agent.effort, "medium")

    def test_mode_unknown_leaves_session_untouched(self):
        _, provider = self.run_command("/mode ghost")
        self.assertIsNone(provider)
        self.assertEqual(self.session.mode, "code")
        self.assertEqual(self.tui.messages[-1][0], "error")

    def test_mode_does_not_overwrite_saved_defaults(self):
        self.run_command("/mode fast")
        self.assertEqual(self.config.mode, "code")
        self.assertFalse(self.manager.user_config_path.exists())

    def test_model_use_changes_session_only(self):
        default_model = self.config.model
        _, provider = self.run_command("/model use custom-model")
        self.assertIsNotNone(provider)
        self.assertEqual(self.session.model, "custom-model")
        self.assertEqual(self.config.model, default_model)
        self.assertEqual(provider.model, "custom-model")

    def test_model_use_without_name_is_an_error(self):
        _, provider = self.run_command("/model use")
        self.assertIsNone(provider)
        self.assertEqual(self.tui.messages[-1][0], "error")

    def test_model_list_uses_provider(self):
        self.run_command("/model list")
        self.assertIn("alpha", self.tui.text())
        self.assertIn("beta", self.tui.text())

    def test_provider_test_updates_connection_status(self):
        self.run_command("/provider test")
        self.assertEqual(self.tui.connection_status, "connected")
        self.agent.provider = DummyProvider(healthy=False)
        self.run_command("/provider test")
        self.assertEqual(self.tui.connection_status, "offline")
        self.assertEqual(self.tui.messages[-1][0], "error")

    def test_provider_unknown_and_remove_active_are_rejected(self):
        self.run_command("/provider use ghost")
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.run_command(f"/provider remove {self.config.provider}")
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.assertIn(self.config.provider, self.config.providers)

    def test_provider_add_saves_and_switches(self):
        _, provider = self.run_command("/provider add local llama_cpp http://127.0.0.1:9999/v1 my-model")
        self.assertIsNotNone(provider)
        self.assertEqual(self.config.provider, "local")
        self.assertEqual(self.session.provider, "local")
        self.assertEqual(self.session.model, "my-model")
        self.assertTrue(self.manager.user_config_path.exists())

    # --- context ----------------------------------------------------
    def test_context_add_tree_remove_clear(self):
        self.run_command("/context add hello.py")
        self.assertEqual(self.project_context.tree(), ["hello.py"])
        self.assertEqual(self.session_manager.load(self.session.id).context_files[0]["path"], "hello.py")
        self.run_command("/context remove hello.py")
        self.assertEqual(self.project_context.tree(), [])
        self.run_command("/context remove hello.py")
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.run_command("/context add hello.py")
        self.run_command("/context clear")
        self.assertEqual(self.project_context.tree(), [])

    def test_context_add_blocks_paths_outside_workspace(self):
        self.run_command("/context add ../outside.txt")
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.assertEqual(self.project_context.tree(), [])

    def test_read_adds_file_to_context_and_prints_it(self):
        self.run_command("/read hello.py")
        self.assertIn("print('hello')", self.tui.text())
        self.assertEqual(self.project_context.tree(), ["hello.py"])

    def test_tree_and_grep(self):
        self.run_command("/tree")
        self.assertIn("hello.py", self.tui.text())
        self.run_command("/grep hello")
        self.assertIn("hello.py:1", self.tui.text())
        self.run_command("/grep")
        self.assertEqual(self.tui.messages[-1][0], "error")

    # --- sessions ---------------------------------------------------
    def test_resume_restores_controls_history_skills_and_context(self):
        self.run_command("/plan on")
        self.run_command("/effort high")
        self.run_command("/skill add python")
        self.run_command("/context add hello.py")
        self.agent.context.add_message("user", "question")
        self.agent.context.add_message("assistant", "answer")
        save_session_state(self.session_manager, self.session, self.config, self.agent, self.project_context)
        saved_id = self.session.id

        self.run_command("/new")
        self.assertNotEqual(self.session.id, saved_id)
        self.assertFalse(self.agent.plan_mode)
        self.assertEqual(self.agent.effort, "medium")
        self.assertEqual(self.agent.context.history, [])
        self.assertEqual(self.project_context.tree(), [])

        self.run_command(f"/resume {saved_id}")
        self.assertEqual(self.session.id, saved_id)
        self.assertTrue(self.agent.plan_mode)
        self.assertEqual(self.agent.effort, "high")
        self.assertEqual(self.agent.active_skill_names(), ["python"])
        self.assertEqual([m["content"] for m in self.agent.context.history], ["question", "answer"])
        self.assertEqual(self.project_context.tree(), ["hello.py"])

    def test_new_session_does_not_inherit_previous_history(self):
        self.agent.context.add_message("user", "secret from session one")
        first_id = self.session.id
        self.run_command("/new")
        self.assertNotEqual(self.session.id, first_id)
        self.assertEqual(self.agent.context.history, [])
        self.assertEqual(self.session_manager.load(self.session.id).history, [])

    def test_resume_unknown_id_starts_new_session_with_error(self):
        first_id = self.session.id
        self.run_command("/resume deadbeef")
        self.assertIn("error", self.tui.kinds())
        self.assertNotEqual(self.session.id, first_id)

    def test_resume_without_id_reports_usage(self):
        self.run_command("/resume")
        self.assertEqual(self.tui.messages[0][0], "error")
        self.assertIn("Usage", self.tui.messages[0][1])

    def test_sessions_and_session_listing(self):
        self.run_command("/sessions")
        self.assertIn(self.session.id, self.tui.text())
        self.run_command("/session")
        self.assertIn(f"Session: {self.session.id}", self.tui.text())


if __name__ == "__main__":
    unittest.main()
