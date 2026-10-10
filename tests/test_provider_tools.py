import unittest
from io import BytesIO
from unittest.mock import patch

from zerocoding.providers.ollama import OllamaProvider
from zerocoding.providers.openai_compatible import OpenAICompatibleProvider


class TestProviderTools(unittest.TestCase):
    def test_ollama_tool_response_is_normalized(self):
        provider = OllamaProvider("http://localhost:11434", "model")
        with patch.object(provider, "_post", return_value={"message": {"content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "x"}}}]}}):
            result = provider.chat_with_tools([], [])
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "read_file")

    def test_ollama_stream_emits_text_and_tool_calls(self):
        provider = OllamaProvider("http://localhost:11434", "model")
        body = b'{"message":{"content":"checking"}}\n{"message":{"tool_calls":[{"function":{"name":"read_file","arguments":{"path":"a"}}}]},"done":true}\n'
        with patch.object(provider, "_post", return_value=BytesIO(body)):
            events = list(provider.chat_stream_with_tools([], []))
        self.assertEqual(events[0], {"content": "checking"})
        self.assertEqual(events[-1]["tool_calls"][0]["function"]["name"], "read_file")

    def test_ollama_plain_stream_keeps_final_usage_for_agent_metrics(self):
        provider = OllamaProvider("http://localhost:11434", "model")
        body = b'{"message":{"content":"hello"}}\n{"done":true,"prompt_eval_count":12,"eval_count":4,"prompt_eval_duration":1000000,"eval_duration":2000000,"total_duration":3000000}\n'
        with patch.object(provider, "_post", return_value=BytesIO(body)):
            self.assertEqual(list(provider.chat_stream([], max_output_tokens=128)), ["hello"])
        self.assertEqual(provider.last_usage, {"input_tokens": 12, "prefill_ms": 1.0, "output_tokens": 4, "generation_ms": 2.0, "total_ms": 3.0})

    def test_openai_tool_response_is_normalized(self):
        provider = OpenAICompatibleProvider("", "http://localhost/v1", "model")
        with patch.object(provider, "_post", return_value={"choices": [{"message": {"content": None, "tool_calls": [{"id": "x"}]}}]}):
            result = provider.chat_with_tools([], [])
        self.assertEqual(result["content"], "")
        self.assertEqual(result["tool_calls"][0]["id"], "x")

    def test_openai_stream_joins_partial_tool_call(self):
        provider = OpenAICompatibleProvider("", "http://localhost/v1", "model")
        body = b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"x","function":{"name":"read_","arguments":"{\\"path\\":"}}]}}]}\n'
        body += b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":"\\"a\\"}"}}]}}]}\n'
        body += b'data: [DONE]\n'
        with patch.object(provider, "_post", return_value=BytesIO(body)):
            events = list(provider.chat_stream_with_tools([], []))
        call = events[-1]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "read_file")
        self.assertEqual(call["function"]["arguments"], '{"path":"a"}')


if __name__ == "__main__":
    unittest.main()
