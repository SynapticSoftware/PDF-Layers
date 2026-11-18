import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_layers import LayeredPdf


class FlattenTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "layered.pdf"
        self.destination = Path(directory.name) / "flattened.pdf"
        with pymupdf.open() as document:
            red = document.add_ocg("Red", on=True)
            blue = document.add_ocg("Blue", on=False)
            first = document.new_page(width=144, height=96)
            first.draw_rect((0, 0, 72, 96), color=None, fill=(1, 0, 0), oc=red)
            first.draw_rect((72, 0, 144, 96), color=None, fill=(0, 0, 1), oc=blue)
            second = document.new_page(width=144, height=96)
            second.draw_rect(second.rect, color=None, fill=(0, 1, 0))
            second.set_rotation(90)
            document.save(str(self.source))

        self.pdf = LayeredPdf(pymupdf.open(str(self.source)), self.source)
        self.addCleanup(self.pdf.close)

    def assert_colors(self, picture, left, right):
        self.assertEqual(picture.pixel(picture.width // 4, picture.height // 2), left)
        self.assertEqual(picture.pixel(picture.width * 3 // 4, picture.height // 2), right)

    def test_layer_toggles_drive_preview_and_export(self):
        original = self.source.read_bytes()
        layers = {name: (index, enabled) for index, name, enabled in self.pdf.layers()}
        red, red_enabled = layers["Red"]
        blue, blue_enabled = layers["Blue"]
        self.assertTrue(red_enabled)
        self.assertFalse(blue_enabled)

        preview = pymupdf.Pixmap(self.pdf.preview(0, 144, 96))
        self.assert_colors(preview, (255, 0, 0), (255, 255, 255))

        self.pdf.set_layer(red, False)
        self.pdf.set_layer(blue, True)
        preview = pymupdf.Pixmap(self.pdf.preview(0, 144, 96))
        self.assert_colors(preview, (255, 255, 255), (0, 0, 255))

        self.assertEqual(list(self.pdf.flatten(self.destination, 300)), [(1, 0), (2, 0)])
        self.assertEqual(self.source.read_bytes(), original)
        with pymupdf.open(str(self.destination)) as output:
            self.assertEqual(output.page_count, 2)
            self.assertEqual(output.get_ocgs(), {})
            self.assertEqual(output[0].rect, pymupdf.Rect(0, 0, 144, 96))
            self.assertEqual(output[1].rect, pymupdf.Rect(0, 0, 96, 144))
            self.assert_colors(output[0].get_pixmap(), (255, 255, 255), (0, 0, 255))
            self.assert_colors(output[1].get_pixmap(), (0, 255, 0), (0, 255, 0))

    def test_cancel_preserves_existing_destination(self):
        self.destination.write_bytes(b"existing output")
        export = self.pdf.flatten(self.destination, 150)
        next(export)
        export.close()
        self.assertEqual(self.destination.read_bytes(), b"existing output")
        self.assertEqual(set(self.destination.parent.iterdir()), {self.source, self.destination})

    def test_export_cannot_replace_original(self):
        original = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "original PDF"):
            list(self.pdf.flatten(self.source, 150))
        self.assertEqual(self.source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
