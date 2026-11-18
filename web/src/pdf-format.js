import {
  EncryptedPDFError,
  PDFArray,
  PDFDict,
  PDFDocument,
  PDFName,
  PDFObjectCopier,
  PDFPage,
  PDFRef,
} from 'pdf-lib';

export const PNG_DPI = 300;

export function pageLayerIds(operators, beginMarkedContentProps) {
  const groups = new Set();
  const visit = (item) => {
    if (typeof item === 'string') {
      if (/^\d+R\d*$/.test(item)) groups.add(item);
    } else if (Array.isArray(item)) {
      item.forEach(visit);
    } else if (item?.type === 'OCG' || item?.type === 'OCMD') {
      visit(item.id);
      visit(item.expression ?? item.ids);
    }
  };

  for (const [index, operator] of operators.fnArray.entries()) {
    if (operator !== beginMarkedContentProps) continue;
    const [tag, properties] = operators.argsArray[index] ?? [];
    if (tag === 'OC') visit(properties);
  }
  return groups;
}

const name = PDFName.of;
const optionalContent = name('OCProperties');

function applyLayerVisibility(doc, config) {
  if (config.hasInitialVisibility) return;
  const properties = doc.catalog.lookupMaybe(optionalContent, PDFDict);
  const defaultConfig = properties?.lookupMaybe(name('D'), PDFDict);
  const groups = properties?.lookupMaybe(name('OCGs'), PDFArray);
  if (!defaultConfig || !groups) return;

  const visible = [];
  const hidden = [];
  const edited = config.serializable.groupState;
  for (const groupRef of groups.asArray()) {
    if (!(groupRef instanceof PDFRef)) continue;
    const id = groupRef.objectNumber + 'R' + (groupRef.generationNumber || '');
    const group = config.getGroup(id);
    if (!group) continue;
    (group.visible ? visible : hidden).push(groupRef);
    if (!edited.get(id)?.userSet) continue;
    // A viewer may apply this usage hint after the default configuration.
    const definition = doc.context.lookupMaybe(groupRef, PDFDict);
    const usage = definition?.lookupMaybe(name('Usage'), PDFDict);
    const view = usage?.lookupMaybe(name('View'), PDFDict);
    if (view?.has(name('ViewState'))) {
      view.set(name('ViewState'), name(group.visible ? 'ON' : 'OFF'));
    }
  }
  defaultConfig.set(name('BaseState'), name('OFF'));
  defaultConfig.set(name('ON'), doc.context.obj(visible));
  defaultConfig.set(name('OFF'), doc.context.obj(hidden));
}

export async function saveLayered(bytes, config, pageNumber = null) {
  let source;
  try {
    source = await PDFDocument.load(bytes, { updateMetadata: false });
  } catch (error) {
    if (error instanceof EncryptedPDFError) {
      throw new Error('Encrypted PDFs support flattened PDF and PNG export.');
    }
    throw error;
  }
  applyLayerVisibility(source, config);
  if (pageNumber === null) {
    return source.save({ updateFieldAppearances: false });
  }

  const output = await PDFDocument.create({ updateMetadata: false });
  const original = source.getPage(pageNumber - 1);
  const copier = PDFObjectCopier.for(source.context, output.context);
  const page = copier.copy(original.node);
  const reference = output.context.register(page);
  output.addPage(PDFPage.of(page, reference, output));
  const layers = source.catalog.get(optionalContent);
  if (layers) output.catalog.set(optionalContent, copier.copy(layers));
  return output.save({ updateFieldAppearances: false });
}

export function rasterSize(width, height, dpi) {
  return [
    Math.max(1, Math.round(width * dpi / 72)),
    Math.max(1, Math.round(height * dpi / 72)),
  ];
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) {
      crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function pngWithResolution(bytes, dpi) {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const resolution = new Uint8Array(21);
  const chunk = new DataView(resolution.buffer);
  const pixelsPerMeter = Math.round(dpi / 0.0254);
  chunk.setUint32(0, 9);
  resolution.set([112, 72, 89, 115], 4); // pHYs
  chunk.setUint32(8, pixelsPerMeter);
  chunk.setUint32(12, pixelsPerMeter);
  resolution[16] = 1;
  chunk.setUint32(17, crc32(resolution.subarray(4, 17)));

  const chunks = [bytes.subarray(0, 8)];
  for (let offset = 8; offset + 12 <= bytes.length;) {
    const length = data.getUint32(offset);
    const type = data.getUint32(offset + 4);
    const end = offset + length + 12;
    if (end > bytes.length) throw new Error('Could not read the rendered PNG.');
    if (type !== 0x70485973) chunks.push(bytes.subarray(offset, end));
    if (type === 0x49484452) chunks.push(resolution);
    offset = end;
  }
  return new Blob(chunks, { type: 'image/png' });
}
