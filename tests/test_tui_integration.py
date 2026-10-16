import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import fcntl
import termios
from pathlib import Path

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from zerocoding.core.agent import Agent
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn, ToolCall
from zerocoding.tui.app import ZerocodingTUI


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = iter(turns)

    def chat(self, messages, **kwargs):
        return next(self.turns)


class TestTuiApprovalFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "created.txt"
        self.tui = ZerocodingTUI(provider_name="fake", model="scripted", theme="purple", mode="code",
                                 session_id="test", connection_status="offline", skills=[])

    def run_tool_write(self, key):
        provider = ScriptedProvider([
            ProviderTurn(tool_calls=[ToolCall("write_file", {"path": "created.txt", "content": "approved\n"}, "w1")]),
            ProviderTurn(content="Finished."),
        ])
        agent = Agent(provider, tools=ToolRegistry(self.root, approve=self.tui.confirm_action))
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe, output=DummyOutput()):
                pipe.send_text(key)
                answer = agent.ask("create the file", use_tools=True)
        return answer

    def test_approval_key_from_tui_applies_write_in_agent_flow(self):
        self.assertEqual(self.run_tool_write("Y"), "Finished.")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "approved\n")

    def test_rejection_from_tui_preserves_file_in_agent_flow(self):
        self.assertEqual(self.run_tool_write("n"), "Finished.")
        self.assertFalse(self.target.exists())

    def test_escape_enter_text_and_ctrl_c_never_approve_agent_write(self):
        for key in ("\x1b", "\r", "/exit\r", "anything\r", "\x03"):
            with self.subTest(key=key):
                self.target.unlink(missing_ok=True)
                self.assertEqual(self.run_tool_write(key), "Finished.")
                self.assertFalse(self.target.exists())

    def test_ctrl_c_during_provider_turn_leaves_history_unchanged(self):
        class InterruptingProvider:
            def chat(self, messages, **kwargs):
                raise KeyboardInterrupt

        agent = Agent(InterruptingProvider(), tools=ToolRegistry(self.root, approve=self.tui.confirm_action))
        agent.context.add_message("user", "previous request")
        before = list(agent.context.history)

        with self.assertRaises(KeyboardInterrupt):
            agent.ask("new request", use_tools=True)

        self.assertEqual(agent.context.history, before)


class TestTuiInputPrompt(unittest.TestCase):
    def test_prompt_toolkit_reads_slash_command_and_ctrl_c_cancels_input(self):
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe, output=DummyOutput()):
                tui = ZerocodingTUI(provider_name="fake", model="scripted", theme="purple", mode="code",
                                    session_id="test", connection_status="offline", skills=[])
                pipe.send_text("/status\r")
                self.assertEqual(tui.input_prompt(), "/status")
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe, output=DummyOutput()):
                tui = ZerocodingTUI(provider_name="fake", model="scripted", theme="purple", mode="code",
                                    session_id="test", connection_status="offline", skills=[])
                pipe.send_text("\x03")
                self.assertEqual(tui.input_prompt(), "")

    @unittest.skipUnless(os.name == "posix", "PTY smoke test requires a POSIX terminal")
    def test_pty_reads_command_through_real_terminal(self):
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
        script = (
            "from zerocoding.tui.app import ZerocodingTUI; "
            "t=ZerocodingTUI(provider_name='fake', model='scripted', theme='purple', mode='code', "
            "session_id='pty', connection_status='offline', skills=[]); "
            "print('RESULT:'+t.input_prompt(), flush=True)"
        )
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        process = subprocess.Popen([sys.executable, "-c", script], stdin=slave, stdout=slave, stderr=slave,
                                   cwd=repo, env=env, close_fds=True)
        os.close(slave)
        output = bytearray()
        sent = False
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and process.poll() is None:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        output.extend(os.read(master, 4096))
                    except OSError:
                        break
                if not sent and "›".encode() in output:
                    os.write(master, b"/exit\r")
                    sent = True
            if process.poll() is None:
                process.kill()
                self.fail(f"PTY prompt did not finish within 8 seconds (sent={sent}): {output.decode(errors='replace')[-1000:]}")
            while True:
                try:
                    ready, _, _ = select.select([master], [], [], 0)
                    if not ready:
                        break
                    output.extend(os.read(master, 4096))
                except OSError:
                    break
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        self.assertEqual(process.returncode, 0, output.decode(errors="replace"))
        self.assertIn(b"RESULT:/exit", output)

    @unittest.skipUnless(os.name == "posix", "PTY approval flow requires a POSIX terminal")
    def test_pty_drives_prompt_provider_and_approved_write_end_to_end(self):
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
        script = (
            "from pathlib import Path; import os; "
            "from zerocoding.core.agent import Agent; "
            "from zerocoding.core.tools import ToolRegistry; "
            "from zerocoding.providers.base import ProviderTurn, ToolCall; "
            "from zerocoding.tui.app import ZerocodingTUI; "
            "class_provider = type('Provider', (), {'__init__': lambda self: setattr(self, 'turns', iter(["
            "ProviderTurn(tool_calls=[ToolCall('write_file', {'path':'created.txt','content':'approved\\n'}, 'w1')]),"
            "ProviderTurn(content='Finished.')])) , 'chat': lambda self, messages, **kwargs: next(self.turns)}) ; "
            "root=Path(os.environ['ZC_TEST_ROOT']); "
            "t=ZerocodingTUI(provider_name='fake', model='scripted', theme='purple', mode='code', session_id='pty', skills=[]); "
            "a=Agent(class_provider(), tools=ToolRegistry(root, approve=t.confirm_action)); "
            "prompt=t.input_prompt(); "
            "response=a.ask(prompt, use_tools=True); print('DONE:'+response, flush=True)"
        )
        self._test_temp = tempfile.TemporaryDirectory()
        self._test_root = Path(self._test_temp.name)
        self.addCleanup(self._test_temp.cleanup)
        env["ZC_TEST_ROOT"] = str(self._test_root)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        process = subprocess.Popen([sys.executable, "-c", script], stdin=slave, stdout=slave, stderr=slave,
                                   cwd=repo, env=env, close_fds=True)
        os.close(slave)
        output = bytearray()
        sent_prompt = sent_approval = False
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and process.poll() is None:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        output.extend(os.read(master, 4096))
                    except OSError:
                        break
                if not sent_prompt and "›".encode() in output:
                    os.write(master, b"create the file\r")
                    sent_prompt = True
                if sent_prompt and not sent_approval and b"Approve?" in output:
                    os.write(master, b"Y")
                    sent_approval = True
            if process.poll() is None:
                process.kill()
                self.fail(f"PTY approval flow timed out: {output.decode(errors='replace')[-1000:]}")
            while True:
                try:
                    ready, _, _ = select.select([master], [], [], 0)
                    if not ready:
                        break
                    output.extend(os.read(master, 4096))
                except OSError:
                    break
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        self.assertEqual(process.returncode, 0, output.decode(errors="replace"))
        self.assertTrue(sent_prompt)
        self.assertTrue(sent_approval)
        self.assertIn(b"DONE:Finished.", output)
        self.assertEqual((self._test_root / "created.txt").read_text(encoding="utf-8"), "approved\n")


if __name__ == "__main__":
    unittest.main()
