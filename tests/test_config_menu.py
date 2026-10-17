import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zerocoding.config_menu import run_config_menu
from zerocoding.core.config import ConfigManager
from zerocoding.tui.menus import MenuOption, MenuState


class ScriptedUI:
    def __init__(self, selections, answers=()):
        self.selections, self.answers = list(selections), list(answers)
        self.titles, self.messages = [], []

    def select(self, title, options, current=None, extra_keys=None):
        self.titles.append(title)
        return self.selections.pop(0) if self.selections else None

    def ask(self, prompt, default=""):
        return self.answers.pop(0) if self.answers else None

    def show_success(self, text): self.messages.append(text)
    def show_error(self, text): self.messages.append(text)
    def show_info(self, text): self.messages.append(text)


class FakeProvider:
    model = "qwen3.5:4b"

    def list_models(self):
        return ["qwen3.5:4b", "llama3.2:3b"]


class FakeAgent:
    effort = "medium"
    streaming_enabled = True

    def __init__(self):
        self.provider = FakeProvider()


class TestMenuState(unittest.TestCase):
    def test_move_wraps_and_jump_is_one_based(self):
        state = MenuState("t", [MenuOption("a"), MenuOption("b"), MenuOption("c")])
        state.move(-1)
        self.assertEqual(state.index, 2)
        state.move(1)
        self.assertEqual(state.index, 0)
        self.assertTrue(state.jump(2))
        self.assertEqual(state.index, 1)
        self.assertFalse(state.jump(9))

    def test_help_line_lists_extra_keys(self):
        state = MenuState("t", [MenuOption("a")], extra_keys={"s": "this session only"})
        self.assertIn("s this session only", state.help_line())
        self.assertIn("esc cancel", state.help_line())

    def test_lines_mark_the_active_row(self):
        text = "".join(chunk for _, chunk in MenuState("Pick", [MenuOption("a"), MenuOption("b")], index=1).lines())
        self.assertIn("❯ 2. b", text)
        self.assertNotIn("❯ 1.", text)


class TestConfigMenu(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = ConfigManager(user_config_path=Path(self.directory.name) / "config.yaml",
                                     env_file=str(Path(self.directory.name) / "missing.env"))
        self.config = self.manager.load()
        self.agent = FakeAgent()
        self.commands = []

    def run_menu(self, selections, answers=()):
        ui = ScriptedUI(selections, answers)
        run_config_menu(ui, self.config, self.manager, self.agent, self.commands.append)
        return ui

    def test_escape_on_the_main_menu_closes_without_changes(self):
        self.run_menu([None])
        self.assertEqual(self.commands, [])

    def test_effort_choice_runs_the_effort_command(self):
        self.run_menu([(2, "enter"), (2, "enter"), None])
        self.assertEqual(self.commands, ["/effort high"])

    def test_model_enter_saves_as_default_but_s_is_session_only(self):
        self.run_menu([(1, "enter"), (1, "enter"), None])
        self.assertEqual(self.commands, ["/model use llama3.2:3b"])
        self.assertEqual(self.config.active_provider.model, "llama3.2:3b")
        self.commands.clear()
        self.config.active_provider.model = "keep"
        self.run_menu([(1, "enter"), (0, "s"), None])
        self.assertEqual(self.commands, ["/model use qwen3.5:4b"])
        self.assertEqual(self.config.active_provider.model, "keep")

    def test_streaming_toggle_is_saved(self):
        self.run_menu([(3, "enter"), None])
        self.assertFalse(self.config.streaming_enabled)
        self.assertFalse(self.agent.streaming_enabled)
        self.assertFalse(self.manager.load().streaming_enabled)

    def test_mouse_toggle_is_saved_and_applied_to_the_tui(self):
        ui = ScriptedUI([(4, "enter"), None])
        ui.mouse_enabled = True
        run_config_menu(ui, self.config, self.manager, self.agent, self.commands.append)
        self.assertFalse(self.config.mouse_support)
        self.assertFalse(ui.mouse_enabled)
        self.assertFalse(self.manager.load().mouse_support)

    def test_add_provider_picks_the_model_from_what_the_server_serves(self):
        with patch("zerocoding.providers.openai_compatible.OpenAICompatibleProvider.list_models",
                   return_value=["qwen3.5:4b"]):
            self.run_menu([(5, "enter"), (0, "enter"), (0, "enter"), None],
                          answers=["tiny", "http://127.0.0.1:11434/v1"])
        self.assertEqual(self.commands, ["/provider add tiny openai_compatible http://127.0.0.1:11434/v1 qwen3.5:4b"])

    def test_add_provider_refuses_an_existing_name(self):
        ui = self.run_menu([(5, "enter"), (0, "enter"), None], answers=[self.config.provider])
        self.assertEqual(self.commands, [])
        self.assertTrue(any("already exists" in message for message in ui.messages))

    def test_remove_provider_never_offers_the_active_one(self):
        self.manager.save(self.config)
        ui = self.run_menu([(6, "enter"), None])
        self.assertEqual(self.commands, [])
        self.assertTrue(any("switch to another" in message for message in ui.messages))


if __name__ == "__main__":
    unittest.main()
