import json
import os
import pty
import select
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.text import Text

from zerocoding.tui.diffview import DiffView, looks_like_diff, parse_diff, summarize
from zerocoding.tui.fullscreen import ApprovalScreen, FullscreenAnimation, FullscreenTUI, TranscriptConsole

DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n def double(value):\n-    return value * 3\n+    return value * 2\n \n"


def plain(lines):
    return ["".join(fragment[1] for fragment in line) for line in lines]


class TestDiffView(unittest.TestCase):
    def test_parse_gives_path_numbers_and_summary(self):
        path, lines = parse_diff(DIFF)
        self.assertEqual(path, "calc.py")
        self.assertEqual([(line.kind, line.number) for line in lines], [("ctx", 1), ("del", 2), ("add", 2), ("ctx", 3)])
        self.assertEqual(summarize(lines), "Added 1 line, removed 1 line")

    def test_new_file_diff_has_no_dev_null_path_and_counts_added_lines(self):
        diff = "--- /dev/null\n+++ b/hello.py\n@@ -0,0 +1,2 @@\n+def hello():\n+    pass\n"
        path, lines = parse_diff(diff)
        self.assertEqual(path, "hello.py")
        self.assertEqual(summarize(lines), "Added 2 lines")

    def test_looks_like_diff_only_for_unified_diffs(self):
        self.assertTrue(looks_like_diff(DIFF))
        self.assertFalse(looks_like_diff("python -m unittest"))

    def test_rows_are_padded_to_the_width_and_colored(self):
        from rich.console import Console
        console = Console(width=40, force_terminal=True, color_system="truecolor", record=True)
        console.print(DiffView(DIFF))
        out = console.export_text(styles=True)
        self.assertIn("48;2;18;48;31", out)   # added row background
        self.assertIn("48;2;58;22;32", out)   # removed row background


class TestTranscriptConsole(unittest.TestCase):
    def test_renders_at_the_requested_width_and_joins_end_without_newline(self):
        console = TranscriptConsole(lambda: None)
        console.print(Text("• "), end="")
        console.print(Text("word " * 12))
        wide, narrow = plain(console.render_lines(80)), plain(console.render_lines(20))
        self.assertEqual(len(wide), 1)
        self.assertTrue(wide[0].startswith("• word"))
        self.assertGreater(len(narrow), 2)

    def test_new_prints_invalidate_the_cache_and_clear_empties_it(self):
        changes = []
        console = TranscriptConsole(lambda: changes.append(1))
        console.print(Text("a"))
        self.assertEqual(plain(console.render_lines(30)), ["a"])
        console.print(Text("b"))
        self.assertEqual(plain(console.render_lines(30)), ["a", "b"])
        console.clear()
        self.assertEqual(console.render_lines(30), [])
        self.assertEqual(len(changes), 3)


class TestApprovalScreen(unittest.TestCase):
    def test_only_y_approves_enter_n_and_escape_refuse_other_keys_do_nothing(self):
        for key in ("char:y", "char:Y"):
            self.assertIs(ApprovalScreen("Edit file", DIFF).key(key).value, True)
        for key in ("char:n", "char:N", "escape", "enter"):
            self.assertIs(ApprovalScreen("Edit file", DIFF).key(key).value, False)
        for key in ("char:x", "down", "tab"):
            self.assertIsNone(ApprovalScreen("Edit file", DIFF).key(key))

    def test_diff_and_command_panels(self):
        diff_text = "".join(fragment[1] for fragment in ApprovalScreen("Edit file", DIFF).fragments(60))
        self.assertIn("calc.py", diff_text)
        self.assertIn("Added 1 line, removed 1 line", diff_text)
        command_text = "".join(fragment[1] for fragment in ApprovalScreen("Run command", "python -m unittest").fragments(60))
        self.assertIn("$ python -m unittest", command_text)


class FullscreenCase(unittest.TestCase):
    def setUp(self):
        pipe_context = create_pipe_input()
        pipe = pipe_context.__enter__()
        self.addCleanup(pipe_context.__exit__, None, None, None)
        session = create_app_session(input=pipe, output=DummyOutput())
        session.__enter__()
        self.addCleanup(session.__exit__, None, None, None)
        self.tui = FullscreenTUI(provider_name="p", model="m", theme="purple", mode="code", session_id="s", skills=[])
        self.tui._size = lambda: (40, 12)  # transcript viewport is 6 rows


