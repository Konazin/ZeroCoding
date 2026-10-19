import unittest

from zerocoding.core.agent import Agent
from zerocoding.providers.base import ProviderCapabilities, ProviderTurn
from zerocoding.providers.llama_cpp import LlamaCppProvider
from zerocoding.providers.ollama import OllamaProvider
from zerocoding.providers.openai_compatible import OpenAICompatibleProvider

from tests.provider_kit import FakeBackend

MESSAGES = [{"role": "user", "content": "hi"}]


class TestCapabilities(unittest.TestCase):
    def test_each_backend_declares_what_it_can_do(self):
        llama = LlamaCppProvider("", "http://127.0.0.1:1/v1", "m").capabilities(detect_window=False)
        generic = OpenAICompatibleProvider("", "http://127.0.0.1:1/v1", "m").capabilities(detect_window=False)
        ollama = OllamaProvider("http://127.0.0.1:1", "m").capabilities(detect_window=False)

        self.assertEqual((llama.exact_token_count, llama.streaming, llama.reasoning_control), (True, True, "budget"))
        self.assertEqual((generic.exact_token_count, generic.streaming, generic.reasoning_control), (False, True, "none"))
        self.assertEqual((ollama.exact_token_count, ollama.streaming, ollama.reasoning_control), (False, False, "toggle"))

    def test_summary_is_readable_and_marks_unknown_windows(self):
        text = ProviderCapabilities(None, False, True, False, "none").summary()

        self.assertIn("context window unknown", text)
        self.assertIn("token count estimated", text)
        self.assertIn("ProviderCapabilities", repr(ProviderCapabilities()))

    def test_window_is_detected_when_asked(self):
        with FakeBackend("llama_cpp", n_ctx=6144) as backend:
            caps = LlamaCppProvider("", backend.base_url, "m").capabilities()

        self.assertEqual(caps.context_window, 6144)


class TestFinishReasonAndReasoningTokens(unittest.TestCase):
    def test_non_streaming_and_streaming_turns_carry_finish_reason(self):
        with FakeBackend("llama_cpp") as backend:
            provider = LlamaCppProvider("", backend.base_url, "m")
            backend.script = [{"content": "cut", "finish": "length",
                               "usage": {"completion_tokens_details": {"reasoning_tokens": 900}}}]
            plain = provider.chat(MESSAGES)
            backend.script = [{"content": "cut", "finish": "length"}]
            streamed = provider.chat_stream_turn(MESSAGES)

        self.assertEqual((plain.finish_reason, plain.reasoning_tokens), ("length", 900))
        self.assertEqual(streamed.finish_reason, "length")

    def test_ollama_reports_done_reason_as_finish_reason(self):
        with FakeBackend("ollama") as backend:
            backend.script = [{"content": "x", "finish": "length"}]
            turn = OllamaProvider(backend.base_url, "m").chat(MESSAGES)

        self.assertEqual(turn.finish_reason, "length")


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)

    def chat(self, messages, **kwargs):
        return self.turns.pop(0)


class TestEmptyReplyExplainsItself(unittest.TestCase):
    def test_reasoning_that_ate_the_output_limit_is_named_as_the_cause(self):
        empty = ProviderTurn(content="", finish_reason="length", reasoning_content="think " * 100, reasoning_tokens=1024)
        agent = Agent(Scripted([empty, empty]), max_output_tokens=1024)

        with self.assertRaises(RuntimeError) as caught:
            agent.ask("q")

        message = str(caught.exception)
        self.assertIn("output limit of 1024 tokens", message)
        self.assertIn("1024 tokens of private reasoning", message)
        self.assertIn("thinking: off", message)
        self.assertEqual(agent.last_turn["length_stops"], 2)

    def test_unknown_stop_reason_is_admitted(self):
        agent = Agent(Scripted([ProviderTurn(content=""), ProviderTurn(content="")]))

        with self.assertRaises(RuntimeError) as caught:
            agent.ask("q")

        self.assertIn("did not say why it stopped", str(caught.exception))

    def test_other_finish_reasons_are_reported_verbatim(self):
        turn = ProviderTurn(content="", finish_reason="content_filter")
        agent = Agent(Scripted([turn, turn]))

        with self.assertRaises(RuntimeError) as caught:
            agent.ask("q")

        self.assertIn("content_filter", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
