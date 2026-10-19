"""The same behavioural checks run against every backend type, using the fake servers in provider_kit."""
import tempfile
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.config import ProviderConfig, normalize_thinking
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.llama_cpp import LlamaCppProvider
from zerocoding.providers.ollama import OllamaProvider
from zerocoding.providers.openai_compatible import OpenAICompatibleProvider

from tests.provider_kit import FakeBackend

MESSAGES = [{"role": "user", "content": "hi"}]
TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "r",
                                           "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]
BACKENDS = {
    "llama_cpp": lambda url, **kw: LlamaCppProvider("", url, "fake", **kw),
    "openai": lambda url, **kw: OpenAICompatibleProvider("", url, "fake", **kw),
    "ollama": lambda url, **kw: OllamaProvider(url, "fake", **kw),
}


def every_backend(test):
    def wrapper(self):
        for kind, build in BACKENDS.items():
            with self.subTest(backend=kind), FakeBackend(kind) as backend:
                test(self, kind, backend, build(backend.base_url))
    return wrapper


def chat_path(kind):
    return "/api/chat" if kind == "ollama" else "/v1/chat/completions"


class TestConformance(unittest.TestCase):
    @every_backend
    def test_plain_answer_usage_and_finish_reason(self, kind, backend, provider):
        backend.script = [{"content": "hello"}]

        turn = provider.chat(MESSAGES)

        self.assertEqual(turn.content, "hello")
        self.assertEqual(turn.usage.get("prompt_tokens"), 10)
        self.assertEqual(turn.usage.get("completion_tokens"), 5)
        self.assertEqual(turn.finish_reason, "stop")

    @every_backend
    def test_native_tool_calls_become_tool_call_objects(self, kind, backend, provider):
        backend.script = [{"tool_calls": [("read_file", {"path": "a.py"})]}]

        turn = provider.chat(MESSAGES, tools=TOOLS)

        self.assertEqual([(c.name, c.arguments) for c in turn.tool_calls], [("read_file", {"path": "a.py"})])
        self.assertTrue(backend.bodies(chat_path(kind))[0]["tools"])

    @every_backend
    def test_private_reasoning_stays_out_of_the_answer(self, kind, backend, provider):
        backend.script = [{"content": "answer", "reasoning": "secret chain of thought"}]

        turn = provider.chat(MESSAGES)

        self.assertEqual(turn.content, "answer")
        self.assertTrue(turn.thinking_present)
        self.assertNotIn("secret", turn.content)

    @every_backend
    def test_the_agent_loop_runs_end_to_end(self, kind, backend, provider):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("print('x')\n")
            backend.script = [{"tool_calls": [("read_file", {"path": "a.py"})]}, {"content": "it prints x"}]
            agent = Agent(provider, tools=ToolRegistry(tmp, approve=lambda *_: False), streaming_enabled=False)

            answer = agent.ask("what does a.py print?", use_tools=True)

        self.assertEqual(answer, "it prints x")
        self.assertEqual(agent.last_turn["tool_calls"], 1)
        self.assertEqual(len(backend.bodies(chat_path(kind))), 2)

    def test_streaming_backends_assemble_text_tools_and_usage(self):
        for kind in ("llama_cpp", "openai"):
            with self.subTest(backend=kind), FakeBackend(kind) as backend:
                provider = BACKENDS[kind](backend.base_url)
                backend.script = [{"content": "streamed text", "tool_calls": [("read_file", {"path": "a.py"})]}]
                seen = []

                turn = provider.chat_stream_turn(MESSAGES, on_delta=seen.append, tools=TOOLS)

                self.assertEqual("".join(seen), "streamed text")
                self.assertEqual(turn.content, "streamed text")
                self.assertEqual([(c.name, c.arguments) for c in turn.tool_calls], [("read_file", {"path": "a.py"})])
                self.assertEqual(turn.usage["prompt_tokens"], 10)
                self.assertEqual(turn.finish_reason, "tool_calls")

    def test_the_agent_streams_through_a_streaming_backend(self):
        with FakeBackend("llama_cpp") as backend:
            backend.script = [{"content": "streamed answer"}]
            agent = Agent(BACKENDS["llama_cpp"](backend.base_url), streaming_enabled=True)

            self.assertEqual(agent.ask("hi"), "streamed answer")
            self.assertTrue(backend.bodies("/v1/chat/completions")[0]["stream"])


