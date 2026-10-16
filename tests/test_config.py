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


if __name__ == '__main__':
    unittest.main()
