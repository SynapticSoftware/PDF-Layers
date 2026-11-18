"""Preview PDF layers and export PDF or PNG files."""

import argparse
import os
import tempfile
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pikepdf
import pymupdf
from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD

from page_layers import page_layer_ids

TITLE = "PDF Layers"
ICON = Path(__file__).with_name("icon.png")
EXPORT_DPI = (150, 300, 600)
PNG_DPI = 300
PDF_FILES = [("PDF files", "*.pdf")]
PNG_FILES = [("PNG images", "*.png")]
FLATTENED_PDF = "Flattened PDF"
LAYERED_PDF = "Layered PDF"
PNG = "PNG (300 dpi)"
ALL_PAGES = "All pages"
CURRENT_PAGE = "Current page"
BACKGROUND = "#000000"
TEXT = "#f1f3f5"
MUTED = "#a1a8b3"


class LayeredPdf:
    def __init__(self, document, source, password=""):
        self.document = document
        self.source = source.resolve()
        self.password = password
        self.native = pymupdf._as_pdf_document(document)
        self.groups = document.get_ocgs()
        self.visibility = {xref: group["on"] for xref, group in self.groups.items()}
        self.page_groups = {}
        self.structure = pikepdf.open(self.source, password=password) if self.groups else None

    def close(self):
        if self.structure is not None:
            self.structure.close()
        self.native = None
        self.document.close()

    def layers(self, page_index=0):
        if self.structure is None:
            return
        if page_index not in self.page_groups:
            self.page_groups[page_index] = page_layer_ids(self.structure.pages[page_index])
        for xref, group in self.groups.items():
            if xref in self.page_groups[page_index]:
                yield xref, group["name"] or f"Layer {xref}", self.visibility[xref]

    def set_layer(self, xref, enabled):
        visibility = self.visibility | {xref: enabled}
        self.document.set_layer(
            -1, basestate="OFF",
            on=[key for key, visible in visibility.items() if visible],
            off=[key for key, visible in visibility.items() if not visible],
        )
        pymupdf.mupdf.pdf_select_layer_config(self.native, -1)
        self.visibility = visibility

    def preview(self, index, width, height):
        page = self.document[index]
        rect = page.rect
        scale = min(width / rect.width, height / rect.height, 6)
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")

    @contextmanager
    def output_path(self, destination):
        if destination.resolve() == self.source or (
            destination.exists() and destination.samefile(self.source)
        ):
            raise ValueError("Choose a different filename from the original PDF.")

        with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
            pending = Path(directory) / destination.name
            yield pending
            os.replace(pending, destination)

    def flatten(self, destination, dpi, page_index=None):
        """Yield progress after each page and replace the destination after saving."""
        pages = range(self.document.page_count) if page_index is None else (page_index,)
        with self.output_path(destination) as pending:
            reduced = 0
            with pymupdf.open() as output:
                for index, number in enumerate(pages, start=1):
                    page = self.document[number]
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

    def save_layered(self, destination, page_index=None):
        encryption = pymupdf.PDF_ENCRYPT_KEEP
        with self.output_path(destination) as pending:
            if page_index is None:
                self.document.save(str(pending), encryption=encryption)
                return

            data = self.document.tobytes(encryption=encryption)
            with pymupdf.open(stream=data, filetype="pdf") as output:
                if output.needs_pass and not output.authenticate(self.password):
                    raise ValueError("Could not unlock the exported PDF.")
                output.select([page_index])
                output.save(str(pending), garbage=1, encryption=encryption)

    def save_png(self, destination, page_index):
        page = self.document[page_index]
        width, height = page.rect.width, page.rect.height
        pixel_width = max(1, round(width * PNG_DPI / 72))
        pixel_height = max(1, round(height * PNG_DPI / 72))
        matrix = pymupdf.Matrix(pixel_width / width, pixel_height / height)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, annots=True)
        pixmap.set_dpi(PNG_DPI, PNG_DPI)
        with self.output_path(destination) as pending:
            pixmap.save(str(pending), output="png")


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
        self.configure_theme()
        if ICON.is_file():
            self.icon = tk.PhotoImage(file=str(ICON))
            root.iconphoto(True, self.icon)

        toolbar = ttk.Frame(root, padding=(12, 10))
        toolbar.pack(fill="x")
        self.open_button = ttk.Button(toolbar, text="Open PDF", command=self.open_pdf)
        self.open_button.pack(side="left")
        export_controls = ttk.Frame(toolbar)
        export_controls.pack(side="right")
        ttk.Label(export_controls, text="Pages").pack(side="left")
        self.scope = ttk.Combobox(
            export_controls, values=(ALL_PAGES, CURRENT_PAGE), state="readonly", width=11,
        )
        self.scope.current(0)
        self.scope.pack(side="left", padx=(6, 12))
        self.pdf_scope = ALL_PAGES
        ttk.Label(export_controls, text="Format").pack(side="left")
        self.format = ttk.Combobox(
            export_controls, values=(FLATTENED_PDF, LAYERED_PDF, PNG), state="readonly", width=15,
        )
        self.format.current(0)
        self.format.pack(side="left", padx=(6, 12))
        self.format.bind("<<ComboboxSelected>>", self.change_format)
        ttk.Label(export_controls, text="DPI").pack(side="left")
        self.dpi = ttk.Combobox(
            export_controls, values=[f"{dpi} dpi" for dpi in EXPORT_DPI],
            state="readonly", width=7,
        )
        self.dpi.current(1)
        self.flattened_dpi = 1
        self.dpi.pack(side="left", padx=(6, 12))
        self.save_button = ttk.Button(
            export_controls, text="Save As", command=self.save_file, state="disabled"
        )
        self.save_button.pack(side="left")

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
            sidebar, width=250, highlightthickness=0, background=BACKGROUND,
        )
        layer_scroll = ttk.Scrollbar(
            sidebar, orient="vertical", command=self.layer_canvas.yview,
            style="Vertical.TScrollbar",
        )

        def sync_layer_scroll(first, last):
            layer_scroll.set(first, last)
            if float(first) == 0 and float(last) == 1:
                layer_scroll.pack_forget()
            elif not layer_scroll.winfo_manager():
                layer_scroll.pack(side="right", fill="y", before=self.layer_canvas)

        self.layer_canvas.pack(side="left", fill="both", expand=True)
        self.layer_canvas.configure(yscrollcommand=sync_layer_scroll)
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

        self.canvas = tk.Canvas(viewer, background=BACKGROUND, highlightthickness=1,
                                highlightbackground="#272c33")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.schedule_preview)
        self.status = tk.StringVar(value="Open or drop a PDF.")
        ttk.Label(root, textvariable=self.status, foreground=MUTED,
                  padding=(12, 8)).pack(fill="x")

        root.bind("<Control-o>", lambda event: self.open_pdf())
        root.bind("<Control-s>", lambda event: self.save_file())
        root.protocol("WM_DELETE_WINDOW", self.close)
        for target in (root, self.canvas, self.layer_canvas):
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<DropEnter>>", self.drop_action)
            target.dnd_bind("<<Drop>>", self.drop_file)
        root.update_idletasks()
        root.minsize(max(680, toolbar.winfo_reqwidth() + 16), 420)

    def configure_theme(self):
        self.root.configure(background=BACKGROUND)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BACKGROUND, foreground=TEXT,
                        bordercolor="#353a42", lightcolor=BACKGROUND, darkcolor=BACKGROUND)
        style.configure("TButton", background="#1b2028", padding=(10, 5))
        style.map("TButton", background=[("active", "#303946")],
                  foreground=[("disabled", "#727985")])
        style.configure("TCheckbutton", indicatorbackground="#242b34", focuscolor="#9ab8ff")
        style.map("TCheckbutton", background=[("active", "#171b21")],
                  foreground=[("disabled", "#727985")],
                  indicatorbackground=[("selected", "#729af6")])
        style.configure("TCombobox", background="#20262e", fieldbackground="#161a20",
                        selectbackground="#20262e", selectforeground=TEXT, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", "#161a20"), ("disabled", "#101215")],
                  foreground=[("disabled", "#727985")], arrowcolor=[("disabled", "#727985")])
        style.configure("Vertical.TScrollbar", background="#262c35", troughcolor=BACKGROUND,
                        arrowcolor=TEXT)
        self.root.option_add("*TCombobox*Listbox.background", "#161a20")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#303946")

    def drop_action(self, event):
        return COPY if self.export is None else REFUSE_DROP

    def drop_file(self, event):
        if self.export is not None:
            return REFUSE_DROP
        for filename in self.root.tk.splitlist(event.data):
            path = Path(filename)
            if path.suffix.lower() == ".pdf" and path.is_file():
                return COPY if self.load_pdf(path) else REFUSE_DROP
        self.status.set("Drop a PDF file to open it.")
        return REFUSE_DROP

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
        password = ""
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
                    return False
                if not document.authenticate(password):
                    raise ValueError("The PDF password was incorrect.")
            if document.page_count < 1:
                raise ValueError("The PDF has no pages.")
            candidate = LayeredPdf(document, path, password)
        except Exception as error:
            if document is not None and not document.is_closed:
                document.close()
            messagebox.showerror("Could not open PDF", str(error), parent=self.root)
            return False

        if self.pdf is not None:
            self.pdf.close()
        self.pdf = candidate
        self.page = 0
        self.preview_image = None
        self.save_button.state(["!disabled"])
        self.update_page_controls()
        self.update_layers()
        self.schedule_preview()
        return True

    def update_layers(self):
        for child in self.layer_list.winfo_children():
            child.destroy()
        self.layer_controls.clear()
        try:
            layers = list(self.pdf.layers(self.page))
        except (ValueError, pikepdf.PdfError) as error:
            ttk.Label(self.layer_list, text="Could not read this page's layers.",
                      wraplength=220).pack(anchor="w")
            self.status.set(str(error))
            return

        for xref, name, enabled in layers:
            checked = tk.BooleanVar(self.root, value=enabled)
            box = ttk.Checkbutton(
                self.layer_list, text=name, variable=checked,
                command=lambda key=xref, value=checked: self.toggle_layer(key, value),
            )
            box.pack(anchor="w", fill="x", pady=2)
            box.bind("<MouseWheel>", self.scroll_layers)
            self.layer_controls.append((box, checked))
        if not layers:
            ttk.Label(self.layer_list, text="This page has no layers.").pack(anchor="w")

        self.layer_canvas.yview_moveto(0)
        label = "layer" if len(layers) == 1 else "layers"
        self.status.set(f"{self.pdf.source.name}   |   {len(layers)} {label} on this page")

    def toggle_layer(self, xref, checked):
        try:
            self.pdf.set_layer(xref, checked.get())
        except Exception as error:
            checked.set(not checked.get())
            messagebox.showerror("Could not change layer", str(error), parent=self.root)
        self.schedule_preview()

    def change_page(self, offset):
        self.page += offset
        self.preview_image = None
        self.update_page_controls()
        self.update_layers()
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
            self.canvas.create_text(*center, text="Drop a PDF here or choose Open PDF.",
                                    fill=MUTED)
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
                width=max(1, width - 32), justify="center", fill=TEXT,
            )

    def change_format(self, event):
        file_format = self.format.get()
        if file_format == PNG:
            self.pdf_scope = self.scope.get()
            self.scope.set(CURRENT_PAGE)
        elif self.scope.instate(["disabled"]):
            self.scope.set(self.pdf_scope)

        if self.dpi.instate(["readonly", "!disabled"]):
            self.flattened_dpi = self.dpi.current()
        if file_format == FLATTENED_PDF:
            self.dpi.current(self.flattened_dpi)
        else:
            self.dpi.set(f"{PNG_DPI} dpi" if file_format == PNG else "N/A")
        self.update_export_options(False)

    def save_file(self):
        if self.pdf is None or self.export is not None:
            return
        file_format = self.format.get()
        is_png = file_format == PNG
        page_index = self.page if is_png or self.scope.get() == CURRENT_PAGE else None
        extension = ".png" if is_png else ".pdf"
        suffix = f"-page-{page_index + 1}" if page_index is not None else ""
        if not is_png:
            suffix += "-flattened" if file_format == FLATTENED_PDF else "-layered"
        filename = filedialog.asksaveasfilename(
            parent=self.root, title=f"Save {file_format}",
            initialdir=str(self.pdf.source.parent),
            initialfile=f"{self.pdf.source.stem}{suffix}{extension}",
            defaultextension=extension, filetypes=PNG_FILES if is_png else PDF_FILES,
        )
        if not filename:
            return

        destination = Path(filename)
        self.export = self.export_file(destination, file_format, page_index)
        count = self.pdf.document.page_count if page_index is None else 1
        self.set_export_busy(True)
        self.status.set("Preparing export...")
        self.root.after(20, self.export_page, destination, count, 0)

    def export_file(self, destination, file_format, page_index):
        if file_format == FLATTENED_PDF:
            yield from self.pdf.flatten(destination, EXPORT_DPI[self.dpi.current()], page_index)
        elif file_format == LAYERED_PDF:
            self.pdf.save_layered(destination, page_index)
        else:
            self.pdf.save_png(destination, page_index)

    def update_export_options(self, busy):
        file_format = self.format.get()
        self.format.configure(state="disabled" if busy else "readonly")
        self.scope.configure(state="disabled" if busy or file_format == PNG else "readonly")
        self.dpi.configure(state="disabled" if busy or file_format != FLATTENED_PDF else "readonly")

    def set_export_busy(self, busy):
        state = "disabled" if busy else "normal"
        for control in (self.open_button, self.save_button, self.previous, self.next):
            control.configure(state=state)
        for box, _ in self.layer_controls:
            box.configure(state=state)
        self.update_export_options(busy)
        if not busy:
            self.update_page_controls()

    def export_page(self, destination, count, reduced):
        try:
            index, reduced = next(self.export)
        except StopIteration:
            note = f"  |  Resolution reduced on {reduced} large page(s)" if reduced else ""
            self.status.set(f"Saved {destination}{note}")
        except Exception as error:
            self.status.set("The PDF could not be saved.")
            messagebox.showerror("Could not save PDF", str(error), parent=self.root)
        else:
            self.status.set(f"Flattening page {index} of {count}...")
            self.root.after(10, self.export_page, destination, count, reduced)
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
    root = TkinterDnD.Tk()
    app = App(root)
    if arguments.pdf is not None:
        root.after_idle(app.load_pdf, arguments.pdf)
    root.mainloop()


if __name__ == "__main__":
    main()
