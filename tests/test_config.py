import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.agent import Agent
from zerocoding.core.config import MAX_TOOL_ROUNDS, Config, ConfigManager


def isolated_config(user_yaml: str | None = None) -> Config:
    """Load config from the packaged defaults only.

    No ~/.zerocoding/config.yaml, no .env and no ZEROCODING_* variables, so the result cannot depend
    on the machine running the tests. `user_yaml` stands in for the user layer when a test needs one.
    """
    with tempfile.TemporaryDirectory() as directory:
        user_path = Path(directory) / "config.yaml"
        if user_yaml is not None:
            user_path.write_text(user_yaml, encoding="utf-8")
        manager = ConfigManager(user_config_path=user_path, env_file=str(Path(directory) / "missing.env"))
        clean = {key: value for key, value in os.environ.items() if not key.startswith("ZEROCODING_")}
        with patch.dict("os.environ", clean, clear=True):
            return manager.load()


class _NoProvider:
    """Agent tests below never call the model."""


class TestConfigLoad(unittest.TestCase):
    def test_config_load_override(self):
        config = Config.load(override_provider='ollama')
        self.assertEqual(config.provider, 'ollama')
        self.assertTrue(config.model)
        self.assertTrue(config.memory_path)

    def test_modes_are_loaded(self):
        config = isolated_config()  # never reads ~/.zerocoding/config.yaml, .env or ZEROCODING_* variables
        self.assertIn('code', config.modes)
        self.assertIn('reason', config.modes)
        self.assertEqual(config.provider, 'llama_cpp_local')
        self.assertEqual(config.active_provider.type, 'llama_cpp')
        self.assertEqual(config.modes['code'].provider, 'llama_cpp_local')
        self.assertEqual(config.modes['fast'].model, config.modes['reason'].model)
        self.assertEqual(config.modes['smart'].model, config.model)

    def test_provider_and_model_switch_state(self):
        config = Config.load()
        config.provider = 'llama_cpp_local'
        config.model = 'ornith-1.5-9b-q5-k-m'
        self.assertEqual(config.provider, 'llama_cpp_local')
        self.assertEqual(config.model, 'ornith-1.5-9b-q5-k-m')

    def test_lightweight_agent_budgets(self):
        config = isolated_config()
        self.assertEqual(config.max_input_tokens, 4096)
        self.assertEqual(config.max_output_tokens, 1024)
        self.assertEqual(config.max_tool_rounds, 40)  # safety cap, not a target

    def test_effort_changes_output_tokens_but_never_the_round_cap(self):
        config = isolated_config()
        profiles = config.effort_profiles

        self.assertEqual({name: profile.max_output_tokens for name, profile in profiles.items()},
                         {"low": 512, "medium": 1024, "high": 2048})
        self.assertEqual({profile.max_tool_rounds for profile in profiles.values()}, {40})

    def test_agent_applies_each_effort_profile_with_one_round_cap(self):
        config = isolated_config()
        agent = Agent(_NoProvider(), max_output_tokens=config.max_output_tokens, max_tool_rounds=config.max_tool_rounds,
                      effort_profiles=config.effort_profiles)

        budgets = {}
        for level in ("low", "medium", "high"):
            agent.set_session_controls(effort=level)
            budgets[level] = agent.effective_budgets()

        self.assertEqual(budgets, {"low": (512, 40), "medium": (1024, 40), "high": (2048, 40)})

    def test_ultrathink_adds_output_tokens_but_no_rounds(self):
        config = isolated_config()
        agent = Agent(_NoProvider(), max_tool_rounds=config.max_tool_rounds, effort_profiles=config.effort_profiles)
        agent.set_session_controls(effort="medium", ultrathink=True)

        self.assertEqual(agent.effective_budgets(), (1024 + 1024, 40))

    def test_an_explicit_cap_applies_to_every_effort_and_is_clamped(self):
        for configured, expected in ((12, 12), (500, MAX_TOOL_ROUNDS)):
            config = isolated_config(f"max_tool_rounds: {configured}\n")
            agent = Agent(_NoProvider(), max_tool_rounds=config.max_tool_rounds, effort_profiles=config.effort_profiles)
            for level in ("low", "medium", "high"):
                agent.set_session_controls(effort=level)
                self.assertEqual(agent.effective_budgets()[1], expected, (configured, level))

    def test_agent_without_config_uses_the_same_safety_cap(self):
        agent = Agent(_NoProvider())

        for level in ("low", "medium", "high"):
            agent.set_session_controls(effort=level)
            self.assertEqual(agent.effective_budgets()[1], 40, level)

    def test_streaming_defaults_on_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(user_config_path=Path(directory) / "config.yaml", env_file=str(Path(directory) / "missing.env"))
            config = manager.load()
            self.assertTrue(config.streaming_enabled)
            config.streaming_enabled = False
            manager.save(config)
            self.assertFalse(manager.load().streaming_enabled)

    def test_session_persistence_defaults_on_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            manager = ConfigManager(user_config_path=path, env_file=str(Path(directory) / "missing.env"))
            config = manager.load()
            self.assertTrue(config.session_persistence)

            config.session_persistence = False
            manager.save(config)

            self.assertFalse(manager.load().session_persistence)

    def test_session_persistence_can_be_disabled_by_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigManager(
                user_config_path=Path(directory) / "missing.yaml",
                env_file=str(Path(directory) / "missing.env"),
            )
            with patch.dict("os.environ", {"ZEROCODING_SESSION_PERSISTENCE": "false"}):
                self.assertFalse(manager.load().session_persistence)


if __name__ == '__main__':
    unittest.main()
