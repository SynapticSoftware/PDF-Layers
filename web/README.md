# PDF Layers for the browser

A React app for previewing optional PDF layers and downloading the visible result. PDF files selected by the user are read and processed locally in the browser.

- Open or drop a PDF and use the layer list for the current page. A shared layer has the same setting wherever it appears in the PDF.
- Download one page or all pages as a flattened or layered PDF. A flattened PDF uses page images. A layered PDF keeps original page content with the chosen default layer visibility.
- Download the current page as a 300 dpi PNG. The pixel dimensions are calculated from the displayed page size, including its rotation.
- Password-protected PDFs can be opened for preview and image export. Layered export requires an unencrypted source PDF.

## Run from source

```sh
npm ci
npm run dev
```

Run `npm test` for the PDF format checks. Run `npm run build` to create the deployable static site in `dist/`.
