import json
import unittest
from unittest.mock import patch

from zerocoding.core.agent import Agent
from zerocoding.core.cancel import CancelToken, TurnCancelled
from zerocoding.providers.base import ProviderTurn, ToolCall
from zerocoding.providers.openai_compatible import OpenAICompatibleProvider
from zerocoding.core.events import AgentEvent
from zerocoding.tui.app import ZerocodingTUI


class FakeSseResponse:
    def __init__(self, events):
        self.lines = [b"data: " + json.dumps(event).encode() + b"\n\n" for event in events]
        self.lines.append(b"data: [DONE]\n\n")
        self.closed = False

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.closed = True


class TestOpenAICompatibleStreaming(unittest.TestCase):
    def test_stream_assembles_text_tools_and_reasoning_without_exposing_reasoning(self):
        response = FakeSseResponse([
            {"choices": [{"delta": {"reasoning_content": "private "}}]},
            {"choices": [{"delta": {"content": "Read "}}]},
            {"choices": [{"delta": {"content": "the file."}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call-1", "function": {"name": "read_", "arguments": "{\"path\":"}},
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"name": "file", "arguments": "\"a.py\"}"}},
            ]}}]},
        ])
        provider = OpenAICompatibleProvider("", "http://localhost:8080/v1", "fake")
        sent = {}
        emitted = []

        def fake_urlopen(request, timeout):
            sent["request"] = request
            sent["timeout"] = timeout
            return response

        with patch("zerocoding.providers.openai_compatible.urllib.request.urlopen", fake_urlopen):
            turn = provider.chat_stream_turn(
                [{"role": "user", "content": "read"}],
                tools=[{"type": "function", "function": {"name": "read_file"}}],
                max_tokens=128,
                on_delta=emitted.append,
            )

        payload = json.loads(sent["request"].data)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["max_tokens"], 128)
        self.assertEqual(emitted, ["Read ", "the file."])
        self.assertEqual(turn.content, "Read the file.")
        self.assertTrue(turn.thinking_present)
        self.assertEqual(turn.reasoning_content, "private ")
        self.assertEqual(turn.tool_calls, [ToolCall("read_file", {"path": "a.py"}, "call-1")])
        self.assertTrue(response.closed)

    def test_inline_thinking_tags_split_across_stream_chunks_are_never_emitted(self):
        response = FakeSseResponse([
            {"choices": [{"delta": {"content": "Public <thi"}}]},
            {"choices": [{"delta": {"content": "nk>private plan</think> answer"}}]},
        ])
        provider = OpenAICompatibleProvider("", "http://localhost:8080/v1", "fake")
        emitted = []
        with patch("zerocoding.providers.openai_compatible.urllib.request.urlopen", return_value=response):
            turn = provider.chat_stream_turn([], on_delta=emitted.append)

        self.assertEqual("".join(emitted), "Public  answer")
        self.assertEqual(turn.content, "Public  answer")
        self.assertEqual(turn.reasoning_content, "private plan")

    def test_non_streaming_response_also_removes_inline_thinking(self):
        provider = OpenAICompatibleProvider("", "http://localhost:8080/v1", "fake")
        provider._post = lambda endpoint, payload: {"choices": [{"message": {
            "content": "Public <think>private plan</think> answer",
        }}]}

        turn = provider.chat([])

        self.assertEqual(turn.content, "Public  answer")
        self.assertEqual(turn.reasoning_content, "private plan")

    def test_cancel_closes_stream_response(self):
        cancel = CancelToken()

        class CancellingResponse(FakeSseResponse):
            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                cancel.cancel()
                yield b'data: {"choices":[{"delta":{"content":"second"}}]}\n\n'

        response = CancellingResponse([])
        provider = OpenAICompatibleProvider("", "http://localhost:8080/v1", "fake")
        emitted = []

        with patch("zerocoding.providers.openai_compatible.urllib.request.urlopen", return_value=response):
            with self.assertRaises(TurnCancelled):
                provider.chat_stream_turn([], cancel=cancel, on_delta=emitted.append)

        self.assertTrue(response.closed)
        self.assertEqual(emitted, ["first"])


class StreamingAgentProvider:
    def __init__(self, failure=None):
        self.failure = failure
        self.stream_calls = 0
        self.chat_calls = 0

    def chat_stream_turn(self, messages, on_delta=None, **kwargs):
        self.stream_calls += 1
        if self.failure:
            on_delta("partial answer")
            raise RuntimeError("stream interrupted")
        on_delta("Visible answer.")
        return ProviderTurn(content="Visible answer.", reasoning_content="private thought")

    def chat(self, messages, **kwargs):
        self.chat_calls += 1
        return ProviderTurn(content="Recovered answer.")


class TestAgentStreaming(unittest.TestCase):
    def test_streams_only_public_content_and_records_ttft(self):
        provider = StreamingAgentProvider()
        agent = Agent(provider, streaming_enabled=True)
        events = []

        answer = agent.ask("question", on_event=events.append)

        self.assertEqual(answer, "Visible answer.")
        self.assertEqual([event.summary for event in events if event.kind == "response_delta"], ["Visible answer."])
        self.assertIn("response_end", [event.kind for event in events])
        self.assertNotIn("private thought", str(events))
        self.assertNotIn("private thought", str(agent.context.history))
        self.assertIsInstance(agent.last_turn["ttft_ms"], float)
        self.assertEqual(provider.chat_calls, 0)

    def test_stream_failure_resets_partial_text_then_falls_back_once(self):
        provider = StreamingAgentProvider(failure=True)
        agent = Agent(provider, streaming_enabled=True)
        events = []

        answer = agent.ask("question", on_event=events.append)

        kinds = [event.kind for event in events]
        self.assertEqual(answer, "Recovered answer.")
        self.assertIn("response_delta", kinds)
        self.assertIn("response_reset", kinds)
        self.assertEqual(provider.chat_calls, 1)

    def test_cancellation_resets_partial_output_and_does_not_save_turn(self):
        class CancellingProvider(StreamingAgentProvider):
            def chat_stream_turn(self, messages, on_delta=None, **kwargs):
                on_delta("partial")
                raise TurnCancelled("Turn cancelled.")

        provider = CancellingProvider()
        agent = Agent(provider, streaming_enabled=True)
        agent.context.add_message("assistant", "prior answer")
        before = list(agent.context.history)
        events = []

        with self.assertRaises(TurnCancelled):
            agent.ask("question", on_event=events.append)

        self.assertIn("response_reset", [event.kind for event in events])
        self.assertEqual(agent.context.history, before)


class TestTuiStreaming(unittest.TestCase):
    def test_renders_public_deltas_and_clears_temporary_output_at_end(self):
        instances = []

        class FakeLive:
            def __init__(self, renderable, **kwargs):
                self.renderable = renderable
                self.updates = []
                self.stopped = False
                instances.append(self)

            def start(self):
                return None

            def update(self, renderable, refresh=False):
                self.updates.append(renderable.plain)

            def stop(self):
                self.stopped = True

        tui = ZerocodingTUI(provider_name="fake", model="stream", theme="purple", mode="code")
        with patch("zerocoding.tui.app.Live", FakeLive):
            tui.handle_agent_event(AgentEvent("response_delta", summary="public "))
            tui.handle_agent_event(AgentEvent("response_delta", summary="answer"))
            self.assertIsNotNone(tui._response_live)
            tui.handle_agent_event(AgentEvent("response_end"))

        self.assertTrue(instances[0].stopped)
        self.assertEqual(instances[0].updates[-1], "• public answer")
        self.assertIsNone(tui._response_live)


if __name__ == "__main__":
    unittest.main()
