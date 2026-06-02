import unittest

from zerocoding.providers.ollama import OllamaProvider


class TestOllamaProvider(unittest.TestCase):
    def test_ollama_provider_init(self):
        provider = OllamaProvider(url='http://localhost:11434', model='test-model')
        self.assertEqual(provider.model, 'test-model')


if __name__ == '__main__':
    unittest.main()
