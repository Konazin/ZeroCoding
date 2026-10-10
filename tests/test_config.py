import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.config import Config, ConfigManager


class TestConfigLoad(unittest.TestCase):
    def test_permission_mode_defaults_to_manual_and_round_trips(self):
        config = Config.load()
        self.assertEqual(config.permission_mode, "manual")

        config.permission_mode = "approve_for_me"
        with tempfile.TemporaryDirectory() as tmp:
            manager = ConfigManager(user_config_path=Path(tmp) / "config.yaml", env_file=str(Path(tmp) / "missing.env"))
            manager.save(config)
            restored = manager.load()

        self.assertEqual(restored.permission_mode, "approve_for_me")

    def test_invalid_permission_mode_falls_back_to_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("permission_mode: unlimited\n", encoding="utf-8")
            manager = ConfigManager(user_config_path=path, env_file=str(Path(tmp) / "missing.env"))
            self.assertEqual(manager.load().permission_mode, "manual")

    def test_config_load_override(self):
        config = Config.load(override_provider='ollama')
        self.assertEqual(config.provider, 'ollama')
        self.assertTrue(config.model)
        self.assertTrue(config.memory_path)

    def test_modes_are_loaded(self):
        config = Config.load()
        self.assertIn('code', config.modes)
        self.assertIn('reason', config.modes)
        self.assertEqual(config.modes['code'].provider, 'ollama_local')

    def test_provider_and_model_switch_state(self):
        config = Config.load()
        config.provider = 'ollama_local'
        config.model = 'deepseek-coder-v2'
        self.assertEqual(config.provider, 'ollama_local')
        self.assertEqual(config.model, 'deepseek-coder-v2')

    def test_model_environment_override_applies_to_environment_selected_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ConfigManager(user_config_path=Path(tmp) / "missing.yaml", env_file=str(Path(tmp) / "missing.env"))
            with patch.dict("os.environ", {
                "ZEROCODING_PROVIDER": "ollama_local",
                "ZEROCODING_MODEL": "qwen2.5-coder:4b",
            }, clear=True):
                config = manager.load()

        self.assertEqual(config.provider, "ollama_local")
        self.assertEqual(config.model, "qwen2.5-coder:4b")

    def test_model_environment_override_resolves_legacy_ollama_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ConfigManager(user_config_path=Path(tmp) / "missing.yaml", env_file=str(Path(tmp) / "missing.env"))
            with patch.dict("os.environ", {"ZEROCODING_PROVIDER": "ollama", "ZEROCODING_MODEL": "custom-local-model"}, clear=True):
                config = manager.load()

        self.assertEqual(config.provider, "ollama_local")
        self.assertEqual(config.model, "custom-local-model")


if __name__ == '__main__':
    unittest.main()
