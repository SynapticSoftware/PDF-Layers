import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pikepdf
import pymupdf
from tkinterdnd2 import COPY, REFUSE_DROP, TkinterDnD

from pdf_layers import App, LayeredPdf


class FlattenTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "layered.pdf"
        self.destination = Path(directory.name) / "flattened.pdf"
        with pymupdf.open() as document:
            red = document.add_ocg("Red", on=True)
            blue = document.add_ocg("Blue", on=False)
            green = document.add_ocg("Green", on=True)
            first = document.new_page(width=144, height=96)
            first.draw_rect((0, 0, 72, 96), color=None, fill=(1, 0, 0), oc=red)
            first.draw_rect((72, 0, 144, 96), color=None, fill=(0, 0, 1), oc=blue)
            first.insert_text((3, 12), "Layer text", fontsize=6)
            second = document.new_page(width=144, height=96)
            with pymupdf.open() as art:
                art_page = art.new_page(width=144, height=96)
                art_page.draw_rect(art_page.rect, color=None, fill=(0, 1, 0))
                second.show_pdf_page(second.rect, art, 0, oc=green)
            second.set_rotation(90)
            document.save(str(self.source))

        # A shared resource dictionary can list a group that a page never draws.
        with pikepdf.open(self.source, allow_overwriting_input=True) as structure:
            structure.pages[0].Resources.Properties.Unused = structure.Root.OCProperties.OCGs[2]
            structure.save(self.source)

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

    def test_only_lists_layers_used_on_each_page_even_when_hidden(self):
        self.assertEqual({name for _, name, _ in self.pdf.layers(0)}, {"Red", "Blue"})
        green, name, state = next(self.pdf.layers(1))
        self.assertEqual((name, state), ("Green", True))
        self.pdf.set_layer(green, False)
        self.assertEqual(list(self.pdf.layers(1)), [(green, "Green", False)])
        preview = pymupdf.Pixmap(self.pdf.preview(1, 96, 144))
        self.assert_colors(preview, (255, 255, 255), (255, 255, 255))
        first = pymupdf.Pixmap(self.pdf.preview(0, 144, 96))
        self.assert_colors(first, (255, 0, 0), (255, 255, 255))

    def test_one_page_flattened_export(self):
        self.assertEqual(list(self.pdf.flatten(self.destination, 300, page_index=1)), [(1, 0)])
        with pymupdf.open(self.destination) as output:
            self.assertEqual(output.page_count, 1)
            self.assertEqual(output.get_ocgs(), {})
            self.assertEqual(output[0].rect, pymupdf.Rect(0, 0, 96, 144))
            self.assert_colors(output[0].get_pixmap(), (0, 255, 0), (0, 255, 0))

    def test_layered_export_keeps_content_and_selected_visibility_for_both_scopes(self):
        original = self.source.read_bytes()
        for xref, name, _ in self.pdf.layers(0):
            self.pdf.set_layer(xref, name == "Blue")

        for page_index, page_count in ((None, 2), (0, 1)):
            with self.subTest(page_index=page_index):
                self.pdf.save_layered(self.destination, page_index)
                with pymupdf.open(self.destination) as output:
                    self.assertEqual(output.page_count, page_count)
                    self.assertIn("Layer text", output[0].get_text())
                    layers = {group["name"]: group["on"] for group in output.get_ocgs().values()}
                    self.assertFalse(layers["Red"])
                    self.assertTrue(layers["Blue"])
                    self.assert_colors(output[0].get_pixmap(), (255, 255, 255), (0, 0, 255))
        self.assertEqual(self.source.read_bytes(), original)

    def test_png_uses_displayed_dimensions_and_300_dpi(self):
        green, _, _ = next(self.pdf.layers(1))
        self.pdf.set_layer(green, False)
        image_path = self.source.with_suffix(".png")
        self.pdf.save_png(image_path, page_index=1)
        png = pymupdf.Pixmap(image_path)
        self.assertEqual((png.width, png.height), (400, 600))
        self.assertEqual((png.xres, png.yres), (300, 300))
        self.assert_colors(png, (255, 255, 255), (255, 255, 255))

    def test_drop_opens_pdf_path_with_spaces_and_unicode(self):
        file = self.source.with_name("ä drawing.PDF")
        file.write_bytes(self.source.read_bytes())
        opened = []

        def load_pdf(path):
            opened.append(path)
            return True

        app = SimpleNamespace(root=tk.Tcl(), export=None, load_pdf=load_pdf)
        event = SimpleNamespace(data="{" + file.as_posix() + "}")
        self.assertEqual(App.drop_file(app, event), COPY)
        self.assertEqual(opened, [file])
        app.export = iter(())
        self.assertEqual(App.drop_file(app, event), REFUSE_DROP)

    @unittest.skipUnless(sys.platform == "win32", "Uses the Windows TkDND dispatcher")
    def test_windows_file_drop_reaches_the_canvas(self):
        source = self.source.with_name("ä drawing.PDF")
        source.write_bytes(self.source.read_bytes())
        root = TkinterDnD.Tk()
        app = App(root)
        self.addCleanup(app.close)
        root.update()
        canvas = app.canvas
        x = canvas.winfo_rootx() + 20
        y = canvas.winfo_rooty() + 20

        with patch("pdf_layers.messagebox.showerror") as show_error:
            self.assertEqual(root.tk.call(
                "olednd::HandleDragEnter", str(canvas), ("CF_HDROP",), (COPY,), (),
                x, y, (15,),
            ), COPY)
            self.assertEqual(root.tk.call(
                "olednd::HandleDrop", str(canvas), (), x, y, "CF_HDROP", (str(source),),
            ), COPY)
            show_error.assert_not_called()

        self.assertEqual(app.pdf.source, source.resolve())
        self.assertEqual([box.cget("text") for box, _ in app.layer_controls], ["Red", "Blue"])


if __name__ == "__main__":
    unittest.main()
