import unittest

from zerocoding.core.config import Config


class TestConfigLoad(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
