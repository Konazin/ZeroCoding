import unittest

from zerocoding.providers.ollama import OllamaProvider
from zerocoding.providers.base import ProviderTurn


class TestOllamaProvider(unittest.TestCase):
    def test_ollama_provider_init(self):
        provider = OllamaProvider(url='http://localhost:11434', model='test-model')
        self.assertEqual(provider.model, 'test-model')

    def test_structured_tool_calls_and_context_budget(self):
        provider = OllamaProvider(url='http://localhost:11434', model='test-model')
        sent = {}
        provider._post = lambda endpoint, payload, stream=False: sent.update(payload=payload) or {
            "prompt_eval_count": 20,
            "eval_count": 2,
            "prompt_eval_duration": 300_000_000,
            "eval_duration": 50_000_000,
            "total_duration": 400_000_000,
            "load_duration": 12_000_000,
            "done_reason": "stop",
            "message": {
                "content": "",
                "thinking": "private reasoning that must not be returned",
                "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a.py"}}}],
            },
        }

        turn = provider.chat([{"role": "user", "content": "read"}], tools=[{"type": "function"}],
                             num_ctx=5120, max_tokens=1024)

        self.assertIsInstance(turn, ProviderTurn)
        self.assertEqual(turn.tool_calls[0].name, "read_file")
        self.assertEqual(turn.tool_calls[0].arguments, {"path": "a.py"})
        self.assertEqual(turn.usage, {
            "prompt_tokens": 20,
            "completion_tokens": 2,
            "prompt_eval_duration_ns": 300_000_000,
            "eval_duration_ns": 50_000_000,
            "total_duration_ns": 400_000_000,
            "load_duration_ns": 12_000_000,
            "done_reason": "stop",
        })
        self.assertTrue(turn.thinking_present)
        self.assertNotIn("private reasoning", turn.content)
        self.assertEqual(sent["payload"]["options"]["num_ctx"], 5120)
        self.assertEqual(sent["payload"]["options"]["num_predict"], 1024)

    def test_explicit_thinking_toggle_is_sent_without_exposing_thought_text(self):
        provider = OllamaProvider(url='http://localhost:11434', model='test-model')
        payloads = []

        def fake_post(endpoint, payload, stream=False):
            payloads.append(payload)
            return {"message": {"content": "answer", "thinking": "private"}}

        provider._post = fake_post
        on_turn = provider.chat([{"role": "user", "content": "hello"}], think=True)
        off_turn = provider.chat([{"role": "user", "content": "hello"}], think=False)
        default_turn = provider.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(payloads[0]["think"], True)
        self.assertEqual(payloads[1]["think"], False)
        self.assertNotIn("think", payloads[2])
        self.assertEqual(on_turn.content, "answer")
        self.assertEqual(off_turn.content, "answer")
        self.assertTrue(on_turn.thinking_present)
        self.assertTrue(off_turn.thinking_present)
        self.assertTrue(default_turn.thinking_present)

    def test_usage_fields_are_optional(self):
        provider = OllamaProvider(url='http://localhost:11434', model='test-model')
        provider._post = lambda endpoint, payload, stream=False: {
            "message": {"content": "ok"},
            "prompt_eval_count": 12,
        }

        turn = provider.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(turn.usage, {"prompt_tokens": 12})


if __name__ == '__main__':
    unittest.main()
