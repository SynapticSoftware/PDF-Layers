"""Preview and flatten PDF optional content on Windows."""

import argparse
from pathlib import Path
import os
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf

TITLE = "PDF Layers"
ICON = Path(__file__).with_name("icon.png")
EXPORT_DPI = (150, 300, 600)
PDF_FILES = [("PDF files", "*.pdf")]


class LayeredPdf:
    def __init__(self, document, source):
        self.document = document
        self.source = source.resolve()
        self.engine = pymupdf.mupdf
        self.native = pymupdf._as_pdf_document(document)

    def close(self):
        self.native = None
        self.document.close()

    def layers(self):
        for index in range(self.engine.pdf_count_layers(self.native)):
            name = self.engine.pdf_layer_name(self.native, index)
            enabled = self.engine.pdf_layer_is_enabled(self.native, index)
            yield index, name or f"Layer {index + 1}", bool(enabled)

    def set_layer(self, index, enabled):
        self.engine.pdf_enable_layer(self.native, index, int(enabled))

    def preview(self, index, width, height):
        page = self.document[index]
        rect = page.rect
        scale = min(width / rect.width, height / rect.height, 6)
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")

    def flatten(self, destination, dpi):
        """Yield progress after each page and replace the destination after saving."""
        if destination.resolve() == self.source or (
            destination.exists() and destination.samefile(self.source)
        ):
            raise ValueError("Choose a different filename from the original PDF.")

        with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
            pending = Path(directory) / "flattened.pdf"
            reduced = 0
            with pymupdf.open() as output:
                for index, page in enumerate(self.document, start=1):
                    rect = page.rect
                    scale = min(
                        dpi / 72,
                        (32_000_000 / (rect.width * rect.height)) ** 0.5,
                        12_000 / max(rect.width, rect.height),
                    )
                    reduced += scale < dpi / 72
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True
                    )
                    new_page = output.new_page(width=rect.width, height=rect.height)
                    new_page.insert_image(
                        new_page.rect, stream=pixmap.tobytes("png"),
                        keep_proportion=False,
                    )
                    yield index, reduced
                output.save(str(pending), deflate=True)
            os.replace(pending, destination)


