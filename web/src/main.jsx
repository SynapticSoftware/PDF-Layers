import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Check, ChevronDown, Download, FileText, FolderOpen, Layers3,
  LoaderCircle, LockKeyhole, ShieldCheck, Upload,
} from 'lucide-react';
import '@fontsource-variable/manrope';
import './styles.css';

const assets = import.meta.env.BASE_URL;
const pdfTools = () => import('./pdf-browser');
const formats = [
  { value: 'flattened', label: 'Flattened PDF' },
  { value: 'layered', label: 'Layered PDF' },
  { value: 'png', label: 'PNG' },
];

function Select({ label, value, options, disabled, onChange }) {
  return <label className="field">
    <span>{label}</span>
    <span className="select-wrap">
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option
          key={option.value} value={option.value} disabled={option.disabled}
        >{option.label}</option>)}
      </select>
      <ChevronDown size={15} aria-hidden="true" />
    </span>
  </label>;
}

function PageCanvas({ page, config, revision, onError }) {
  const frame = useRef(null);
  const canvas = useRef(null);
  const [size, setSize] = useState(null);

  useEffect(() => {
    const observe = new ResizeObserver(([box]) => {
      const { width, height } = box.contentRect;
      setSize((current) => current?.width === width && current?.height === height
        ? current : { width, height });
    });
    observe.observe(frame.current);
    return () => observe.disconnect();
  }, []);

  useEffect(() => {
    if (!size) return;
    const original = page.getViewport({ scale: 1 });
    const fit = Math.min(size.width / original.width, size.height / original.height);
    if (!(fit > 0)) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const viewport = page.getViewport({ scale: fit * dpr });
    const buffer = document.createElement('canvas');
    buffer.width = Math.ceil(viewport.width);
    buffer.height = Math.ceil(viewport.height);
    const task = page.render({
      canvas: buffer, viewport, background: '#ffffff',
      optionalContentConfigPromise: Promise.resolve(config),
    });
    let current = true;
    task.promise.then(() => {
      if (!current) return;
      const target = canvas.current;
      target.width = buffer.width;
      target.height = buffer.height;
      target.style.width = buffer.width / dpr + 'px';
      target.style.height = buffer.height / dpr + 'px';
      target.getContext('2d').drawImage(buffer, 0, 0);
    }).catch((error) => {
      if (current && error.name !== 'RenderingCancelledException') {
        onError('This page could not be previewed. ' + error.message);
      }
    }).finally(() => {
      buffer.width = buffer.height = 0;
    });
    return () => {
      current = false;
      task.cancel();
    };
  }, [page, config, revision, size, onError]);

  return <div ref={frame} className="page-frame">
    <canvas ref={canvas} aria-label={'PDF page ' + page.pageNumber} role="img" />
  </div>;
}

function PasswordDialog({ prompt, onCancel }) {
  const dialog = useRef(null);
  useEffect(() => { dialog.current.showModal(); }, []);
  return <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); onCancel(); }}>
    <form onSubmit={(event) => {
      event.preventDefault();
      prompt.submit(new FormData(event.currentTarget).get('password'));
    }}>
      <div className="dialog-icon"><LockKeyhole size={21} aria-hidden="true" /></div>
      <h2>Password-protected PDF</h2>
      <p>{prompt.incorrect ? 'That password was incorrect. Try again.' : 'Enter the password to open this file.'}</p>
      <label className="field">
        <span>Password</span>
        <input name="password" type="password" required autoFocus />
      </label>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
        <button type="submit" className="button primary">Open PDF</button>
      </div>
    </form>
  </dialog>;
}

