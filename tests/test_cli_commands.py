"""Characterization tests for the interactive slash-command handlers in cli.py."""
import os
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

from zerocoding.commands import handle_command, refresh_tui_state, save_session_state
from zerocoding.core.agent import Agent
from zerocoding.core.config import ConfigManager
from zerocoding.core.external import ExternalTool
from zerocoding.core.project_context import ProjectContext
from zerocoding.core.sessions import Session, SessionManager
from zerocoding.core.tools import ToolRegistry
from zerocoding.cli import main


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
        self.confirm_result = False
        self.confirmations = []

    def _log(self, kind, text):
        self.messages.append((kind, str(text)))

    def show_info(self, text): self._log("info", text)
    def show_success(self, text): self._log("success", text)
    def show_error(self, text): self._log("error", text)
    def show_warning(self, text): self._log("warning", text)
    def show_help(self): self._log("help", "")
    def play_buddy(self, name=None): return name or "dance"
    def show_status(self): self._log("status", "")
    def show_skills(self, skills): self._log("skills", ",".join(s.name for s in skills))
    def clear(self): self._log("clear", "")
    def render_tool_call(self, name, target=""): self._log("tool", f"{name} {target}")
    def render_tool_done(self, *args): self._log("tool_done", args)
    def set_runtime_state(self, **kwargs): self.runtime = kwargs
    def confirm_action(self, action, preview):
        self.confirmations.append((action, preview))
        return self.confirm_result

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

    def test_cli_help_exposes_ephemeral_session_override(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as result:
                main(["--no-session-save", "--help"])

        self.assertEqual(result.exception.code, 0)
        self.assertIn("--no-session-save", output.getvalue())

    def test_cli_reports_session_storage_startup_errors_without_traceback(self):
        class BrokenSessionManager:
            persist = True
            root = Path("/private/session/path")

            def save(self, session):
                raise NotADirectoryError(f"Session path is not a directory: {self.root}")

        stderr = io.StringIO()
        with (
            patch("zerocoding.cli.load_env"),
            patch("zerocoding.cli.ConfigManager", return_value=self.manager),
            patch.object(self.manager, "load", return_value=self.config),
            patch("zerocoding.cli.build_provider", return_value=DummyProvider()),
            patch("zerocoding.cli.SessionManager", return_value=BrokenSessionManager()),
            patch("zerocoding.cli.load_skills", return_value=[]),
            contextlib.redirect_stderr(stderr),
        ):
            result = main([])

        self.assertEqual(result, 1)
        self.assertIn("Could not create a private session", stderr.getvalue())
        self.assertIn("/private/session/path", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_ephemeral_session_state_commands_work_without_writing_files(self):
        root = Path(self.tmp.name) / "ephemeral-sessions"
        ephemeral_manager = SessionManager(root, persist=False)
        ephemeral_session = ephemeral_manager.create(
            self.config.provider, self.config.model, self.config.mode, str(self.workspace)
        )
        self.agent.context.add_message("user", "keep in memory")

        save_session_state(
            ephemeral_manager, ephemeral_session, self.config, self.agent, self.project_context,
        )
        handle_command(
            "/sessions", self.tui, self.agent, self.config, self.manager, self.skills,
            self.project_context, ephemeral_manager, ephemeral_session,
        )

        self.assertFalse(root.exists())
        self.assertIn("persistence is disabled", self.tui.text())
        self.assertEqual(self.agent.context.history[0]["content"], "keep in memory")

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

    def test_buddy_command_plays_an_animation(self):
        self.run_command("/buddy sleep")
        self.assertIn("sleep", self.tui.text())

    def test_provider_add_rejects_unknown_type_and_keeps_config(self):
        before = dict(self.config.providers)
        _, provider = self.run_command("/provider add ollama local http://127.0.0.1:11434/v1 qwen3.5:4b")
        self.assertIsNone(provider)
        self.assertEqual(self.tui.messages[-1][0], "error")
        self.assertIn("openai_compatible", self.tui.messages[-1][1])
        self.assertEqual(self.config.providers, before)

    def test_provider_add_warns_when_the_model_is_not_served(self):
        with patch("zerocoding.providers.openai_compatible.OpenAICompatibleProvider.list_models",
                   return_value=["qwen3.5:4b"]):
            self.run_command("/provider add tiny openai_compatible http://127.0.0.1:11434/v1 qwen:3.5:4b")
        self.assertIn("warning", self.tui.kinds())
        self.assertIn("qwen3.5:4b", self.tui.text())

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

    def test_new_and_resume_preserve_registered_extension_tools(self):
        extension = ExternalTool(
            name="mcp__demo__echo",
            server="demo",
            tool="echo",
            spec={"type": "function", "function": {"name": "mcp__demo__echo", "parameters": {"type": "object"}}},
            read_only=True,
            handler=lambda args: f"echo:{args.get('value', '')}",
        )
        self.agent.tools.register_external(extension)
        self.agent.context.add_message("user", "existing session")
        save_session_state(self.session_manager, self.session, self.config, self.agent, self.project_context)
        saved_id = self.session.id

        self.run_command("/new")
        self.assertIn("mcp__demo__echo", [schema["function"]["name"] for schema in self.agent.tools.schemas])
        self.assertEqual(self.agent.tools.execute("mcp__demo__echo", {"value": "new"}), "echo:new")

        self.run_command(f"/resume {saved_id}")
        self.assertIn("mcp__demo__echo", [schema["function"]["name"] for schema in self.agent.tools.schemas])
        self.assertEqual(self.agent.tools.execute("mcp__demo__echo", {"value": "resumed"}), "echo:resumed")

    def test_new_session_does_not_inherit_previous_history(self):
        self.agent.context.add_message("user", "secret from session one")
        first_id = self.session.id
        self.run_command("/new")
        self.assertNotEqual(self.session.id, first_id)
        self.assertEqual(self.agent.context.history, [])
        self.assertEqual(self.session_manager.load(self.session.id).history, [])

    def test_resume_unknown_id_preserves_current_session_and_history(self):
        first_id = self.session.id
        self.agent.context.add_message("user", "keep this turn")
        self.run_command("/resume deadbeef")
        self.assertIn("error", self.tui.kinds())
        self.assertEqual(self.session.id, first_id)
        self.assertEqual(self.agent.context.history, [{"role": "user", "content": "keep this turn"}])

    def test_resume_ambiguous_prefix_preserves_current_session(self):
        first = Session(id="deadbeef" + "0" * 24, provider="local", model="first")
        second = Session(id="deadbeef" + "1" * 24, provider="local", model="second")
        self.session_manager.save(first)
        self.session_manager.save(second)
        current_id = self.session.id

        self.run_command("/resume deadbeef")

        self.assertEqual(self.session.id, current_id)
        self.assertTrue(any("ambiguous" in message.lower() for message in self.tui.text().splitlines()))

    def test_resume_malformed_session_preserves_current_session_and_history(self):
        current_id = self.session.id
        self.agent.context.add_message("user", "current history")
        malformed = self.session_manager.root / "deadbeef.json"
        malformed.write_text('{"id":"deadbeef","skills":"not-a-list"}', encoding="utf-8")

        self.run_command("/resume deadbeef")

        self.assertEqual(self.session.id, current_id)
        self.assertEqual(self.agent.context.history, [{"role": "user", "content": "current history"}])
        self.assertIn("skills", self.tui.text())

    def test_resume_provider_setup_failure_preserves_all_current_state(self):
        saved = self.session_manager.create("local", "saved-model", path="/saved-workspace")
        saved.history = [{"role": "assistant", "content": "saved history"}]
        self.session_manager.save(saved)
        self.agent.context.add_message("user", "current history")
        self.agent.add_skill("python")
        self.agent.set_session_controls(plan_mode=True, effort="high")
        self.project_context.add("hello.py")
        current_id = self.session.id
        original_tools = self.agent.tools
        original_context = dict(self.project_context.files)

        with patch("zerocoding.commands.build_session_provider", side_effect=RuntimeError("provider setup failed")):
            self.run_command(f"/resume {saved.id}")

        self.assertEqual(self.session.id, current_id)
        self.assertEqual(self.agent.context.history, [{"role": "user", "content": "current history"}])
        self.assertEqual(self.agent.active_skill_names(), ["python"])
        self.assertTrue(self.agent.plan_mode)
        self.assertEqual(self.agent.effort, "high")
        self.assertIs(self.agent.tools, original_tools)
        self.assertEqual(self.project_context.files, original_context)
        self.assertIn("provider setup failed", self.tui.text())

    def test_new_session_storage_failure_preserves_current_state(self):
        self.agent.context.add_message("user", "current history")
        self.agent.add_skill("python")
        self.agent.set_session_controls(plan_mode=True, effort="high")
        self.project_context.add("hello.py")
        current_id = self.session.id
        original_tools = self.agent.tools
        original_context = dict(self.project_context.files)

        with patch.object(self.session_manager, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.run_command("/new")

        self.assertEqual(self.session.id, current_id)
        self.assertEqual(self.agent.context.history, [{"role": "user", "content": "current history"}])
        self.assertEqual(self.agent.active_skill_names(), ["python"])
        self.assertTrue(self.agent.plan_mode)
        self.assertEqual(self.agent.effort, "high")
        self.assertIs(self.agent.tools, original_tools)
        self.assertEqual(self.project_context.files, original_context)

    def test_new_after_resume_targets_current_workspace_for_tools(self):
        self.agent.tools = self.agent.tools.clone_for("/previous-workspace")

        self.run_command("/new")

        self.assertEqual(self.agent.tools.root, self.workspace.resolve())

    def test_sessions_delete_requires_confirmation_and_cannot_delete_active_session(self):
        saved = self.session_manager.create("local", "old-model", path="/old-project")

        self.run_command(f"/sessions delete {saved.id}")
        self.assertTrue((self.session_manager.root / f"{saved.id}.json").exists())
        self.assertEqual(self.tui.confirmations[-1][0], "Delete session")

        self.tui.confirm_result = True
        self.run_command(f"/sessions delete {self.session.id}")
        self.assertTrue((self.session_manager.root / f"{self.session.id}.json").exists())
        self.assertEqual(len(self.tui.confirmations), 1)

        self.run_command(f"/sessions delete {saved.id}")
        self.assertFalse((self.session_manager.root / f"{saved.id}.json").exists())

    def test_sessions_delete_without_confirmation_capability_does_not_delete(self):
        saved = self.session_manager.create("local", "old-model")
        self.tui.confirm_action = None

        self.run_command(f"/sessions delete {saved.id}")

        self.assertTrue((self.session_manager.root / f"{saved.id}.json").exists())
        self.assertIn("requires an interactive confirmation", self.tui.text())

    def test_sessions_clear_removes_only_inactive_session_json_files(self):
        first = self.session_manager.create("local", "first")
        second = self.session_manager.create("local", "second")
        unrelated = self.session_manager.root / "notes.json"
        unrelated.write_text("keep", encoding="utf-8")
        self.tui.confirm_result = True

        self.run_command("/sessions clear")

        self.assertTrue((self.session_manager.root / f"{self.session.id}.json").exists())
        self.assertFalse((self.session_manager.root / f"{first.id}.json").exists())
        self.assertFalse((self.session_manager.root / f"{second.id}.json").exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_sessions_list_shows_metadata_without_printing_history_content(self):
        self.agent.context.add_message("user", "private workspace question")
        save_session_state(self.session_manager, self.session, self.config, self.agent, self.project_context)

        self.run_command("/sessions")

        self.assertIn(self.session.id, self.tui.text())
        self.assertIn("messages", self.tui.text())
        self.assertNotIn("private workspace question", self.tui.text())

    def test_sessions_list_warns_when_invalid_session_files_are_ignored(self):
        invalid_id = "deadbeef"
        invalid_path = self.session_manager.root / f"{invalid_id}.json"
        invalid_path.write_text('{"private":"conversation content",', encoding="utf-8")

        self.run_command("/sessions")

        self.assertIn(invalid_id, self.tui.text())
        self.assertIn("Ignored 1 unreadable session file", self.tui.text())
        self.assertNotIn("conversation content", self.tui.text())

    def test_resume_without_id_reports_usage(self):
        current_id = self.session.id
        self.agent.context.add_message("user", "keep this turn")
        self.run_command("/resume")
        self.assertEqual(self.tui.messages[0][0], "error")
        self.assertIn("Usage", self.tui.messages[0][1])
        self.assertEqual(self.session.id, current_id)
        self.assertEqual(self.agent.context.history, [{"role": "user", "content": "keep this turn"}])

    def test_sessions_and_session_listing(self):
        self.run_command("/sessions")
        self.assertIn(self.session.id, self.tui.text())
        self.run_command("/session")
        self.assertIn(f"Session: {self.session.id}", self.tui.text())


if __name__ == "__main__":
    unittest.main()
