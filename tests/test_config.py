import unittest

from zerocoding.core.config import Config


class TestConfigLoad(unittest.TestCase):
    def test_config_load_override(self):
        config = Config.load(override_provider='ollama')
        self.assertEqual(config.provider, 'ollama')
        self.assertTrue(config.model)
        self.assertTrue(config.memory_path)


if __name__ == '__main__':
    unittest.main()