class App:
    def __init__(self, root):
        self.root = root
        self.pdf = None
        self.page = 0
        self.preview_job = None
        self.preview_image = None
        self.export = None
        self.layer_controls = []

        root.title(TITLE)
        root.geometry("1080x720")
        root.minsize(640, 420)
        if ICON.is_file():
            self.icon = tk.PhotoImage(file=str(ICON))
            root.iconphoto(True, self.icon)

        toolbar = ttk.Frame(root, padding=(12, 10))
        toolbar.pack(fill="x")
        self.open_button = ttk.Button(toolbar, text="Open PDF", command=self.open_pdf)
        self.open_button.pack(side="left")
        self.save_button = ttk.Button(
            toolbar, text="Save Flattened PDF", command=self.save_pdf, state="disabled"
        )
        self.save_button.pack(side="right")
        self.dpi = ttk.Combobox(
            toolbar, values=[f"{dpi} dpi" for dpi in EXPORT_DPI],
            state="readonly", width=9,
        )
        self.dpi.current(1)
        self.dpi.pack(side="right", padx=(8, 12))
        ttk.Label(toolbar, text="Export quality").pack(side="right")

        body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12)
        sidebar = ttk.Frame(body, padding=(0, 8, 8, 0))
        viewer = ttk.Frame(body)
        body.add(sidebar, weight=0)
        body.add(viewer, weight=1)

        ttk.Label(sidebar, text="Layers", font=("Segoe UI", 12, "bold")).pack(
            anchor="w", pady=(0, 8)
        )
        self.layer_canvas = tk.Canvas(
            sidebar, width=250, highlightthickness=0,
            background=ttk.Style(root).lookup("TFrame", "background") or "#f0f0f0",
        )
        layer_scroll = ttk.Scrollbar(
            sidebar, orient="vertical", command=self.layer_canvas.yview
        )
        layer_scroll.pack(side="right", fill="y")
        self.layer_canvas.pack(side="left", fill="both", expand=True)
        self.layer_canvas.configure(yscrollcommand=layer_scroll.set)
        self.layer_list = ttk.Frame(self.layer_canvas)
        layer_window = self.layer_canvas.create_window(
            0, 0, anchor="nw", window=self.layer_list
        )
        self.layer_list.bind(
            "<Configure>", lambda event: self.layer_canvas.configure(
                scrollregion=self.layer_canvas.bbox("all")
            ),
        )
        self.layer_canvas.bind(
            "<Configure>", lambda event: self.layer_canvas.itemconfigure(
                layer_window, width=event.width
            ),
        )
        self.layer_canvas.bind("<MouseWheel>", self.scroll_layers)
        ttk.Label(self.layer_list, text="Open a PDF to see its layers.").pack(anchor="w")

        nav = ttk.Frame(viewer, padding=(0, 0, 0, 8))
        nav.pack(fill="x")
        self.previous = ttk.Button(
            nav, text="Previous", command=lambda: self.change_page(-1), state="disabled"
        )
        self.next = ttk.Button(
            nav, text="Next", command=lambda: self.change_page(1), state="disabled"
        )
        self.page_label = ttk.Label(nav, text="Preview", width=18, anchor="center")
        self.previous.pack(side="left")
        self.page_label.pack(side="left")
        self.next.pack(side="left")

        self.canvas = tk.Canvas(viewer, background="#e6ebf1", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.schedule_preview)
        self.status = tk.StringVar(value="Open a PDF to begin.")
        ttk.Label(root, textvariable=self.status, padding=(12, 8)).pack(fill="x")

        root.bind("<Control-o>", lambda event: self.open_pdf())
        root.bind("<Control-s>", lambda event: self.save_pdf())
        root.protocol("WM_DELETE_WINDOW", self.close)

    def scroll_layers(self, event):
        self.layer_canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def open_pdf(self):
        if self.export is not None:
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=PDF_FILES)
        if path:
            self.load_pdf(Path(path))

    def load_pdf(self, path):
        document = None
        try:
            document = pymupdf.open(str(path))
            if not document.is_pdf:
                raise ValueError("Choose a PDF file.")
            if document.needs_pass:
                password = simpledialog.askstring(
                    "Password-protected PDF", "Enter the PDF password.",
                    show="*", parent=self.root,
                )
                if password is None:
                    document.close()
                    return
                if not document.authenticate(password):
                    raise ValueError("The PDF password was incorrect.")
            if document.page_count < 1:
                raise ValueError("The PDF has no pages.")
            candidate = LayeredPdf(document, path)
            layers = list(candidate.layers())
        except Exception as error:
            if document is not None and not document.is_closed:
                document.close()
            messagebox.showerror("Could not open PDF", str(error), parent=self.root)
            return

        if self.pdf is not None:
            self.pdf.close()
        self.pdf = candidate
        self.page = 0

        for child in self.layer_list.winfo_children():
            child.destroy()
        self.layer_controls.clear()
        for index, name, enabled in layers:
            checked = tk.BooleanVar(self.root, value=enabled)
            box = ttk.Checkbutton(
                self.layer_list, text=name, variable=checked,
                command=lambda i=index, value=checked: self.toggle_layer(i, value),
            )
            box.pack(anchor="w", fill="x", pady=2)
            box.bind("<MouseWheel>", self.scroll_layers)
            self.layer_controls.append((box, checked))
        if not layers:
            ttk.Label(self.layer_list, text="This PDF has no layers.").pack(anchor="w")

        self.layer_canvas.yview_moveto(0)
        self.status.set(f"{path.name}   |   {len(layers)} layers")
        self.save_button.state(["!disabled"])
        self.update_page_controls()
        self.schedule_preview()

    def toggle_layer(self, index, checked):
        try:
            self.pdf.set_layer(index, checked.get())
        except Exception as error:
            checked.set(not checked.get())
            messagebox.showerror("Could not change layer", str(error), parent=self.root)
        self.schedule_preview()

    def change_page(self, offset):
        self.page += offset
        self.update_page_controls()
        self.schedule_preview()

    def update_page_controls(self):
        count = self.pdf.document.page_count
        self.page_label.configure(text=f"Page {self.page + 1} of {count}")
        self.previous.configure(state="normal" if self.page > 0 else "disabled")
        self.next.configure(state="normal" if self.page + 1 < count else "disabled")

    def schedule_preview(self, event=None):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(80, self.render_preview)

    def render_preview(self):
        self.preview_job = None
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        center = (width // 2, height // 2)
        if self.pdf is None:
            self.canvas.create_text(*center, text="Open a PDF to preview it.")
            return
        if self.export is not None and self.preview_image is not None:
            self.canvas.create_image(*center, image=self.preview_image)
            return

        try:
            png = self.pdf.preview(self.page, max(1, width - 32), max(1, height - 32))
            self.preview_image = tk.PhotoImage(data=png, format="png")
            self.canvas.create_image(*center, image=self.preview_image)
        except Exception as error:
            self.preview_image = None
            self.canvas.create_text(
                *center, text=f"Could not preview this page.\n{error}",
                width=max(1, width - 32), justify="center",
            )

    def save_pdf(self):
        if self.pdf is None or self.export is not None:
            return
        filename = filedialog.asksaveasfilename(
            parent=self.root, title="Save Flattened PDF",
            initialdir=str(self.pdf.source.parent),
            initialfile=f"{self.pdf.source.stem}-flattened.pdf",
            defaultextension=".pdf", filetypes=PDF_FILES,
        )
        if not filename:
            return

        destination = Path(filename)
        self.export = self.pdf.flatten(destination, EXPORT_DPI[self.dpi.current()])
        self.set_export_busy(True)
        self.status.set("Preparing export...")
        self.root.after(20, self.export_page, destination, 0)

    def set_export_busy(self, busy):
        state = "disabled" if busy else "normal"
        for control in (self.open_button, self.save_button, self.previous, self.next):
            control.configure(state=state)
        for box, _ in self.layer_controls:
            box.configure(state=state)
        self.dpi.configure(state="disabled" if busy else "readonly")
        if not busy:
            self.update_page_controls()

    def export_page(self, destination, reduced):
        try:
            index, reduced = next(self.export)
        except StopIteration:
            note = f"  |  Resolution reduced on {reduced} large page(s)" if reduced else ""
            self.status.set(f"Saved {destination}{note}")
        except Exception as error:
            self.status.set("The PDF could not be saved.")
            messagebox.showerror("Could not save PDF", str(error), parent=self.root)
        else:
            self.status.set(f"Flattening page {index} of {self.pdf.document.page_count}...")
            self.root.after(10, self.export_page, destination, reduced)
            return

        self.export = None
        self.set_export_busy(False)
        self.schedule_preview()

    def close(self):
        if self.export is not None:
            if not messagebox.askyesno(
                "Cancel export", "Cancel the current export and close PDF Layers?",
                parent=self.root,
            ):
                return
            if self.export is not None:
                self.export.close()
        if self.pdf is not None:
            self.pdf.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="?")
    arguments = parser.parse_args()
    root = tk.Tk()
    app = App(root)
    if arguments.pdf is not None:
        root.after_idle(app.load_pdf, arguments.pdf)
    root.mainloop()


if __name__ == "__main__":
    main()
