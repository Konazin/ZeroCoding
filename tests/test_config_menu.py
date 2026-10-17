import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zerocoding.config_menu import pick_model, run_settings
from zerocoding.core.config import ConfigManager
from zerocoding.tui.menus import CANCELLED, InputScreen, Row, SelectScreen, SettingsScreen, Tab


class ScriptedUI:
    """Feeds scripted key presses into the real screens, one key list per screen that opens."""

    def __init__(self, scripts):
        self.scripts, self.messages, self.mouse_enabled, self.opened = list(scripts), [], True, []

    def run_screen(self, screen):
        self.opened.append(screen)
        for key in self.scripts.pop(0) if self.scripts else ["escape"]:
            done = screen.key(key)
            if done is not None:
                return done
        return CANCELLED

    def show_success(self, text): self.messages.append(text)
    def show_error(self, text): self.messages.append(text)
    def show_warning(self, text): self.messages.append(text)
    def show_info(self, text): self.messages.append(text)


def typed(text):
    return [f"char:{c}" for c in text]


class FakeProvider:
    model = "qwen3.5:4b"

    def __init__(self, models=("qwen3.5:4b", "llama3.2:3b")):
        self.models = list(models)

    def list_models(self):
        return self.models

    def healthcheck(self):
        return True


class FakeAgent:
    effort = "medium"
    streaming_enabled = True

    def __init__(self, models=("qwen3.5:4b", "llama3.2:3b")):
        self.provider = FakeProvider(models)


class TestScreens(unittest.TestCase):
    def test_select_moves_wraps_jumps_and_confirms(self):
        screen = SelectScreen("t", [Row("a"), Row("b"), Row("c")])
        screen.key("up")
        self.assertEqual(screen.index, 2)
        screen.key("char:2")
        self.assertEqual(screen.index, 1)
        self.assertEqual(screen.key("enter").value, 1)
        self.assertTrue(SelectScreen("t", [Row("a")]).key("escape").cancelled)

    def test_select_extra_key_returns_the_row_and_the_key(self):
        screen = SelectScreen("t", [Row("a"), Row("b")], extra_keys={"s": "this session"})
        screen.key("down")
        done = screen.key("char:s")
        self.assertEqual((done.value, done.key), (1, "s"))
        self.assertIn("s this session", screen.footer())

    def test_select_adjuster_changes_effort_with_arrows_within_bounds(self):
        screen = SelectScreen("t", [Row("a")], adjust=("effort", ["low", "medium", "high"], "medium"))
        screen.key("right"); screen.key("right"); screen.key("right")
        self.assertEqual(screen.adjusted, "high")
        screen.key("left"); screen.key("left"); screen.key("left")
        self.assertEqual(screen.adjusted, "low")

    def test_select_renders_check_cursor_and_overflow(self):
        rows = [Row(f"m{i}", checked=i == 2) for i in range(12)]
        text = "".join(chunk for _, chunk in SelectScreen("Select model", rows, index=2, window=5).fragments(100))
        self.assertIn("❯", text)
        self.assertIn("✔", text)
        self.assertIn("more", text)

    def test_input_validates_before_accepting_and_edits(self):
        screen = InputScreen("Name", validate=lambda v: None if v.isalnum() else "letters only")
        for key in typed("a b"):
            screen.key(key)
        self.assertIsNone(screen.key("enter"))
        self.assertEqual(screen.error, "letters only")
        screen.key("backspace"); screen.key("backspace")
        self.assertEqual(screen.key("enter").value, "a")
        screen.key("ctrl-u")
        self.assertEqual(screen.value, "")

    def test_empty_box_accepts_the_suggested_name(self):
        screen = InputScreen("Name", fallback="ollama")
        self.assertIn("ollama", "".join(chunk for _, chunk in screen.fragments(60)))
        self.assertEqual(screen.key("enter").value, "ollama")

    def test_input_box_draws_a_border(self):
        text = "".join(chunk for _, chunk in InputScreen("Name", default="abc").fragments(60))
        self.assertIn("╭", text)
        self.assertIn("abc▌", text)

    def test_settings_tabs_search_and_enter(self):
        rows = [Row("Streaming", "true", "streaming"), Row("Mouse", "true", "mouse"), Row("Effort", "medium", "effort")]
        screen = SettingsScreen([Tab("Status", lines=lambda: [("A", "b")]), Tab("Config", rows=lambda: rows, searchable=True)], tab="Config")
        self.assertEqual(screen.focus, "list")
        for key in typed("mou"):
            screen.key(key)
        self.assertEqual([r.id for r in screen.visible_rows()], ["mouse"])
        self.assertEqual(screen.key("enter").value, ("Config", "mouse"))
        screen.key("escape")  # clears the filter first
        self.assertEqual(len(screen.visible_rows()), 3)
        screen.key("up")
        self.assertEqual(screen.focus, "tabs")
        screen.key("left")
        self.assertEqual(screen.current.name, "Status")
        self.assertTrue(screen.key("escape").cancelled)

    def test_disabled_rows_cannot_be_selected(self):
        screen = SettingsScreen([Tab("Config", rows=lambda: [Row("Thinking", "true", "t", enabled=False)])])
        self.assertIsNone(screen.key("enter"))


class MenuFlowCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = ConfigManager(user_config_path=Path(self.directory.name) / "config.yaml",
                                     env_file=str(Path(self.directory.name) / "missing.env"))
        self.config = self.manager.load()
        self.agent = FakeAgent()
        self.commands = []


