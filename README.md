# PDF Layers

PDF Layers is a Windows desktop app for previewing PDF layers and saving the visible pages as a flattened PDF.

1. Open a PDF.
2. Check or uncheck layers and use **Previous** and **Next** to inspect the pages.
3. Choose an export resolution, click **Save Flattened PDF**, and choose a new filename.

Export uses the same renderer as the preview. It renders the visible page content and annotations into page images and keeps the original displayed dimensions and page order. The output has no interactive layers, searchable text, form fields, or links. Very large pages may be rendered below the selected resolution.

## Windows executable

Open the latest successful **Build Windows app** run in [Actions](https://github.com/SynapticSoftware/PDF-Layers/actions) and download the `PDFLayers-Windows-x64` artifact. Extract the ZIP and run `PDFLayers.exe`.

To build locally on Windows, install Python 3.12 x64 and run `build.cmd`. The build runs the tests and produces `dist\PDFLayers.exe`.

## Run from source

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 pdf_layers.py
```

The app window and executable use `icon.png`. Both use the same stacked-layer artwork.
