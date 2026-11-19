// DocLib 2.0 前端核心：DOM/图标/API/对话框
const ICONS = {
  files:'<path d="M5 2.8h6l4 4v10.4H5z"/><path d="M11 2.8v4h4"/><path d="M7.6 9.2h4.8M7.6 12h4.8"/>',
  search:'<circle cx="8.7" cy="8.7" r="4.3"/><path d="m12 12 4.2 4.2"/>',
  graph:'<circle cx="5" cy="6" r="2"/><circle cx="14.5" cy="4.8" r="1.8"/><circle cx="11" cy="14.5" r="2.2"/><path d="m6.8 5.5 6-.5M6.2 7.6l3.6 5.1M13.7 6.4l-1.9 6"/>',
  note:'<path d="M5 3h10v14H5z"/><path d="M7.5 7h5M7.5 10h5M7.5 13h3.2"/>',
  mind:'<circle cx="6" cy="10" r="2"/><circle cx="14" cy="5.5" r="1.7"/><circle cx="14" cy="14.5" r="1.7"/><path d="M8 9.3 12.3 6.3M8 10.7l4.3 3"/>',
  settings:'<circle cx="10" cy="10" r="2.4"/><path d="M10 2.8v2M10 15.2v2M2.8 10h2M15.2 10h2M5 5l1.4 1.4M13.6 13.6 15 15M15 5l-1.4 1.4M6.4 13.6 5 15"/>',
  theme:'<path d="M10 2.8a7.2 7.2 0 1 0 0 14.4z" fill="currentColor" opacity=".22"/><circle cx="10" cy="10" r="7.2"/>',
  plus:'<path d="M10 4v12M4 10h12"/>',
  close:'<path d="m5 5 10 10M15 5 5 15"/>',
  chevron:'<path d="m6 8 4 4 4-4"/>',
  right:'<path d="m7.5 4.5 5.5 5.5-5.5 5.5"/>',
  left:'<path d="M12.5 4.5 7 10l5.5 5.5"/>',
  filePdf:'<path d="M5 2.8h6l4 4v10.4H5z"/><path d="M11 2.8v4h4"/><path d="M7 13.5h6"/>',
  fileDoc:'<path d="M5 2.8h6l4 4v10.4H5z"/><path d="M11 2.8v4h4"/><path d="M7.5 9h5M7.5 12h5"/>',
  fileText:'<path d="M5 2.8h6l4 4v10.4H5z"/><path d="M11 2.8v4h4"/><path d="M7.5 9h5M7.5 12h5M7.5 15h3"/>',
  folder:'<path d="M3 6.2h5l1.6 1.8H17v8H3z"/><path d="M3 6.2V4.2h5.2l1.3 1.5"/>',
  send:'<path d="M3.5 10 16.5 3.5 13 16l-3.2-5.2z"/><path d="m9.8 10.8 3-3"/>',
  history:'<path d="M4.5 5.5A6.8 6.8 0 1 1 3.4 12"/><path d="M4.5 2.8v3.4h3.4M10 6.5V10l2.5 1.4"/>',
  external:'<path d="M11 4h5v5M16 4l-7 7"/><path d="M14 11v5H4V6h5"/>',
  refresh:'<path d="M16 10a6 6 0 1 1-1.8-4.3"/><path d="M16 3v4h-4"/>',
  fit:'<path d="M3 7V3h4M17 7V3h-4M3 13v4h4M17 13v4h-4"/>',
  filter:'<path d="M3 5h14M6 10h8M8 15h4"/>',
  trash:'<path d="M4 6h12M8 6V4h4v2M6 6l.8 10h6.4L14 6M8.5 9v4M11.5 9v4"/>',
  edit:'<path d="M4 14.5V17h2.5L16 7.5 12.5 4z"/><path d="m11 5.5 3.5 3.5"/>',
  more:'<circle cx="4" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="10" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="16" cy="10" r="1.2" fill="currentColor" stroke="none"/>',
  check:'<path d="m4 10 4 4 8-8"/>',
  alert:'<path d="M10 3 2.8 16h14.4z"/><path d="M10 8v3.5M10 14v.2"/>',
  pin:'<path d="m7 3 6 0-1 5 3 2H5l3-2z"/><path d="M10 10v7"/>',
  panelLeft:'<rect x="3" y="3.5" width="14" height="13" rx="1"/><path d="M8 3.5v13"/>',
  panelRight:'<rect x="3" y="3.5" width="14" height="13" rx="1"/><path d="M12 3.5v13"/>',
  book:'<path d="M3 4.5c2.6-1 4.6-1 6.5 0v11c-1.9-1-3.9-1-6.5 0z"/><path d="M17 4.5c-2.6-1-4.6-1-6.5 0v11c1.9-1 3.9-1 6.5 0z"/>',
  link:'<path d="M8.5 11.5 11.5 8.5"/><path d="M7 13H5.8a3.8 3.8 0 0 1 0-7.6H8M13 7h1.2a3.8 3.8 0 0 1 0 7.6H12"/>',
  zoomIn:'<circle cx="8.7" cy="8.7" r="4.3"/><path d="m12 12 4.2 4.2M8.7 6.7v4M6.7 8.7h4"/>',
  zoomOut:'<circle cx="8.7" cy="8.7" r="4.3"/><path d="m12 12 4.2 4.2M6.7 8.7h4"/>',
  bookOpen:'<path d="M3 4.5c2.6-1 4.6-1 6.5 0v11c-1.9-1-3.9-1-6.5 0zM17 4.5c-2.6-1-4.6-1-6.5 0v11c1.9-1 3.9-1 6.5 0z"/>',
  spark:'<path d="M10 2.5 11.6 8 17 9.6 11.6 11.2 10 16.8 8.4 11.2 3 9.6 8.4 8z"/>',
  copy:'<rect x="6" y="6" width="9" height="10" rx="1"/><path d="M4 13V4h9"/>',
  eye:'<path d="M2.5 10s2.8-5 7.5-5 7.5 5 7.5 5-2.8 5-7.5 5-7.5-5-7.5-5z"/><circle cx="10" cy="10" r="2"/>',
  dots:'<circle cx="5" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="10" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="10" r="1.2" fill="currentColor" stroke="none"/>'
};