function App() {
  const [session, setSession] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [pageData, setPageData] = useState(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [prompt, setPrompt] = useState(null);
  const [scope, setScope] = useState('all');
  const [format, setFormat] = useState('flattened');
  const [dpi, setDpi] = useState('300');
  const input = useRef(null);
  const activeOpen = useRef(null);
  const dragDepth = useRef(0);
  const page = pageData?.session === session && pageData.number === pageNumber ? pageData : null;
  const busy = loading || saving;
  const selectedScope = format === 'png' ? 'page' : scope;

  const browse = () => input.current.click();

  async function openFile(file, providedBytes) {
    if (activeOpen.current || saving) return;
    if (!providedBytes && !/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
      setError('Choose a PDF file.');
      return;
    }
    const attempt = { task: null };
    activeOpen.current = attempt;
    setLoading(true);
    setError('');
    setStatus('');
    try {
      const bytes = new Uint8Array(await (providedBytes ? providedBytes() : file.arrayBuffer()));
      const { loadPdf } = await pdfTools();
      let protectedPdf = false;
      attempt.task = loadPdf(bytes);
      attempt.task.onPassword = (submit, reason) => {
        if (activeOpen.current !== attempt) return;
        protectedPdf = true;
        setPrompt({ submit, incorrect: reason === 2 });
      };
      const pdf = await attempt.task.promise;
      const config = await pdf.getOptionalContentConfig();
      if (activeOpen.current !== attempt) return;
      setSession({ pdf, task: attempt.task, config, bytes, name: file.name, protectedPdf, layers: new Map() });
      setPageNumber(1);
      setPageData(null);
      if (protectedPdf && format === 'layered') setFormat('flattened');
    } catch (cause) {
      if (activeOpen.current === attempt) {
        setError('Could not open the PDF. ' + cause.message);
        void attempt.task?.destroy().catch(() => {});
      }
    } finally {
      if (activeOpen.current === attempt) {
        activeOpen.current = null;
        setLoading(false);
        setPrompt(null);
      }
    }
  }

  function cancelPassword() {
    const attempt = activeOpen.current;
    activeOpen.current = null;
    void attempt?.task?.destroy().catch(() => {});
    setLoading(false);
    setPrompt(null);
  }

  useEffect(() => () => {
    if (session) void session.task.destroy().catch(() => {});
  }, [session]);

  useEffect(() => {
    if (!session) return;
    let current = true;
    async function getPage() {
      try {
        const pdfPage = await session.pdf.getPage(pageNumber);
        let layers = session.layers.get(pageNumber);
        if (!layers) {
          const { layersForPage } = await pdfTools();
          layers = await layersForPage(pdfPage, session.config);
          session.layers.set(pageNumber, layers);
        }
        if (current) {
          setPageData({ session, number: pageNumber, pdfPage, layers });
        }
      } catch (cause) {
        if (current) setError('Could not load this page. ' + cause.message);
      }
    }
    void getPage();
    return () => { current = false; };
  }, [session, pageNumber]);

  function changePage(number) {
    if (busy || !session || number < 1 || number > session.pdf.numPages) return;
    setError('');
    setPageNumber(number);
  }

  function toggleLayer(id, visible) {
    session.config.setVisibility(id, visible);
    setRevision((version) => version + 1);
    setError('');
  }

  async function save() {
    if (!session || !page || busy) return;
    setSaving(true);
    setError('');
    setStatus('Preparing download…');
    const onlyPage = selectedScope === 'page' ? pageNumber : null;
    const base = session.name.replace(/\.pdf$/i, '');
    const suffix = onlyPage ? '-page-' + onlyPage : '';
    try {
      const { download, flattenPdf, saveLayered, savePng } = await pdfTools();
      if (format === 'png') {
        download(await savePng(page.pdfPage, session.config), base + suffix + '.png');
      } else if (format === 'layered') {
        const bytes = await saveLayered(session.bytes, session.config, onlyPage);
        download(new Blob([bytes], { type: 'application/pdf' }), base + suffix + '-layered.pdf');
      } else {
        const { bytes, reduced } = await flattenPdf(
          session.pdf, session.config, onlyPage, Number(dpi),
          (number, total) => setStatus('Flattening page ' + number + ' of ' + total + '…'),
        );
        download(new Blob([bytes], { type: 'application/pdf' }), base + suffix + '-flattened.pdf');
        if (reduced) {
          setStatus('Download started. Resolution was reduced on ' + reduced + ' large page(s).');
          return;
        }
      }
      setStatus('Download started.');
    } catch (cause) {
      setStatus('');
      setError('Could not export. ' + cause.message);
    } finally {
      setSaving(false);
    }
  }

  const filesDragged = (event) => Array.from(event.dataTransfer.types).includes('Files');

  return <div className="app"
    onDragEnter={(event) => {
      if (!filesDragged(event)) return;
      event.preventDefault();
      dragDepth.current++;
      if (!busy) setDragging(true);
    }}
    onDragOver={(event) => {
      if (!filesDragged(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
    }}
    onDragLeave={() => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (!dragDepth.current) setDragging(false);
    }}
    onDrop={(event) => {
      event.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      const file = event.dataTransfer.files[0];
      if (file && !busy) void openFile(file);
    }}>
    <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => {
      const file = event.currentTarget.files[0];
      event.currentTarget.value = '';
      if (file) void openFile(file);
    }} />
    <header className="masthead">
      <div className="brand">
        <div className="brand-mark"><img src={assets + 'icon.png'} alt="" /></div>
        <h1>PDF Layers</h1>
      </div>
      <div className="masthead-right">
        <span className="privacy"><ShieldCheck size={17} aria-hidden="true" /> Files stay on this device</span>
        <button className="button secondary" onClick={browse} disabled={busy}>
          <FolderOpen size={17} aria-hidden="true" /> Open PDF
        </button>
      </div>
    </header>

    <div className="workspace">
      <aside className="sidebar" aria-label="PDF controls">
        <section className="layers-panel" aria-labelledby="layers-heading">
          <div className="section-heading">
            <Layers3 size={19} aria-hidden="true" />
            <h2 id="layers-heading">Layers</h2>
            {page && <span className="count">{page.layers.length}</span>}
          </div>
          {!session && <p className="aside-note">Open a PDF to see its layers.</p>}
          {session && !page && <p className="aside-note">Reading page layers…</p>}
          {page?.layers.length === 0 && <p className="aside-note">This page has no layers.</p>}
          {!!page?.layers.length && <div className="layer-list">
            {page.layers.map(([id, group]) => <label className="layer-row" key={id}>
              <input type="checkbox" checked={group.visible} disabled={busy}
                onChange={(event) => toggleLayer(id, event.currentTarget.checked)} />
              <span className="checkbox-mark"><Check size={13} strokeWidth={3} aria-hidden="true" /></span>
              <span>{group.name || 'Layer ' + id}</span>
            </label>)}
          </div>}
        </section>

        <section className="export-panel" aria-labelledby="export-heading">
          <div className="section-heading">
            <Download size={18} aria-hidden="true" />
            <h2 id="export-heading">Export</h2>
          </div>
          <Select label="Pages" value={selectedScope} onChange={setScope} disabled={!session || busy || format === 'png'}
            options={[{ value: 'all', label: 'All pages' }, { value: 'page', label: 'Current page' }]} />
          <Select label="Format" value={format} onChange={setFormat} disabled={!session || busy}
            options={formats.map((item) => ({
              ...item, disabled: item.value === 'layered' && session?.protectedPdf,
            }))} />
          {format !== 'layered' && <Select label="Resolution" value={format === 'png' ? '300' : dpi}
            onChange={setDpi} disabled={!session || busy || format === 'png'}
            options={['150', '300', '600'].map((value) => ({ value, label: value + ' dpi' }))} />}
          {format === 'layered' && <p className="export-note">Keeps layers and your visibility settings.</p>}
          <button className="button primary export-button" disabled={!page || busy} onClick={() => void save()}>
            {saving ? <LoaderCircle size={17} className="spinner" aria-hidden="true" /> : <Download size={17} aria-hidden="true" />}
            {saving ? 'Preparing download' : 'Download'}
          </button>
        </section>
      </aside>

      <main className="viewer" aria-label="PDF preview">
        <div className="viewer-bar">
          <div className="file-heading">
            <FileText size={17} aria-hidden="true" />
            <span title={session?.name}>{session?.name ?? 'Preview'}</span>
          </div>
          <nav className="pagination" aria-label="Pages">
            <button className="button compact secondary" disabled={!session || busy || pageNumber === 1}
              onClick={() => changePage(pageNumber - 1)}>Previous</button>
            <span>{session ? 'Page ' + pageNumber + ' of ' + session.pdf.numPages : 'Page —'}</span>
            <button className="button compact secondary"
              disabled={!session || busy || pageNumber === session.pdf.numPages}
              onClick={() => changePage(pageNumber + 1)}>Next</button>
          </nav>
        </div>

        <div className={'stage' + (dragging ? ' dragging' : '')}>
          {page && <PageCanvas key={pageNumber + ':' + session.name}
            page={page.pdfPage} config={session.config} revision={revision} onError={setError} />}
          {!session && !loading && <div className="drop-card">
            <div className="drop-icon"><Upload size={27} strokeWidth={1.65} aria-hidden="true" /></div>
            <h2>Drop a PDF to begin</h2>
            <p>Choose a file to preview its layers and export pages.</p>
            <div className="drop-actions">
              <button className="button primary" onClick={browse}>Browse files</button>
              <button className="button text-button" onClick={() => void openFile(
                { name: 'Sample floor plan.pdf' },
                async () => {
                  const response = await fetch(assets + 'sample.pdf');
                  if (!response.ok) throw new Error('The sample file could not be loaded.');
                  return response.arrayBuffer();
                },
              )}>Try a sample</button>
            </div>
          </div>}
          {!page && (loading || (session && !error)) && <div className="stage-message">
            <LoaderCircle size={25} className="spinner" aria-hidden="true" />
            {loading ? 'Opening PDF…' : 'Loading page…'}
          </div>}
          {dragging && <div className="drop-overlay">
            <Upload size={32} aria-hidden="true" /><strong>Drop to open</strong>
          </div>}
        </div>
        {error ? <p className="message error" role="alert">{error}</p>
          : status && <p className="message" role="status">{status}</p>}
      </main>
    </div>
    {prompt && <PasswordDialog key={String(prompt.incorrect)} prompt={prompt} onCancel={cancelPassword} />}
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
