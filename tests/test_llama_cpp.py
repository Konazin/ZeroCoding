import unittest

from zerocoding.core.config import Config, ProviderConfig
from zerocoding.core.router import build_provider
from zerocoding.providers.base import ProviderTurn
from zerocoding.providers.llama_cpp import LlamaCppProvider


class TestLlamaCppProvider(unittest.TestCase):
    def test_native_effort_and_request_round_trip(self):
        provider = LlamaCppProvider(
            api_key="",
            api_url="http://127.0.0.1:8080/v1",
            model="ornith-1.5-9b-q5-k-m",
        )
        sent = {}
        provider._post = lambda endpoint, payload: sent.update(endpoint=endpoint, payload=payload) or {
            "choices": [{
                "message": {
                    "content": "Read result summarized.",
                    "reasoning_content": "private reasoning",
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"sample.py"}'},
                    }],
                }
            }],
            "usage": {"prompt_tokens": 42, "completion_tokens": 17},
        }

        turn = provider.chat(
            [{"role": "user", "content": "Read the file"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
            max_tokens=512,
            reasoning_effort="high",
        )

        self.assertIsInstance(turn, ProviderTurn)
        self.assertEqual(sent["endpoint"], "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(sent["payload"]["model"], "ornith-1.5-9b-q5-k-m")
        self.assertEqual(sent["payload"]["reasoning_effort"], "high")
        self.assertEqual(sent["payload"]["tool_choice"], "auto")
        self.assertEqual(sent["payload"]["max_tokens"], 512)
        self.assertEqual(turn.content, "Read result summarized.")
        self.assertNotIn("private reasoning", turn.content)
        self.assertEqual(turn.reasoning_content, "private reasoning")
        self.assertTrue(turn.thinking_present)
        self.assertEqual(turn.tool_calls[0].call_id, "call-1")
        self.assertEqual(turn.tool_calls[0].arguments, {"path": "sample.py"})
        self.assertEqual(turn.usage["prompt_tokens"], 42)
        self.assertEqual(provider.tool_result_message("call-1", "read_file", "ok"), {
            "role": "tool", "tool_call_id": "call-1", "name": "read_file", "content": "ok"
        })

    def test_effort_levels_are_explicit_and_invalid_level_is_unsupported(self):
        provider = LlamaCppProvider("", "http://127.0.0.1:8080/v1", "ornith")
        self.assertEqual(provider.native_effort_kwargs("low"), {"reasoning_effort": "low"})
        self.assertEqual(provider.native_effort_kwargs("medium"), {"reasoning_effort": "medium"})
        self.assertEqual(provider.native_effort_kwargs("high"), {"reasoning_effort": "high"})
        self.assertIsNone(provider.native_effort_kwargs("extreme"))
        self.assertIn("template-dependent", provider.native_effort_status("high"))

    def test_router_builds_llama_cpp_type(self):
        config = Config(
            provider="local",
            providers={
                "local": ProviderConfig(
                    name="local",
                    type="llama_cpp",
                    base_url="http://127.0.0.1:8080/v1",
                    model="ornith",
                )
            },
        )
        provider = build_provider(config)
        self.assertIsInstance(provider, LlamaCppProvider)
        self.assertEqual(provider.model, "ornith")
        self.assertEqual(provider.timeout, 300)


if __name__ == "__main__":
    unittest.main()