export function icon(name, cls = '') {
  const p = ICONS[name] || ICONS.dots;
  return `<svg class="icon ${cls}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}

export function el(tag, props = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = String(v);
    else if (k === 'html') n.innerHTML = v; // only trusted icon/markdown output
    else if (k === 'dataset') Object.assign(n.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') n.value = v;
    else if (k === 'checked') n.checked = !!v;
    else n.setAttribute(k, String(v));
  }
  for (const c of [].concat(children || [])) {
    if (c == null || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

export function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

export function on(target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  return () => target.removeEventListener(type, fn, opts);
}

export function debounce(fn, ms = 300) {
  let t = 0;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function uid(prefix = 't') {
  return `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/* ---------------- API ---------------- */
const BASE = '';
async function request(path, { method = 'GET', body = null, timeout = 60000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const opt = { method, signal: ctrl.signal, headers: {} };
    if (body !== null) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(BASE + path, opt);
    const txt = await res.text();
    let data = null;
    try { data = txt ? JSON.parse(txt) : null; } catch { data = { ok: false, error: txt.slice(0, 300) }; }
    if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
    return data;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('请求超时');
    throw e;
  } finally { clearTimeout(timer); }
}
export const api = {
  get: (path, params) => {
    if (params) {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, v);
      const s = q.toString(); if (s) path += (path.includes('?') ? '&' : '?') + s;
    }
    return request(path);
  },
  post: (path, body = {}) => request(path, { method: 'POST', body }),
  raw: request,
};

/* ---------------- format ---------------- */
export function fmtSize(n) {
  n = Number(n || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
export function fmtTime(ms) {
  if (!ms) return '';
  const d = new Date(Number(ms));
  const p = x => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
export function timeAgo(ms) {
  const t = Number(ms || 0); if (!t) return '';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
  return fmtTime(t).slice(0, 10);
}
export function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------------- toast ---------------- */
let toastWrap = null;
export function toast(msg, { error = false, ms = 2600 } = {}) {
  if (!toastWrap) {
    toastWrap = el('div', { class: 'toast-wrap' });
    document.body.append(toastWrap);
  }
  const t = el('div', { class: `toast${error ? ' error' : ''}`, text: String(msg || '') });
  toastWrap.append(t);
  requestAnimationFrame(() => t.classList.add('show'));
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 200); }, ms);
  return t;
}

/* ---------------- menus/dialogs ---------------- */
let openMenus = [];
export function closeMenus() {
  for (const m of openMenus) m.remove();
  openMenus = [];
}
export function menu(x, y, items) {
  closeMenus();
  const m = el('div', { class: 'menu' });
  for (const it of items) {
    if (it.sep) { m.append(el('div', { class: 'sep' })); continue; }
    const row = el('div', { class: `mi${it.danger ? ' danger' : ''}${it.disabled ? ' disabled' : ''}` }, [
      it.icon ? el('span', { html: icon(it.icon) }) : null,
      el('span', { text: it.label }),
      it.kbd ? el('span', { class: 'k', text: it.kbd }) : null,
    ]);
    if (!it.disabled) row.addEventListener('click', () => { closeMenus(); it.onClick && it.onClick(); });
    m.append(row);
  }
  document.body.append(m);
  const r = m.getBoundingClientRect();
  m.style.left = `${Math.max(6, Math.min(x, innerWidth - r.width - 8))}px`;
  m.style.top = `${Math.max(6, Math.min(y, innerHeight - r.height - 8))}px`;
  openMenus.push(m);
  setTimeout(() => {
    const off = e => {
      if (!m.contains(e.target)) { closeMenus(); document.removeEventListener('mousedown', off); }
    };
    document.addEventListener('mousedown', off);
  }, 0);
  return m;
}

