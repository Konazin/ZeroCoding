import unittest

try:
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    HAS_PT = True
except ImportError:  # pragma: no cover
    HAS_PT = False

from zerocoding.tui.app import ZerocodingTUI


@unittest.skipUnless(HAS_PT, "prompt_toolkit not installed")
class TestConfirmAction(unittest.TestCase):
    """Regression: invalid key names ('s-y') made every approval raise, so writes/commands could never be approved."""

    def ask(self, keys: str):
        tui = ZerocodingTUI(provider_name="p", model="m", theme="purple", mode="code",
                            session_id="s", connection_status="unknown", skills=[])
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe, output=DummyOutput()):
                pipe.send_text(keys)
                return tui.confirm_action("Edit file", "--- a\n+++ b\n-x\n+y")

    def test_y_and_uppercase_y_approve(self):
        self.assertTrue(self.ask("y"))
        self.assertTrue(self.ask("Y"))

    def test_n_uppercase_n_and_escape_refuse(self):
        self.assertFalse(self.ask("n"))
        self.assertFalse(self.ask("N"))
        self.assertFalse(self.ask("\x1b"))

    def test_enter_or_arbitrary_text_refuses_by_default(self):
        """Regression: bool(text) approved any typed text, e.g. a following '/exit' command."""
        self.assertFalse(self.ask("\r"))
        self.assertFalse(self.ask("/exit\r"))
        self.assertFalse(self.ask("ok sure\r"))


if __name__ == "__main__":
    unittest.main()
