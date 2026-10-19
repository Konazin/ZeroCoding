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
        self.assertEqual((generic.exact_token_count, generic.streaming, generic.reasoning_control), (False, True, "toggle"))
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


class TestContextWindowProbes(unittest.TestCase):
    def test_llama_cpp_reads_props(self):
        with FakeBackend("llama_cpp", n_ctx=6144) as backend:
            self.assertEqual(LlamaCppProvider("", backend.base_url, "fake").context_window(), 6144)

    def test_generic_servers_fall_back_to_the_models_entry_then_lmstudio(self):
        with FakeBackend("openai", model_max=32768) as backend:
            self.assertEqual(OpenAICompatibleProvider("", backend.base_url, "fake").context_window(), 32768)
        with FakeBackend("openai", lmstudio_loaded=12000) as backend:
            self.assertEqual(OpenAICompatibleProvider("", backend.base_url, "fake").context_window(), 12000)

    def test_unknown_window_is_none_and_a_failed_probe_is_not_repeated_every_call(self):
        with FakeBackend("openai") as backend:
            provider = OpenAICompatibleProvider("", backend.base_url, "fake")
            self.assertIsNone(provider.context_window())
            first = len(backend.requests)
            self.assertIsNone(provider.context_window())
            self.assertIsNone(provider.context_window())

            self.assertEqual(len(backend.requests), first)

    def test_a_successful_probe_is_cached_for_good(self):
        with FakeBackend("llama_cpp", n_ctx=4096) as backend:
            provider = LlamaCppProvider("", backend.base_url, "fake")
            provider.context_window()
            seen = len(backend.requests)
            provider.context_window()

            self.assertEqual(len(backend.requests), seen)

    def test_native_ollama_uses_the_model_maximum_capped_at_8192(self):
        for model_max, expected in ((32768, 8192), (4096, 4096), (None, None)):
            with FakeBackend("ollama", model_max=model_max) as backend:
                self.assertEqual(OllamaProvider(backend.base_url, "fake").context_window(), expected, model_max)

    def test_an_unreachable_server_gives_none_quickly(self):
        import time
        provider = OpenAICompatibleProvider("", "http://127.0.0.1:9/v1", "m")
        started = time.monotonic()

        self.assertIsNone(provider.context_window())
        self.assertLess(time.monotonic() - started, 5)

    def test_the_agent_sizes_its_prompt_from_the_probed_window(self):
        with FakeBackend("ollama", model_max=32768) as backend:
            agent = Agent(OllamaProvider(backend.base_url, "fake"), max_output_tokens=1024)

            self.assertEqual(agent.window_tokens(), 8192)
            self.assertEqual(agent.input_budget(1024), 8192 - 1024 - 128)


class TestAnswerStuckInTheReasoningField(unittest.TestCase):
    """Seen live: Qwen 3.5 on Ollama's /v1 put the whole final answer in `reasoning` and left `content` empty."""

    def test_the_reasoning_key_ollama_uses_is_read_like_reasoning_content(self):
        with FakeBackend("openai") as backend:
            backend.script = [{"content": "", "reasoning": "thinking out loud", "reasoning_key": "reasoning"}]
            turn = OpenAICompatibleProvider("", backend.base_url, "fake").chat(MESSAGES)

        self.assertTrue(turn.thinking_present)
        self.assertEqual(turn.reasoning_content, "thinking out loud")
        self.assertEqual(turn.content, "")

    def test_an_empty_reply_is_retried_once_with_reasoning_switched_off(self):
        with FakeBackend("openai") as backend:
            backend.script = [{"content": "", "reasoning": "I fixed it", "reasoning_key": "reasoning"},
                              {"content": "I fixed the bug in calc.py."}]
            agent = Agent(OpenAICompatibleProvider("", backend.base_url, "fake"), streaming_enabled=False)

            answer = agent.ask("fix it")
            bodies = backend.bodies("/v1/chat/completions")

        self.assertEqual(answer, "I fixed the bug in calc.py.")
        self.assertNotIn("reasoning_effort", bodies[0])
        self.assertEqual(bodies[1]["reasoning_effort"], "none")

    def test_the_retry_after_a_tool_result_also_drops_reasoning_and_then_goes_back_to_normal(self):
        import tempfile
        from pathlib import Path
        from zerocoding.core.tools import ToolRegistry

        with tempfile.TemporaryDirectory() as tmp, FakeBackend("openai") as backend:
            (Path(tmp) / "a.py").write_text("x = 1\n")
            backend.script = [{"tool_calls": [("read_file", {"path": "a.py"})]},
                              {"content": "", "reasoning": "answer in the wrong field", "reasoning_key": "reasoning"},
                              {"content": "a.py sets x to 1."}]
            agent = Agent(OpenAICompatibleProvider("", backend.base_url, "fake"),
                          tools=ToolRegistry(tmp, approve=lambda *_: False), streaming_enabled=False)

            answer = agent.ask("what is in a.py?", use_tools=True)
            bodies = backend.bodies("/v1/chat/completions")

        self.assertEqual(answer, "a.py sets x to 1.")
        self.assertEqual([b.get("reasoning_effort") for b in bodies], [None, None, "none"])

    def test_when_the_retry_is_also_empty_the_error_names_the_reasoning_field(self):
        with FakeBackend("openai") as backend:
            stuck = {"content": "", "reasoning": "all the text is here", "reasoning_key": "reasoning"}
            backend.script = [stuck, stuck]
            agent = Agent(OpenAICompatibleProvider("", backend.base_url, "fake"), streaming_enabled=False)

            with self.assertRaises(RuntimeError) as caught:
                agent.ask("fix it")

        self.assertIn("private reasoning field", str(caught.exception))

    def test_backends_without_reasoning_control_are_not_retried_pointlessly(self):
        agent = Agent(Scripted([ProviderTurn(content=""), ProviderTurn(content="")]))

        self.assertFalse(agent._can_retry_without_thinking())
