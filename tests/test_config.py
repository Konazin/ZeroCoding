import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.config import Config, ConfigManager


class TestConfigLoad(unittest.TestCase):
    def test_config_load_override(self):
        config = Config.load(override_provider='ollama')
        self.assertEqual(config.provider, 'ollama')
        self.assertTrue(config.model)
        self.assertTrue(config.memory_path)

    def test_modes_are_loaded(self):
        with tempfile.TemporaryDirectory() as directory:  # never read the real ~/.zerocoding/config.yaml
            manager = ConfigManager(user_config_path=Path(directory) / "config.yaml", env_file=str(Path(directory) / "missing.env"))
            config = manager.load()
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
        config = Config.load()
        self.assertEqual(config.max_input_tokens, 4096)
        self.assertEqual(config.max_output_tokens, 1024)
        self.assertEqual(config.max_tool_rounds, 6)

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