class TestFullscreenBehavior(FullscreenCase):
    def visible(self):
        return "".join(fragment[1] for fragment in self.tui._transcript_fragments()).split("\n")

    def fill(self, count):
        for index in range(count):
            self.tui.console.print(Text(f"line {index}"))

    def test_follows_the_bottom_and_scrolls_with_clamping(self):
        self.fill(20)
        self.assertEqual(self.visible()[-1], "line 19")
        self.tui.scroll(4)
        self.assertEqual(self.visible()[-1], "line 15")
        self.tui.scroll(100)
        self.visible()
        self.assertEqual(self.visible()[0], "line 0")
        self.tui.scroll(-1000)
        self.assertEqual(self.visible()[-1], "line 19")

    def test_new_output_does_not_move_a_scrolled_view(self):
        self.fill(20)
        self.tui.scroll(5)
        before = self.visible()
        self.fill(3)
        self.assertEqual(self.visible(), before)

    def test_input_is_kept_but_not_sent_while_busy(self):
        self.tui._buffer.text = "next question"
        FullscreenAnimation(self.tui, "Working").start()
        self.assertFalse(self.tui.submit_input())
        self.assertEqual(self.tui._buffer.text, "next question")
        self.assertTrue(self.tui._inbox.empty())
        self.assertIn("Still working", self.tui._flash[0])
        self.tui._activity = None
        self.assertTrue(self.tui.submit_input())
        self.assertEqual(self.tui.input_prompt(), "next question")
        self.assertEqual(self.tui._buffer.text, "")

    def test_modal_screens_block_the_worker_until_a_key_decides(self):
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(self.tui.confirm_action("Edit file", DIFF)))
        worker.start()
        for _ in range(100):
            if self.tui._modal is not None:
                break
            time.sleep(0.01)
        self.tui._feed_modal("char:x")      # ignored
        self.assertTrue(worker.is_alive())
        self.tui._feed_modal("char:y")
        worker.join(2)
        self.assertEqual(outcome, [True])
        text = "\n".join(plain(self.tui.console.render_lines(60)))
        self.assertIn("Added 1 line, removed 1 line", text)
        self.assertIn("return value * 2", text)

    def test_rejection_keeps_the_diff_out_of_the_transcript(self):
        worker = threading.Thread(target=lambda: self.tui.confirm_action("Edit file", DIFF))
        worker.start()
        for _ in range(100):
            if self.tui._modal is not None:
                break
            time.sleep(0.01)
        self.tui._feed_modal("enter")
        worker.join(2)
        text = "\n".join(plain(self.tui.console.render_lines(60)))
        self.assertIn("Rejected edit file", text)
        self.assertNotIn("return value * 2", text)

    def test_buddy_animation_changes_the_header_mascot_in_place(self):
        self.tui.header()
        seen = []
        original = self.tui._invalidate
        self.tui._invalidate = lambda: (seen.append(self.tui._pose), original())
        with patch("zerocoding.tui.fullscreen.time.sleep"):
            self.tui.play_buddy("dance")
        self.assertIn("dance_a", seen)
        self.assertEqual(self.tui._pose, "idle")
        self.assertTrue(self.tui._header_lines(40))

    def test_streamed_text_is_a_tail_block_and_preamble_is_kept(self):
        class Event:
            def __init__(self, summary=""):
                self.summary = summary
        self.tui._handle_response_event("response_delta", Event("I will read"), None)
        self.assertIn("• I will read", "\n".join(plain(self.tui._all_lines(40))))
        self.tui._handle_response_event("response_end", Event("before_tools"), None)
        self.assertEqual(self.tui._stream_text, "")
        self.assertIn("• I will read", "\n".join(plain(self.tui.console.render_lines(40))))


class FakeLLM(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "fake-model"}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        time.sleep(0.6)
        has_tool_result = any(m.get("role") == "tool" for m in request["messages"])
        if has_tool_result:
            message = {"role": "assistant", "content": "All done."}
        else:
            call = {"id": "c1", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": "hello.py", "content": "def hello():\n    pass\n"})}}
            message = {"role": "assistant", "content": "", "tool_calls": [call]}
        body = json.dumps({"choices": [{"message": message}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class TestFullscreenEndToEnd(unittest.TestCase):
    def test_real_terminal_session_keeps_input_during_work_and_applies_an_approved_write(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".zerocoding").mkdir()
            (Path(home) / ".zerocoding" / "config.yaml").write_text(
                "provider: fake\nstreaming_enabled: false\nproviders:\n  fake:\n    type: openai_compatible\n"
                f"    base_url: http://127.0.0.1:{server.server_port}/v1\n    model: fake-model\n"
                "modes:\n  code:\n    provider: fake\n    model: fake-model\n    skills: []\n", encoding="utf-8")
            root = Path(__file__).resolve().parents[1]
            pid, fd = pty.fork()
            if pid == 0:
                os.chdir(home)
                env = dict(os.environ, TERM="xterm-256color", HOME=home, PYTHONPATH=str(root / "src"))
                import sys
                os.execve(sys.executable, [sys.executable, "-m", "zerocoding.cli"], env)
            output = b""

            def pump(seconds, until=None):
                nonlocal output
                end = time.time() + seconds
                while time.time() < end:
                    if select.select([fd], [], [], 0.05)[0]:
                        try:
                            data = os.read(fd, 65536)
                        except OSError:
                            return
                        if b"\x1b[6n" in data:
                            os.write(fd, b"\x1b[1;1R")
                        output += data
                        if until and until in output:
                            return

            try:
                pump(3, b"Effort")
                os.write(fd, b"write a hello file\r")
                pump(1.2, b"Cogitating")  # model is still thinking
                os.write(fd, b"draft typed while working")
                pump(0.3)
                os.write(fd, b"\r")       # must not send while busy
                pump(8, b"requires approval")
                self.assertIn(b"requires approval", output)
                self.assertIn(b"Added 2 lines", output)
                self.assertIn(b"Still working", output)   # Enter during work did not send the draft
                os.write(fd, b"y")
                target = Path(home) / "hello.py"
                deadline = time.time() + 8
                while not target.exists() and time.time() < deadline:
                    pump(0.2)
                self.assertEqual(target.read_text(), "def hello():\n    pass\n")
                pump(2)
                os.write(fd, b"\x03/exit\r")
                pump(3, b"session ended")
            finally:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
                os.waitpid(pid, 0)


if __name__ == "__main__":
    unittest.main()
