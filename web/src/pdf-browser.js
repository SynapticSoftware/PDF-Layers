import * as pdfjs from 'pdfjs-dist';
import { PDFDocument } from 'pdf-lib';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { pageLayerIds, PNG_DPI, pngWithResolution, rasterSize } from './pdf-format';
export { saveLayered } from './pdf-format';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export function loadPdf(bytes) {
  const assets = new URL(import.meta.env.BASE_URL + 'pdf-assets/', document.baseURI);
  const assetUrl = (path) => new URL(path, assets).href;
  return pdfjs.getDocument({
    data: bytes.slice(),
    cMapUrl: assetUrl('cmaps/'),
    cMapPacked: true,
    standardFontDataUrl: assetUrl('standard_fonts/'),
    wasmUrl: assetUrl('wasm/'),
    iccUrl: assetUrl('iccs/'),
    isEvalSupported: false,
    enableXfa: true,
  });
}

export async function layersForPage(page, config) {
  if (!config.getOrder()) return [];
  const pageIds = pageLayerIds(await page.getOperatorList(), pdfjs.OPS.beginMarkedContentProps);
  return Array.from(config).filter(([id]) => pageIds.has(id));
}

function canvasToPng(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('The browser could not encode this page as an image.'));
    }, 'image/png');
  });
}

async function rasterize(page, config, dpi, capLargePages) {
  const viewport = page.getViewport({ scale: 1 });
  const requested = dpi / 72;
  const scale = capLargePages ? Math.min(
    requested,
    Math.sqrt(32_000_000 / (viewport.width * viewport.height)),
    12000 / Math.max(viewport.width, viewport.height),
  ) : requested;
  const canvas = document.createElement('canvas');
  [canvas.width, canvas.height] = rasterSize(viewport.width, viewport.height, scale * 72);
  if (canvas.width * canvas.height > 100_000_000 || Math.max(canvas.width, canvas.height) > 32767) {
    throw new Error('This page exceeds the browser image size limit at 300 dpi.');
  }
  const transform = [canvas.width / viewport.width, 0, 0, canvas.height / viewport.height, 0, 0];
  try {
    await page.render({
      canvas, viewport, transform, background: '#fff',
      optionalContentConfigPromise: Promise.resolve(config),
    }).promise;

    return {
      blob: await canvasToPng(canvas),
      width: viewport.width,
      height: viewport.height,
      reduced: scale < requested,
    };
  } finally {
    canvas.width = canvas.height = 0;
  }
}

export async function savePng(page, config) {
  const { blob } = await rasterize(page, config, PNG_DPI, false);
  return pngWithResolution(new Uint8Array(await blob.arrayBuffer()), PNG_DPI);
}

export async function flattenPdf(pdf, config, pageNumber, dpi, onProgress) {
  const output = await PDFDocument.create();
  const first = pageNumber ?? 1;
  const last = pageNumber ?? pdf.numPages;
  let reduced = 0;
  for (let number = first; number <= last; number++) {
    onProgress(number - first + 1, last - first + 1);
    const page = await pdf.getPage(number);
    const raster = await rasterize(page, config, dpi, true);
    const pageImage = await output.embedPng(await raster.blob.arrayBuffer());
    const { width, height } = raster;
    output.addPage([width, height]).drawImage(pageImage, { x: 0, y: 0, width, height });
    if (raster.reduced) reduced++;
  }
  return { bytes: await output.save(), reduced };
}

export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