class TestSettingsFlows(MenuFlowCase):
    def run_settings(self, scripts, tab="Config", agent=None):
        ui = ScriptedUI(scripts)
        run_settings(ui, self.config, self.manager, agent or self.agent, self.commands.append, tab=tab)
        return ui

    def test_toggle_rows_save_and_apply(self):
        # Config rows: Provider, Model, Effort, Permission mode, Streaming, Mouse, Save sessions
        self.run_settings([["down", "down", "down", "down", "enter"]])
        self.assertFalse(self.config.streaming_enabled)
        self.assertFalse(self.agent.streaming_enabled)
        self.assertFalse(self.manager.load().streaming_enabled)

    def test_mouse_toggle_updates_the_tui(self):
        ui = self.run_settings([["down", "down", "down", "down", "down", "enter"]])
        self.assertFalse(ui.mouse_enabled)
        self.assertFalse(self.manager.load().mouse_support)

    def test_effort_row_opens_a_picker_and_dispatches(self):
        self.run_settings([["down", "down", "enter"], ["char:3", "enter"]])
        self.assertEqual(self.commands, ["/effort high"])

    def test_provider_actions_use_and_remove(self):
        self.config.providers["tiny"] = type(self.config.active_provider)(
            name="tiny", type="openai_compatible", base_url="http://127.0.0.1:11434/v1", model="qwen3.5:4b")
        self.run_settings([["down", "enter"], ["enter"]], tab="Providers")
        self.assertEqual(self.commands, ["/provider use tiny"])
        self.commands.clear()
        self.run_settings([["down", "enter"], ["char:3", "enter"]], tab="Providers")
        self.assertEqual(self.commands, ["/provider remove tiny"])

    def test_add_provider_wizard_uses_lists_boxes_and_the_served_model(self):
        script = [
            ["down", "enter"],                               # Providers tab: "+ Add provider…" row
            ["enter"],                                       # type: openai_compatible
            typed("tiny") + ["enter"],                       # name box
            ["enter"],                                       # URL preset: Ollama
            ["enter"],                                       # model from the served list
        ]
        with patch("zerocoding.providers.openai_compatible.OpenAICompatibleProvider.list_models",
                   return_value=["qwen3.5:4b", "llama3.2:3b"]):
            self.run_settings(script, tab="Providers")
        self.assertEqual(self.commands, ["/provider add tiny openai_compatible http://127.0.0.1:11434/v1 qwen3.5:4b"])

    def test_add_provider_falls_back_to_typing_the_model_when_the_server_lists_none(self):
        script = [["down", "enter"], ["enter"], typed("tiny") + ["enter"], ["enter"], typed("my-model") + ["enter"]]
        with patch("zerocoding.providers.openai_compatible.OpenAICompatibleProvider.list_models", side_effect=RuntimeError("refused")):
            ui = self.run_settings(script, tab="Providers")
        self.assertEqual(self.commands, ["/provider add tiny openai_compatible http://127.0.0.1:11434/v1 my-model"])
        self.assertTrue(any("Could not read the model list" in m for m in ui.messages))

    def test_add_provider_rejects_bad_and_duplicate_names_inline(self):
        ui = self.run_settings([["down", "enter"], ["enter"], typed(self.config.provider) + ["enter"]], tab="Providers")
        name_box = ui.opened[2]
        self.assertEqual(name_box.error, "That name is already used.")
        self.assertEqual(self.commands, [])


class TestModelPicker(MenuFlowCase):
    def pick(self, script, agent=None):
        ui = ScriptedUI([script])
        pick_model(ui, self.config, self.manager, agent or self.agent, self.commands.append)
        return ui

    def test_enter_saves_default_and_s_is_session_only(self):
        self.pick(["down", "enter"])
        self.assertEqual(self.commands, ["/model use llama3.2:3b"])
        self.assertEqual(self.config.active_provider.model, "llama3.2:3b")
        self.commands.clear()
        self.config.active_provider.model = "keep"
        self.pick(["down", "char:s"])
        self.assertEqual(self.commands, ["/model use llama3.2:3b"])
        self.assertEqual(self.config.active_provider.model, "keep")

    def test_effort_adjuster_applies_the_new_level(self):
        self.pick(["right", "enter"])
        self.assertEqual(self.commands, ["/model use qwen3.5:4b", "/effort high"])

    def test_typed_model_when_the_server_lists_none(self):
        ui = ScriptedUI([typed("x") + ["enter"]])
        pick_model(ui, self.config, self.manager, FakeAgent(models=()), self.commands.append)
        self.assertTrue(any("did not list" in m for m in ui.messages))
        self.assertEqual(self.commands[0].startswith("/model use "), True)


if __name__ == "__main__":
    unittest.main()


class TestEffortMenu(unittest.TestCase):
    def test_effort_menu_shows_budgets_and_dispatches_the_choice(self):
        from zerocoding.config_menu import pick_effort

        agent = FakeAgent()
        from zerocoding.core.config import DEFAULT_EFFORT_PROFILES
        agent.effort_profiles = dict(DEFAULT_EFFORT_PROFILES)
        agent.window_tokens = lambda: 8192
        ui, chosen = ScriptedUI([["down", "enter"]]), []

        pick_effort(ui, agent, chosen.append)

        screen = ui.opened[0]
        self.assertEqual(chosen, ["/effort high"])
        self.assertIn("512 output tokens", screen.rows[0].value)
        self.assertIn("8192", screen.subtitle)
