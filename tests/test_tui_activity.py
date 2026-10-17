import unittest
from unittest.mock import patch

from zerocoding.tui import app
from zerocoding.tui.app import ZerocodingTUI
from zerocoding.tui.mascot import ANIMATIONS, POSE_HOLES, render


class TestActivityLine(unittest.TestCase):
    def setUp(self):
        self.tui = ZerocodingTUI(provider_name="x", model="m", theme="purple", mode="code")

    def test_status_row_has_effort_right_and_pet_in_the_middle(self):
        with patch.object(app.TerminalSize, "get_width", staticmethod(lambda: 80)):
            row = self.tui._status_row("[• •]")
        self.assertEqual(len(row), 80)
        self.assertTrue(row.endswith("Effort: Medium"))
        self.assertEqual(row.index("[• •]"), (80 - 5) // 2)

    def test_pet_is_dropped_instead_of_colliding_on_narrow_terminals(self):
        with patch.object(app.TerminalSize, "get_width", staticmethod(lambda: 24)):
            row = self.tui._status_row("╹[• •]╹")
        self.assertNotIn("[• •]", row)
        self.assertTrue(row.endswith("Effort: Medium"))

    def test_pet_fragment_is_clickable_and_a_click_plays_work_first(self):
        from prompt_toolkit.mouse_events import MouseEvent, MouseEventType, MouseButton, MouseModifier
        with patch.object(app.TerminalSize, "get_width", staticmethod(lambda: 80)):
            fragments = self.tui._bottom_toolbar()
        pet = [f for f in fragments if len(f) == 3]
        self.assertEqual(len(pet), 1)
        self.assertEqual(pet[0][1], "[• •]")
        played = []
        self.tui.play_buddy = lambda name=None: played.append(name) or (name or "dance")
        self.tui.click_buddy()
        self.tui.click_buddy()
        self.assertEqual(played, ["work", None])
        down = MouseEvent(app.Point(0, 0) if hasattr(app, "Point") else None, MouseEventType.MOUSE_DOWN, MouseButton.LEFT, frozenset())
        self.assertIsNone(self.tui._on_pet_mouse(down))  # only MOUSE_UP triggers

    def test_done_line_shows_elapsed_and_clock_time(self):
        lines = []
        self.tui.console.print = lambda text, **kw: lines.append(text.plain)
        self.tui.show_done(12.4)
        self.assertRegex(lines[0], r"^[✻*] Worked for 12s · \d\d:\d\d$")

    def test_every_animation_pose_exists_and_renders_five_rows(self):
        for name, (poses, delay) in ANIMATIONS.items():
            self.assertGreater(delay, 0)
            for pose in poses:
                self.assertIn(pose, POSE_HOLES if not pose.startswith("work_") else {*POSE_HOLES, pose})
                self.assertEqual(len(render(pose)), 5, f"{name}:{pose}")


if __name__ == "__main__":
    unittest.main()
