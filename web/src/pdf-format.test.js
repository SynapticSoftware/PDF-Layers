import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { PDFDocument, PDFDict, PDFName } from 'pdf-lib';
import { getDocument, OPS } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { pageLayerIds, pngWithResolution, rasterSize, saveLayered } from './pdf-format.js';

const sample = new URL('../public/sample.pdf', import.meta.url);
const fontDirectory = new URL('../node_modules/pdfjs-dist/standard_fonts/', import.meta.url).pathname;

async function open(bytes) {
  const task = getDocument({ data: new Uint8Array(bytes), standardFontDataUrl: fontDirectory });
  return { pdf: await task.promise, task };
}

test('used layer list is page-specific and includes hidden and shared layers', async () => {
  const { pdf, task } = await open(await readFile(sample));
  try {
    const config = await pdf.getOptionalContentConfig();
    const names = async (pageNumber) => {
      const page = await pdf.getPage(pageNumber);
      const ids = pageLayerIds(await page.getOperatorList(), OPS.beginMarkedContentProps);
      return [...ids].map((id) => config.getGroup(id).name).sort();
    };
    assert.deepEqual(await names(1), ['Floor plan', 'Furniture', 'Measurements']);
    assert.deepEqual(await names(2), ['Measurements', 'Notes']);
    assert.equal([...config].find(([, group]) => group.name === 'Measurements')[1].visible, false);
  } finally {
    await task.destroy();
  }
});

test('layered export preserves group references and visibility for one or all pages', async () => {
  const bytes = await readFile(sample);
  const { pdf, task } = await open(bytes);
  try {
    const config = await pdf.getOptionalContentConfig();
    const id = [...config].find(([, group]) => group.name === 'Furniture')[0];
    config.setVisibility(id, false);
    for (const pageNumber of [null, 1]) {
      const saved = await saveLayered(bytes, config, pageNumber);
      const pdfLibDocument = await PDFDocument.load(saved);
      assert.ok(pdfLibDocument.catalog.lookupMaybe(PDFName.of('OCProperties'), PDFDict));
      const { pdf: reopened, task: reopenedTask } = await open(saved);
      try {
        assert.equal(reopened.numPages, pageNumber === null ? 2 : 1);
        const savedConfig = await reopened.getOptionalContentConfig();
        const [savedId, furniture] = [...savedConfig].find(([, group]) => group.name === 'Furniture');
        assert.equal(furniture.visible, false);
        const page = await reopened.getPage(1);
        assert.ok(pageLayerIds(await page.getOperatorList(), OPS.beginMarkedContentProps).has(savedId));
      } finally {
        await reopenedTask.destroy();
      }
    }
  } finally {
    await task.destroy();
  }
});

test('300 dpi PNG preserves pixels and receives the correct physical resolution', async () => {
  assert.deepEqual(rasterSize(612, 792, 300), [2550, 3300]);
  assert.deepEqual(rasterSize(96, 144, 300), [400, 600]);
  const icon = await readFile(new URL('../public/icon.png', import.meta.url));
  const changed = new Uint8Array(await pngWithResolution(icon, 300).arrayBuffer());
  const read = new DataView(changed.buffer);
  assert.equal(read.getUint32(37), 0x70485973);
  assert.equal(read.getUint32(41), 11811);
  assert.equal(read.getUint32(45), 11811);
  assert.equal(changed[49], 1);
  assert.deepEqual(changed.subarray(16, 24), new Uint8Array(icon.subarray(16, 24)));
});
