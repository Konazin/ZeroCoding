import unittest

from zerocoding.core.agent import Agent, fit_messages
from zerocoding.core.tokens import MESSAGE_OVERHEAD, TokenCounter, estimate_tokens
from zerocoding.providers.base import ProviderTurn
from zerocoding.providers.llama_cpp import LlamaCppProvider


class FakeTokenizer:
    def __init__(self, per_char=1.0, fail=False):
        self.calls = []
        self.per_char = per_char
        self.fail = fail

    def count_tokens(self, text):
        self.calls.append(text)
        return None if self.fail else int(len(text) * self.per_char)


class TestTokenCounter(unittest.TestCase):
    def test_uses_provider_tokenizer_and_caches(self):
        provider = FakeTokenizer()
        counter = TokenCounter(provider)
        messages = [{"role": "user", "content": "hello"}]
        first = counter(messages)
        self.assertEqual(first, len('"hello"') + MESSAGE_OVERHEAD)
        counter(messages)
        self.assertEqual(len(provider.calls), 1)

    def test_falls_back_after_first_failure(self):
        provider = FakeTokenizer(fail=True)
        counter = TokenCounter(provider)
        messages = [{"role": "user", "content": "x" * 400}]
        self.assertEqual(counter(messages), estimate_tokens('"' + "x" * 400 + '"') + MESSAGE_OVERHEAD)
        self.assertFalse(counter.server_enabled)
        counter(messages)
        self.assertEqual(len(provider.calls), 1)

    def test_provider_without_tokenizer_uses_heuristic(self):
        counter = TokenCounter(object())
        self.assertFalse(counter.server_enabled)
        self.assertEqual(counter([{"x": 1}]), estimate_tokens([{"x": 1}]))

    def test_fit_messages_follows_injected_counter(self):
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "now"},
        ]
        dense = TokenCounter(FakeTokenizer(per_char=3.0))
        fitted_dense = fit_messages(messages, 60, dense)
        fitted_sparse = fit_messages(messages, 60, TokenCounter(FakeTokenizer(per_char=0.1)))
        self.assertLess(len(fitted_dense), len(fitted_sparse))
        self.assertEqual(fitted_dense[-1]["content"], "now")

    def test_agent_budgets_with_server_counts(self):
        class Provider(FakeTokenizer):
            def __init__(self):
                super().__init__(per_char=2.0)
                self.sent = None

            def chat(self, messages, **kwargs):
                self.sent = messages
                return ProviderTurn(content="ok")

        provider = Provider()
        agent = Agent(provider, max_input_tokens=256)
        agent.ask("current question", system_prompt="system")
        self.assertEqual(provider.sent[-1]["content"], "current question")


class TestLlamaCppTokenize(unittest.TestCase):
    def _provider(self, url="http://127.0.0.1:8080/v1"):
        return LlamaCppProvider(api_key="", api_url=url, model="m")

    def test_count_tokens_uses_server_root_tokenize(self):
        provider = self._provider()
        sent = {}
        provider._post = lambda endpoint, payload: sent.update(endpoint=endpoint, payload=payload) or {"tokens": [1, 2, 3]}
        self.assertEqual(provider.count_tokens("abc"), 3)
        self.assertEqual(sent["endpoint"], "http://127.0.0.1:8080/tokenize")
        self.assertEqual(sent["payload"], {"content": "abc"})

    def test_count_tokens_returns_none_on_error(self):
        provider = self._provider()

        def boom(endpoint, payload):
            raise RuntimeError("down")

        provider._post = boom
        self.assertIsNone(provider.count_tokens("abc"))


if __name__ == "__main__":
    unittest.main()
