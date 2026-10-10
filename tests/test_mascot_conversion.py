import base64
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from scripts.render_mascot import SOURCE, STATES, render_data, write_gifs


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is optional and used only by the asset converter")
class TestMascotConversion(unittest.TestCase):
    def test_source_atlas_becomes_transparent_gifs_and_kitty_frames(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            gif_dir = Path(temporary)
            write_gifs(SOURCE, gif_dir)
            sprites, png_frames = render_data(gif_dir)

            self.assertEqual(set(sprites), set(STATES))
            self.assertEqual(set(png_frames), set(STATES))
            for state in STATES:
                with Image.open(gif_dir / f"{state}.gif") as gif:
                    self.assertEqual(gif.n_frames, 4)
                    self.assertIn("transparency", gif.info)
                self.assertEqual(len(png_frames[state]), 4)
                for frame in png_frames[state]:
                    with Image.open(io.BytesIO(base64.b64decode(frame))) as source:
                        image = source.convert("RGBA")
                        self.assertEqual(image.size, (192, 192))
                        alpha = image.getchannel("A")
                        self.assertEqual(alpha.getextrema()[0], 0)
                        self.assertGreater(alpha.getextrema()[1], 0)
                for name, dimensions in (("normal", (8, 4)), ("compact", (6, 3))):
                    self.assertEqual(len(sprites[state][name]), 4)
                    self.assertTrue(all(len(frame) == dimensions[1] for frame in sprites[state][name]))


if __name__ == "__main__":
    unittest.main()
