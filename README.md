# PDF Layers

PDF Layers is a Windows desktop app for previewing PDF layers and exporting PDF or PNG files.

1. Drop a PDF onto the window or choose **Open PDF**.
2. Use **Previous** and **Next** to move between pages. The layer list shows the layers used on that page, including hidden layers. Check or uncheck them to update the preview. A layer shared across pages has one visibility setting.
3. Choose **All pages** or **Current page**, choose a format, then click **Save As**.

- **Layered PDF** keeps PDF content and layers with your chosen default visibility. Hidden layers can be turned back on in a PDF viewer.
- **Flattened PDF** renders the visible content and annotations into page images. You can choose 150, 300, or 600 dpi. Very large pages may be rendered at a lower resolution. The output has no interactive layers, searchable text, form fields, or links.
- **PNG (300 dpi)** saves the current page as a single image. Pixel dimensions are calculated from the displayed page width and height at 300 dpi, rounded to whole pixels.

## Windows executable

Open the latest successful **Build Windows app** run in [Actions](https://github.com/SynapticSoftware/PDF-Layers/actions) and download the `PDFLayers-Windows-x64` artifact. Extract the ZIP and run `PDFLayers.exe`.

To build locally on Windows, install Python 3.12 x64 and run `build.cmd`. The build runs the tests and produces `dist\PDFLayers.exe`.

## Run from source

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 pdf_layers.py
```

The app window and executable use `icon.png`. Both use the same stacked-layer artwork.

## React web app

The [React version](web/) runs in the browser and includes page-specific layer controls plus PDF and PNG exports. See the [web app README](web/README.md) for setup.
