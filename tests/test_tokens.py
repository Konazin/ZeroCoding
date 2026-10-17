import unittest
import tempfile

from zerocoding.core.agent import Agent, fit_messages
from zerocoding.core.tokens import MESSAGE_OVERHEAD, TokenCounter, estimate_tokens
from zerocoding.core.tools import ToolRegistry
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

    def test_count_prompt_includes_tools_and_caches_rendered_request(self):
        class ExactProvider:
            def __init__(self):
                self.calls = []

            def count_prompt(self, messages, tools=None):
                self.calls.append((messages, tools))
                return 37

        provider = ExactProvider()
        counter = TokenCounter(provider)
        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "read_file"}}]

        self.assertEqual(counter.count_prompt(messages, tools), 37)
        self.assertEqual(counter.count_prompt(messages, tools), 37)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0], (messages, tools))

    def test_template_counter_failure_falls_back_and_disables_template_path(self):
        class Provider(FakeTokenizer):
            def __init__(self):
                super().__init__()
                self.template_calls = 0

            def count_prompt(self, messages, tools=None):
                self.template_calls += 1
                return None

        provider = Provider()
        counter = TokenCounter(provider)
        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        result = counter.count_prompt(messages, tools)

        self.assertGreater(result, 0)
        self.assertFalse(counter.template_enabled)
        counter.count_prompt(messages, tools)
        self.assertEqual(provider.template_calls, 1)

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

    def test_agent_counts_selected_tool_schemas_with_the_prompt(self):
        class Provider:
            def __init__(self):
                self.counted = []

            def count_prompt(self, messages, tools=None):
                self.counted.append((messages, tools))
                return 100

            def chat(self, messages, **kwargs):
                return ProviderTurn(content="ok")

        provider = Provider()
        with tempfile.TemporaryDirectory() as root:
            agent = Agent(provider, max_input_tokens=256, tools=ToolRegistry(root))
            self.assertEqual(agent.ask("Look at the project", use_tools=True), "ok")

        self.assertEqual(provider.counted[0][1], agent.tools.schemas)


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

    def test_count_prompt_renders_messages_and_tools_before_tokenizing(self):
        provider = self._provider()
        sent = []

        def fake_post(endpoint, payload):
            sent.append((endpoint, payload))
            if endpoint.endswith("/apply-template"):
                return {"prompt": "rendered chat with tools"}
            return {"tokens": [1, 2, 3, 4]}

        provider._post = fake_post
        messages = [{"role": "user", "content": "hello"}]
        tools = [{"type": "function", "function": {"name": "read_file"}}]

        self.assertEqual(provider.count_prompt(messages, tools), 4)
        self.assertEqual(sent[0][0], "http://127.0.0.1:8080/apply-template")
        self.assertEqual(sent[0][1], {
            "messages": messages,
            "add_generation_prompt": True,
            "tools": tools,
        })
        self.assertEqual(sent[1], (
            "http://127.0.0.1:8080/tokenize", {"content": "rendered chat with tools"}
        ))

    def test_render_prompt_returns_none_for_unexpected_server_response(self):
        provider = self._provider()
        provider._post = lambda endpoint, payload: {"error": "unsupported endpoint"}
        self.assertIsNone(provider.render_prompt([{"role": "user", "content": "hello"}]))


class TestPromptBudgetProtocol(unittest.TestCase):
    def test_omits_short_tool_output_without_breaking_the_tool_result_pair(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-one", "type": "function", "function": {"name": "read_file", "arguments": {}}},
            ]},
            {"role": "tool", "tool_call_id": "call-one", "name": "read_file", "content": "x"},
        ]

        fitted = fit_messages(messages, 1, count=lambda items: sum(len(str(item.get("content", ""))) for item in items))

        self.assertEqual(len(fitted), 3)
        self.assertEqual(fitted[-1]["tool_call_id"], "call-one")
        self.assertEqual(fitted[-1]["content"], "")

    def test_trims_old_turns_but_keeps_current_tool_call_and_all_matching_results(self):
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "old question " * 500},
            {"role": "assistant", "content": "old answer " * 500},
            {"role": "user", "content": "Keep this request intact."},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-one", "type": "function", "function": {"name": "read_file", "arguments": {}}},
                {"id": "call-two", "type": "function", "function": {"name": "search_files", "arguments": {}}},
            ]},
            {"role": "tool", "tool_call_id": "call-one", "name": "read_file", "content": "alpha " * 1200},
            {"role": "tool", "tool_call_id": "call-two", "name": "search_files", "content": "beta " * 1200},
        ]
        schemas = [{"type": "function", "function": {"name": "read_file"}}]

        fitted = fit_messages(messages, 500, tools=schemas)

        self.assertNotIn("old question", str(fitted))
        self.assertEqual(fitted[1]["content"], "Keep this request intact.")
        assistant = next(message for message in fitted if message.get("tool_calls"))
        calls = {call["id"] for call in assistant["tool_calls"]}
        results = {message["tool_call_id"] for message in fitted if message.get("role") == "tool"}
        self.assertEqual(calls, results)
        self.assertEqual(calls, {"call-one", "call-two"})
        self.assertTrue(all("truncated to fit context" in message["content"] for message in fitted if message.get("role") == "tool"))

    def test_raises_instead_of_truncating_an_oversized_current_request(self):
        from zerocoding.core.budget import PromptTooLargeError

        messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "do not cut me " * 100}]
        original = [dict(message) for message in messages]

        with self.assertRaises(PromptTooLargeError):
            fit_messages(messages, 10)

        self.assertEqual(messages, original)


if __name__ == "__main__":
    unittest.main()


class TestHistoryDigest(unittest.TestCase):
    @staticmethod
    def _chars(items):
        return sum(len(str(item.get("content", ""))) for item in items)

    def _messages(self):
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old question about parser.py " + "x" * 200},
            {"role": "assistant", "content": "old answer: fixed parser.py"},
            {"role": "user", "content": "current request"},
        ]

    def test_dropped_turns_leave_a_short_digest_in_the_system_message(self):
        fitted = fit_messages(self._messages(), 260, count=self._chars)

        self.assertEqual([m["role"] for m in fitted], ["system", "user"])
        self.assertIn("Earlier turns", fitted[0]["content"])
        self.assertIn("parser.py", fitted[0]["content"])
        self.assertLessEqual(self._chars(fitted), 260)

    def test_digest_is_omitted_when_it_does_not_fit(self):
        fitted = fit_messages(self._messages(), 30, count=self._chars)

        self.assertEqual(fitted[0]["content"], "sys")

    def test_no_digest_when_nothing_was_dropped(self):
        fitted = fit_messages(self._messages(), 10_000, count=self._chars)

        self.assertEqual(len(fitted), 4)
        self.assertEqual(fitted[0]["content"], "sys")