export function modal({ title, body, foot, width = null, onClose = null }) {
  const mask = el('div', { class: 'modal-mask' });
  const box = el('div', { class: 'modal', style: width ? { width } : {} });
  const close = () => {
    mask.remove();
    document.removeEventListener('keydown', esc);
    onClose && onClose();
  };
  const esc = e => { if (e.key === 'Escape') close(); };
  box.append(el('h3', { text: title || '' }));
  const b = el('div', { class: 'body' });
  if (body instanceof Node) b.append(body); else b.append(el('div', { text: body || '' }));
  box.append(b);
  const f = el('div', { class: 'foot' });
  if (foot) {
    for (const item of foot) {
      if (item.spacer) { f.append(el('span', { class: 'spacer' })); continue; }
      const btn = el('button', { class: `btn${item.primary ? ' primary' : ''}${item.danger ? ' danger' : ''}`, text: item.label });
      btn.addEventListener('click', () => item.onClick ? item.onClick(close, b) : close());
      f.append(btn);
    }
  } else {
    const btn = el('button', { class: 'btn', text: '关闭' });
    btn.addEventListener('click', close);
    f.append(btn);
  }
  box.append(f);
  mask.append(box);
  mask.addEventListener('mousedown', e => { if (e.target === mask) close(); });
  document.addEventListener('keydown', esc);
  document.body.append(mask);
  setTimeout(() => {
    const target = box.querySelector('input,textarea,select,button');
    target && target.focus();
  }, 20);
  return { mask, box, body: b, close };
}

export function confirmDialog(title, message, { danger = false, okText = '确认' } = {}) {
  return new Promise(resolve => {
    const d = modal({
      title, body: message,
      foot: [
        { label: '取消', onClick: (close) => { close(); resolve(false); } },
        { label: okText, primary: !danger, danger, onClick: (close) => { close(); resolve(true); } },
      ],
      onClose: () => resolve(false),
    });
    d.mask.querySelector('.btn.primary,.btn.danger')?.addEventListener('click', () => resolve(true), { once: true });
  });
}

export function promptDialog({ title, label = '', value = '', placeholder = '', okText = '保存' }) {
  return new Promise(resolve => {
    const input = el('input', { class: 'input', value, placeholder });
    const body = el('div', { class: 'field' }, [label ? el('label', { text: label }) : null, input]);
    const d = modal({
      title, body,
      foot: [
        { label: '取消', onClick: (close) => { close(); resolve(null); } },
        { label: okText, primary: true, onClick: (close) => { close(); resolve(input.value.trim()); } },
      ],
      onClose: () => resolve(null),
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { const v = input.value.trim(); d.close(); resolve(v); }
    });
    setTimeout(() => { input.focus(); input.select(); }, 30);
  });
}

/* ---------------- markdown ---------------- */
export function markdown(text, { wikilink = false } = {}) {
  const src = String(text || '');
  let html = '';
  try {
    if (window.marked) {
      window.marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });
      html = window.marked.parse(src);
    } else {
      html = `<pre>${escapeHtml(src)}</pre>`;
    }
  } catch { html = `<pre>${escapeHtml(src)}</pre>`; }
  if (wikilink) {
    html = html.replace(/\[\[([^\]]+)\]\]/g, (m, inner) => {
      const [target, alias] = inner.split('|');
      return `<a class="wikilink" data-wikilink="${escapeHtml(target)}">${escapeHtml(alias || target)}</a>`;
    });
  }
  if (window.DOMPurify) html = window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true }, ADD_ATTR: ['data-wikilink'] });
  return html;
}

export function highlightTerms(text, terms) {
  let safe = escapeHtml(text);
  for (const t of (terms || []).filter(Boolean).sort((a, b) => b.length - a.length)) {
    try {
      const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
      safe = safe.replace(re, m => `<mark>${m}</mark>`);
    } catch {}
  }
  return safe;
}

export function fileIcon(type) {
  const t = String(type || '').toLowerCase();
  if (t.includes('pdf')) return 'filePdf';
  if (t.includes('doc')) return 'fileDoc';
  if (t.includes('md') || t.includes('txt')) return 'fileText';
  return 'fileText';
}