class TestThinkingTranslation(unittest.TestCase):
    def sent(self, kind, thinking, **chat_kwargs):
        with FakeBackend(kind) as backend:
            provider = BACKENDS[kind](backend.base_url)
            provider.thinking = thinking
            provider.chat(MESSAGES, **chat_kwargs)
            return backend.bodies(chat_path(kind))[0]

    def test_llama_cpp_maps_each_setting_to_its_native_switch(self):
        self.assertEqual(self.sent("llama_cpp", "off")["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(self.sent("llama_cpp", "on")["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(self.sent("llama_cpp", "budget:200")["reasoning_budget_tokens"], 200)

    def test_auto_keeps_todays_behaviour_and_an_explicit_setting_beats_effort(self):
        auto = self.sent("llama_cpp", "auto", reasoning_effort="high")
        explicit = self.sent("llama_cpp", "off", reasoning_effort="high")

        self.assertEqual(auto["reasoning_effort"], "high")
        self.assertNotIn("chat_template_kwargs", auto)
        self.assertNotIn("reasoning_effort", explicit)

    def test_native_ollama_uses_the_think_boolean(self):
        self.assertIs(self.sent("ollama", "off")["think"], False)
        self.assertIs(self.sent("ollama", "on")["think"], True)
        self.assertIs(self.sent("ollama", "budget:300")["think"], True)
        self.assertNotIn("think", self.sent("ollama", "auto"))

    def test_generic_providers_switch_reasoning_off_with_the_portable_effort_field(self):
        self.assertEqual(self.sent("openai", "off")["reasoning_effort"], "none")
        self.assertEqual(self.sent("openai", "on")["reasoning_effort"], "medium")
        self.assertNotIn("reasoning_effort", self.sent("openai", "auto"))
        self.assertNotIn("think", self.sent("openai", "off"))
        provider = OpenAICompatibleProvider("", "http://x/v1", "m")
        provider.thinking = "budget:100"
        self.assertIn("on or off", provider.thinking_support_problem())

    def test_a_per_request_override_beats_the_configured_setting(self):
        with FakeBackend("openai") as backend:
            provider = OpenAICompatibleProvider("", backend.base_url, "fake")
            provider.thinking = "on"
            provider.chat(MESSAGES, thinking_override="off")
        self.assertEqual(backend.bodies("/v1/chat/completions")[0]["reasoning_effort"], "none")

    def test_limits_of_each_backend_are_reported(self):
        ollama = OllamaProvider("http://x", "m")
        ollama.thinking = "budget:100"
        llama = LlamaCppProvider("", "http://x/v1", "m")
        llama.thinking = "budget:100"

        self.assertIn("on or off", ollama.thinking_support_problem())
        self.assertEqual(llama.thinking_support_problem(), "")

    def test_config_values_are_validated_and_survive_a_round_trip(self):
        for raw, expected in (("off", "off"), ("ON", "on"), ("budget:512", "budget:512"), ("budget:5", "auto"),
                              ("budget:99999", "auto"), ("maybe", "auto"), (None, "auto"), (True, "on"), (False, "off")):
            self.assertEqual(normalize_thinking(raw), expected, raw)
        config = ProviderConfig.from_dict("p", {"type": "llama_cpp", "thinking": "budget:256"})
        self.assertEqual(ProviderConfig.from_dict("p", config.to_dict()).thinking, "budget:256")
        self.assertNotIn("thinking", ProviderConfig.from_dict("p", {"type": "llama_cpp"}).to_dict())

    def test_the_router_applies_the_setting_to_the_built_provider(self):
        from zerocoding.core.config import ConfigManager
        from zerocoding.core.router import build_provider
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.yaml"
            path.write_text("provider: p\nproviders:\n  p:\n    type: llama_cpp\n    base_url: http://x/v1\n"
                            "    model: m\n    thinking: off\n")
            config = ConfigManager(user_config_path=path, env_file=str(Path(tmp) / "none")).load()

        self.assertEqual(build_provider(config).thinking, "off")


if __name__ == "__main__":
    unittest.main()
