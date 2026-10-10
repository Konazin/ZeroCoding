import base64
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zerocoding.tui._mascot_sprites import MASCOT_PNG_FRAMES
from zerocoding.tui.app import ZerocodingTUI
from zerocoding.tui.mascot import MASCOT_STATES, render_kitty_placeholder, render_mascot
from zerocoding.tui.kitty import (
    KittyInputFilter,
    KittyMascot,
    _transmit_png,
    kitty_probe_supported,
    kitty_probe,
)
from zerocoding.tui.theme import GHOST_FRAMES, GHOST_STATE_LABELS


class TestGhostMascot(unittest.TestCase):
    def test_each_agent_state_has_a_clear_portuguese_label(self):
        expected = {
            "idle": "pronto",
            "thinking": "pensando",
            "tool": "em ação",
            "approval": "aprovação",
            "done": "concluído",
            "error": "erro",
        }

        self.assertEqual(GHOST_STATE_LABELS, expected)

    def test_each_state_uses_a_distinct_expression_and_animation(self):
        states = ("idle", "thinking", "tool", "approval", "done", "error")

        self.assertEqual(set(GHOST_FRAMES), set(states))
        self.assertEqual(len({frames[0] for frames in GHOST_FRAMES.values()}), len(states))
        self.assertTrue(all(len(frames) > 1 for frames in GHOST_FRAMES.values()))

    def test_animation_changes_frame_without_changing_state_label(self):
        tui = object.__new__(ZerocodingTUI)
        tui.pet_state = "approval"

        with patch("zerocoding.tui.app.time.monotonic", side_effect=(0.0, 0.5)):
            first = tui._pet_face(animated=True)
            second = tui._pet_face(animated=True)

        self.assertNotEqual(first, second)
        self.assertEqual(tui._pet_state_label(), "aprovação")

    def test_busy_transcript_shows_the_current_state_instead_of_always_thinking(self):
        tui = object.__new__(ZerocodingTUI)
        tui.pet_state = "approval"
        tui._transcript = []
        tui._busy = True
        tui.startup_notice = ""

        rendered = "".join(content for _, content in tui._render_transcript())

        self.assertIn("aprovação", rendered)
        self.assertNotIn("pensando", rendered)

    def test_generated_sprite_data_covers_all_states_and_both_sizes(self):
        self.assertEqual(set(MASCOT_STATES), set(GHOST_STATE_LABELS))

        for compact, expected_size in ((False, (8, 4)), (True, (6, 3))):
            rendered_states = set()
            for state in MASCOT_STATES:
                rows = render_mascot(state, compact=compact)
                self.assertEqual(len(rows), expected_size[1])
                self.assertTrue(all(sum(len(text) for _, text in row) == expected_size[0] for row in rows))
                rendered_states.add(repr(rows))
            self.assertEqual(len(rendered_states), len(MASCOT_STATES))

    def test_each_state_has_distinct_animated_frames_in_both_sizes(self):
        for state in MASCOT_STATES:
            for compact in (False, True):
                frames = [repr(render_mascot(state, compact=compact, frame=index)) for index in range(4)]
                self.assertEqual(len(set(frames)), len(frames), (state, compact))

    def test_generated_kitty_frames_are_fixed_size_transparent_pngs(self):
        self.assertEqual(set(MASCOT_PNG_FRAMES), set(MASCOT_STATES))
        for state, frames in MASCOT_PNG_FRAMES.items():
            self.assertEqual(len(frames), 4)
            self.assertEqual(len(set(frames)), 4, state)
            for encoded in frames:
                png = base64.b64decode(encoded)
                self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual((int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")), (192, 192))
                self.assertEqual(png[25], 6)  # RGBA, including transparency

    def test_kitty_placeholders_fit_the_header_cells(self):
        for compact, expected in ((False, (8, 4)), (True, (6, 3))):
            rows = render_kitty_placeholder(0x123456, compact=compact)
            self.assertEqual((len(rows[0]), len(rows)), expected)
            self.assertTrue(all("\U0010eeee" in cell for row in rows for _, cell in row))

    def test_kitty_probe_accepts_only_a_valid_success_reply(self):
        self.assertTrue(kitty_probe_supported("\x1b_Gi=31;OK\x1b\\"))
        self.assertFalse(kitty_probe_supported("\x1b_Gi=31;EINVAL\x1b\\"))
        self.assertFalse(kitty_probe_supported("\x1b_Gi=31;\x1b\\"))
        self.assertFalse(kitty_probe_supported("\x1b[?1;2c"))
        self.assertIsNone(kitty_probe_supported(""))

    def test_kitty_probe_is_capped_at_250ms_and_preserves_typeahead(self):
        class FakeInput:
            def fileno(self):
                return 9

            def raw_mode(self):
                from contextlib import nullcontext
                return nullcontext()

        sent = []
        with patch("zerocoding.tui.kitty.select.select", return_value=([], [], [])) as select:
            supported, buffered = kitty_probe(FakeInput(), sent.append, timeout=5)
        self.assertFalse(supported)
        self.assertEqual(buffered, b"")
        self.assertLessEqual(select.call_args.args[3], 0.25)
        self.assertIn("\x1b_G", sent[0])

    def test_kitty_probe_handles_success_error_and_timeout(self):
        class FakeInput:
            def fileno(self):
                return 9

            def raw_mode(self):
                from contextlib import nullcontext
                return nullcontext()

        cases = (
            (b"\x1b_Gi=31;OK\x1b\\q", True),
            (b"\x1b_Gi=31;EINVAL\x1b\\q", False),
            (b"\x1b[?1;2cq", False),
        )
        for response, expected in cases:
            with self.subTest(response=response), patch("zerocoding.tui.kitty.select.select", side_effect=[([9], [], [])]), patch(
                "zerocoding.tui.kitty.os.read", return_value=response
            ):
                supported, buffered = kitty_probe(FakeInput(), lambda _: None)
            self.assertEqual(supported, expected)
            self.assertEqual(buffered, response)
            typed = KittyInputFilter().feed(buffered.decode("ascii"))
            self.assertEqual(typed, "q")

    def test_kitty_manager_uploads_loops_for_both_sizes_and_cleans_them_up(self):
        ids = iter(range(100, 112))
        manager = KittyMascot(id_factory=lambda: next(ids))
        output = []
        manager.upload(output.append)
        payload = "".join(output)
        self.assertEqual(len(manager.image_ids), 12)
        self.assertIn("a=f", payload)
        self.assertIn("z=200", payload)
        self.assertIn("c=8,r=4", payload)
        self.assertIn("c=6,r=3", payload)

        manager.update("approval", False, output.append)
        self.assertIn("s=3,v=1", output[-1])
        manager.update("error", True, output.append)
        self.assertIn("s=1", output[-1])
        self.assertIn("s=3,v=1", output[-1])
        manager.cleanup(output.append)
        self.assertEqual(output[-1].count("a=d,d=I"), 12)

    def test_kitty_input_filter_removes_split_protocol_replies_only(self):
        filter_input = KittyInputFilter()
        first = filter_input.feed("a\x1b_Gi=31;O")
        second = filter_input.feed("K\x1b\\b\x1b_Gi=123456;OK\x1b\\c\x1b[?1;2c")
        self.assertEqual(first + second, "abc")

    def test_kitty_image_chunks_follow_the_terminal_protocol(self):
        for frame_delay, expected_action in ((None, "a=t"), (200, "a=f")):
            commands = _transmit_png(42, b"x" * 6000, frame_delay)
            controls = re.findall(r"\x1b_G([^;]*);.*?\x1b\\", commands, re.DOTALL)
            self.assertGreater(len(controls), 1)
            self.assertIn(expected_action, controls[0])
            self.assertTrue(all("a=t" not in control for control in controls[1:]))
            if frame_delay is not None:
                self.assertTrue(all("a=f" in control for control in controls[1:]))

    def test_runtime_sprite_renderer_does_not_need_pillow(self):
        with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
            self.assertEqual(len(render_mascot("idle")), 4)

    def test_header_scales_sprite_and_keeps_text_next_to_it(self):
        tui = object.__new__(ZerocodingTUI)
        tui.pet_state = "approval"
        tui.mode = "code"
        tui.provider_name = "ollama_local"
        tui.model = "qwen2.5-coder:7b"
        tui.permission_mode = "manual"
        tui.session_id = "test"

        for width, expected_title_column in ((80, 10), (58, 8)):
            with self.subTest(width=width), patch(
                "zerocoding.tui.app.shutil.get_terminal_size",
                return_value=SimpleNamespace(columns=width),
            ):
                rows = "".join(text for _, text in tui._render_header()).splitlines()
                self.assertEqual(len(rows), 5)
                self.assertEqual(rows[0].index("ZeroCoding"), expected_title_column)
                self.assertIn("aprovação", rows[0])
                self.assertIn("ollama_local", rows[1])

    def test_extremely_narrow_header_uses_the_text_face_fallback(self):
        tui = object.__new__(ZerocodingTUI)
        tui.pet_state = "idle"
        tui.mode = "code"
        tui.provider_name = "ollama_local"
        tui.model = "qwen2.5-coder:7b"
        tui.permission_mode = "manual"
        tui.session_id = "test"

        with patch("zerocoding.tui.app.shutil.get_terminal_size", return_value=SimpleNamespace(columns=36)):
            rows = "".join(text for _, text in tui._render_header()).splitlines()

        self.assertEqual(len(rows), 5)
        self.assertIn("ZeroCoding", rows[0])
        self.assertNotIn("▀", rows[0])

    def test_input_prompt_prefix_shares_the_buffer_line_and_aligns_wrapping(self):
        tui = object.__new__(ZerocodingTUI)
        tui._pending_approval = None
        tui._wizard = None

        first_line = tui._input_line_prefix(0, 0)
        wrapped_line = tui._input_line_prefix(0, 1)
        next_line = tui._input_line_prefix(1, 0)

        self.assertEqual("".join(text for _, text in first_line), "> ")
        self.assertEqual("".join(text for _, text in wrapped_line), "  ")
        self.assertEqual("".join(text for _, text in next_line), "  ")

    def test_wizard_and_approval_keep_their_separate_question_label(self):
        tui = object.__new__(ZerocodingTUI)
        tui._pending_approval = (object(), {}, object())
        tui._wizard = None
        self.assertEqual(tui._input_line_prefix(0, 0), [])

        tui._pending_approval = None
        tui._wizard = {"question": "Nome"}
        self.assertEqual(tui._input_line_prefix(0, 0), [])


if __name__ == "__main__":
    unittest.main()
