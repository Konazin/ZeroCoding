import unittest

from zerocoding.core.readiness import check_provider_readiness, model_is_available, readiness_hint


class FakeProvider:
    def __init__(self, models=None, error=None):
        self.models = models or []
        self.error = error

    def healthcheck(self):
        return self.error is None

    def list_models(self):
        if self.error:
            raise RuntimeError(self.error)
        return self.models


class TestReadiness(unittest.TestCase):
    def test_model_matching_accepts_implicit_latest_tag(self):
        self.assertTrue(model_is_available("qwen2.5-coder", ["qwen2.5-coder:latest"]))
        self.assertFalse(model_is_available("qwen2.5-coder:7b", ["qwen2.5-coder:latest"]))

    def test_ollama_readiness_reports_connection_failure(self):
        result = check_provider_readiness(FakeProvider(error="offline"), "ollama", "qwen2.5-coder:7b")
        self.assertEqual(result.status, "offline")
        self.assertFalse(result.ready)

    def test_ollama_readiness_reports_missing_model_and_available_choices(self):
        result = check_provider_readiness(FakeProvider(["qwen2.5-coder:7b"]), "ollama", "deepseek-coder-v2")
        self.assertEqual(result.status, "model-missing")
        self.assertEqual(result.models, ("qwen2.5-coder:7b",))
        self.assertFalse(result.ready)

    def test_ollama_readiness_reports_empty_model_list(self):
        result = check_provider_readiness(FakeProvider(), "ollama", "deepseek-coder-v2")
        self.assertEqual(result.status, "no-models")

    def test_compatible_provider_uses_healthcheck_without_model_catalog(self):
        result = check_provider_readiness(FakeProvider(), "openai_compatible", "model-x")
        self.assertEqual(result.status, "connected")
        self.assertTrue(result.ready)

    def test_readiness_hints_provide_next_steps(self):
        offline = check_provider_readiness(FakeProvider(error="offline"), "ollama", "qwen2.5-coder:7b")
        empty = check_provider_readiness(FakeProvider(), "ollama", "qwen2.5-coder:7b")
        missing = check_provider_readiness(FakeProvider(["qwen2.5-coder:7b"]), "ollama", "deepseek-coder-v2")

        self.assertIn("ollama serve", readiness_hint(offline, "ollama", "qwen2.5-coder:7b"))
        self.assertIn("ollama pull", readiness_hint(empty, "ollama", "qwen2.5-coder:7b"))
        self.assertIn("qwen2.5-coder:7b", readiness_hint(missing, "ollama", "deepseek-coder-v2"))


if __name__ == "__main__":
    unittest.main()
