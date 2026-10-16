import json
import tempfile
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.cancel import CancelToken, TurnCancelled
from zerocoding.core.metrics import MetricsLog, summarize
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn, ToolCall


class Scripted:
    def __init__(self, turns, on_chat=None):
        self.turns = list(turns)
        self.on_chat = on_chat
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.on_chat:
            self.on_chat(self.calls)
        return self.turns.pop(0)


def usage(prompt, completion):
    return {"prompt_tokens": prompt, "completion_tokens": completion}


class TestCancellation(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        (self.root / "a.txt").write_text("hello\n", encoding="utf-8")

    def test_token_cancelled_between_rounds_leaves_history_untouched(self):
        token = CancelToken()
        provider = Scripted(
            [ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "a.txt"}, "1")]),
             ProviderTurn(content="never reached")],
            on_chat=lambda n: token.cancel() if n == 1 else None,
        )
        agent = Agent(provider, tools=ToolRegistry(self.root))
        with self.assertRaises(TurnCancelled):
            agent.ask("read it", use_tools=True, cancel=token)
        self.assertEqual(agent.context.history, [])
        self.assertEqual(provider.calls, 1)  # the second provider call never happened
        self.assertEqual(agent.last_turn["outcome"], "cancelled")

    def test_cancel_before_a_tool_runs_does_not_execute_it(self):
        token = CancelToken()
        approvals = []
        provider = Scripted(
            [ProviderTurn(tool_calls=[ToolCall("write_file", {"path": "n.txt", "content": "x"}, "1")])],
            on_chat=lambda n: token.cancel(),
        )
        agent = Agent(provider, tools=ToolRegistry(self.root, approve=lambda a, p: approvals.append(a) or True))
        with self.assertRaises(TurnCancelled):
            agent.ask("write", use_tools=True, cancel=token)
        self.assertEqual(approvals, [])
        self.assertFalse((self.root / "n.txt").exists())

    def test_keyboard_interrupt_is_recorded_and_history_untouched(self):
        class Interrupting:
            def chat(self, messages, **kwargs):
                raise KeyboardInterrupt

        agent = Agent(Interrupting())
        with self.assertRaises(KeyboardInterrupt):
            agent.ask("hi")
        self.assertEqual(agent.context.history, [])
        self.assertEqual(agent.last_turn["outcome"], "cancelled")


class TestMetrics(unittest.TestCase):
    def test_turn_stats_count_tokens_tools_and_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_text("hello\n", encoding="utf-8")
            provider = Scripted([
                ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "a.txt"}, "1"),
                                         ToolCall("read_file", {"path": "missing.txt"}, "2")], usage=usage(100, 10)),
                ProviderTurn(content="done", usage=usage(150, 20)),
            ])
            rows = []
            agent = Agent(provider, tools=ToolRegistry(root))
            agent.metrics_sink = rows.append
            agent.ask("read", use_tools=True)
        self.assertEqual(len(rows), 1)
        stats = rows[0]
        self.assertEqual((stats["outcome"], stats["llm_calls"]), ("ok", 2))
        self.assertEqual((stats["prompt_tokens"], stats["completion_tokens"]), (250, 30))
        self.assertEqual((stats["tool_calls"], stats["tool_errors"]), (2, 1))
        self.assertNotIn("read", json.dumps(stats).replace("read_file", ""))  # no prompt text in metrics

    def test_failed_turn_is_recorded_as_error(self):
        class Broken:
            def chat(self, messages, **kwargs):
                raise RuntimeError("down")

        rows = []
        agent = Agent(Broken())
        agent.metrics_sink = rows.append
        with self.assertRaises(RuntimeError):
            agent.ask("hi")
        self.assertEqual(rows[0]["outcome"], "error")

    def test_trimmed_history_is_counted(self):
        provider = Scripted([ProviderTurn(content="ok")])
        agent = Agent(provider, max_input_tokens=256)
        for i in range(30):
            agent.context.add_message("user", f"old question {i} " + "x" * 200)
            agent.context.add_message("assistant", f"old answer {i} " + "y" * 200)
        agent.ask("current")
        self.assertGreater(agent.last_turn["trimmed_messages"], 0)

    def test_log_roundtrip_summary_and_resilience(self):
        with tempfile.TemporaryDirectory() as directory:
            log = MetricsLog(Path(directory, "m", "turns.jsonl"))
            self.assertEqual(summarize(log.recent()), {"turns": 0})
            log.record({"outcome": "ok", "duration_s": 2.0, "prompt_tokens": 100, "tool_calls": 2, "tool_errors": 1, "trimmed_messages": 0})
            log.record({"outcome": "cancelled", "duration_s": 6.0, "prompt_tokens": 300, "tool_calls": 0, "tool_errors": 0, "trimmed_messages": 4})
            with log.path.open("a") as handle:
                handle.write("not json\n")
            summary = summarize(log.recent())
        self.assertEqual(summary["turns"], 2)
        self.assertEqual(summary["outcomes"], {"ok": 1, "cancelled": 1})
        self.assertEqual(summary["duration_s"], {"median": 4.0, "worst": 6.0})
        self.assertEqual(summary["tool_error_rate"], 0.5)
        self.assertEqual(summary["trimmed_turn_rate"], 0.5)

    def test_unwritable_log_does_not_break_a_turn(self):
        log = MetricsLog("/proc/zc-nope/turns.jsonl")
        agent = Agent(Scripted([ProviderTurn(content="ok")]))
        agent.metrics_sink = log.record
        self.assertEqual(agent.ask("hi"), "ok")


if __name__ == "__main__":
    unittest.main()
