// 中央工作区视图：graph / reader / note / node / search / settings / mindmap / welcome
import {
  el, clear, icon, api, toast, modal, confirmDialog, markdown, escapeHtml,
  fmtSize, fmtTime, timeAgo, fileIcon, highlightTerms,
} from './core.js';
import { openTab, save } from './workspace.js';

const POS_KEY = 'doclib.graph.positions.v1';

export async function renderView(tab, host, state, actions) {
  clear(host);
  switch (tab.kind) {
    case 'graph': return renderGraph(tab, host, state, actions);
    case 'doc': return renderReader(tab, host, state, actions);
    case 'note': return renderNote(tab, host, state, actions);
    case 'node': return renderNode(tab, host, state, actions);
    case 'search': return renderSearch(tab, host, state, actions);
    case 'settings': return renderSettings(tab, host, state, actions);
    case 'mindmap': return renderMindmapTab(tab, host, state, actions);
    default: return renderWelcome(host, state, actions);
  }
}

function loading(host, text = '正在读取…') {
  clear(host);
  host.append(el('div', { class: 'empty' }, [
    el('div', { class: 'loading-line' }, [el('span', { class: 'spin' }), el('span', { text })]),
  ]));
}

function errorView(host, message, actions, retry = null) {
  clear(host);
  host.append(el('div', { class: 'empty' }, [
    el('span', { html: icon('alert') }),
    el('h3', { text: '这里暂时读不出来' }),
    el('p', { text: message || '未知错误' }),
    el('div', { class: 'actions' }, [
      retry ? el('button', { class: 'btn', text: '重试', onClick: retry }) : null,
      el('button', { class: 'btn', text: '打开设置', onClick: () => actions.openSettings() }),
    ]),
  ]));
}

function viewHead(title, meta = '', actions = []) {
  const head = el('div', { class: 'view-head' });
  head.append(el('span', { class: 'title', text: title || '' }));
  if (meta) head.append(el('span', { class: 'meta', text: meta }));
  head.append(el('div', { class: 'spacer', style: { flex: 1 } }));
  for (const a of actions) {
    if (!a) continue;
    const b = el('button', { class: `btn${a.primary ? ' primary' : ''} icon`, title: a.title || a.label, html: a.icon ? icon(a.icon) : '' });
    if (!a.icon) b.textContent = a.label;
    b.addEventListener('click', a.onClick);
    head.append(b);
  }
  return head;
}

/* ================= graph ================= */
async function renderGraph(tab, host, state, actions) {
  const view = el('div', { class: 'graph-view' });
  const canvas = el('div', { class: 'graph-canvas', id: 'cy' });
  const tools = el('div', { class: 'graph-tools' });
  const inspector = el('div', { class: 'graph-inspector', hidden: true });
  const legend = el('div', { class: 'graph-legend' });
  const empty = el('div', { class: 'graph-empty', hidden: true });
  const tip = el('div', { class: 'graph-tip', text: '滚轮缩放 · 拖动平移 · 双击节点打开 · 拖动节点固定' });
  view.append(canvas, tools, inspector, legend, empty, tip);
  host.append(view);

  let cy = null;
  let graph = null;
  let selected = null;
  let dataById = new Map();
  let savePos = null;
  try { savePos = JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch { savePos = {}; }

  const p = tab.params || {};
  let scope = p.scope === 'local' ? 'local' : 'global';
  let center = p.center || centerFromActive(state);
  if (scope === 'local' && !center) scope = 'global';
  let depth = Number(p.depth || 1) || 1;
  let q = p.q || '';
  let types = new Set((p.types || ['node', 'document', 'note']));
  let rels = new Set((p.rels || ['hierarchy', 'mount', 'manual', 'wikilink']));

  renderTools();
  renderLegend();
  await load();

  function centerFromActive(st) {
    const e = st.activeEntity;
    if (!e) return '';
    return `${e.kind === 'doc' ? 'document' : e.kind}:${e.id}`;
  }

  function renderTools() {
    clear(tools);
    tools.append(el('p', { class: 'lab', text: '图谱筛选' }));
    const seg = el('div', { class: 'seg' });
    for (const [k, label] of [['global', '全局'], ['local', '局部']]) {
      const b = el('button', { class: scope === k ? 'on' : '', text: label });
      b.addEventListener('click', () => {
        if (k === 'local' && !center) { toast('先在资料库/图谱中选中一个节点或资料'); return; }
        scope = k; tab.params.scope = k; tab.params.center = center || null;
        renderTools(); load(); save(state.workspace);
      });
      seg.append(b);
    }
    tools.append(seg);
    const inp = el('input', { class: 'input', placeholder: '在图谱中搜索…', value: q });
    let qt = 0;
    inp.addEventListener('input', () => { clearTimeout(qt); qt = setTimeout(() => { q = inp.value.trim(); tab.params.q = q; save(state.workspace); load(); }, 350); });
    tools.append(inp);
    tools.append(el('div', { class: 'divider' }));
    const typeLabels = [['node', '知识节点', '--n1'], ['document', '资料', '--node-doc'], ['note', '笔记', '--cue']];
    for (const [k, label, color] of typeLabels) {
      tools.append(checkRow(label, types.has(k), v => { toggle(types, k, v); tab.params.types = [...types]; save(state.workspace); load(); }, color));
    }
    tools.append(el('div', { class: 'divider' }));
    for (const [k, label] of [['hierarchy', '上下级'], ['mount', '资料归属'], ['manual', '人工关联'], ['wikilink', '笔记双链']]) {
      tools.append(checkRow(label, rels.has(k), v => { toggle(rels, k, v); tab.params.rels = [...rels]; save(state.workspace); load(); }));
    }
    tools.append(el('div', { class: 'divider' }));
    const rg = el('div', { class: 'range' });
    rg.append(el('span', { text: '局部跳数' }));
    const r = el('input', { type: 'range', min: '1', max: '3', value: String(depth) });
    r.addEventListener('input', () => { depth = Number(r.value); tab.params.depth = depth; save(state.workspace); if (scope === 'local') load(); });
    rg.append(r, el('span', { text: `${depth}` }));
    tools.append(rg);
    const actionsRow = el('div', { class: 'row', style: { marginTop: '6px' } }, [
      el('button', { class: 'btn sm', text: '适应', onClick: fit }),
      el('button', { class: 'btn sm', text: '重置布局', onClick: rerunLayout }),
      el('button', { class: 'btn sm', text: '刷新', onClick: load }),
    ]);
    tools.append(actionsRow);
  }

  function checkRow(label, checked, onChange, color) {
    const wrap = el('label', { class: 'check row' });
    const input = el('input', { type: 'checkbox', checked });
    input.addEventListener('change', () => onChange(input.checked));
    wrap.append(input);
    if (color) wrap.append(el('span', { class: 'sw', style: { background: `var(${color})` } }));
    wrap.append(el('span', { text: label }));
    return wrap;
  }
  function toggle(set, k, v) { if (v) set.add(k); else set.delete(k); }

  function renderLegend() {
    clear(legend);
    legend.append(liDot('var(--n1)', '知识节点'));
    legend.append(liHollow('资料'));
    legend.append(liSquare('var(--cue)', '笔记'));
    legend.append(liLine('关联 / 归属'));
    legend.append(liLine('上下级（虚线）', true));
  }
  function liDot(c, t) { return el('div', { class: 'li' }, [el('span', { class: 'd', style: { background: c } }), el('span', { text: t })]); }
  function liHollow(t) { return el('div', { class: 'li' }, [el('span', { class: 'd', style: { border: '1px solid var(--ink-3)' } }), el('span', { text: t })]); }
  function liSquare(c, t) { return el('div', { class: 'li' }, [el('span', { class: 'sq', style: { background: c } }), el('span', { text: t })]); }
  function liLine(t, dashed) { return el('div', { class: 'li' }, [el('span', { class: 'ln', style: dashed ? { borderTop: '1px dashed var(--ink-3)', background: 'none' } : {} }), el('span', { text: t })]); }

  async function load() {
    clear(inspector); inspector.hidden = true; selected = null;
    if (scope === 'local' && !center) { toast('需要先选中一个节点或资料'); scope = 'global'; }
    empty.hidden = true;
    const params = {
      scope, partition: state.partitionId, depth,
      types: [...types].join(','), rels: [...rels].join(','),
      q, limit: scope === 'global' ? 1500 : 800,
    };
    if (scope === 'local') params.center = center;
    try {
      const r = await api.get('/api/v2/graph', params);
      if (!r || r.ok === false) throw new Error((r && r.error) || '图谱读取失败');
      graph = r;
      draw(r);
    } catch (e) {
      errorView(host, e.message, actions, load);
      // 恢复容器（errorView 清空了 host）
      host.append(view);
    }
  }

  function draw(data) {
    if (cy) { cy.destroy(); cy = null; }
    dataById = new Map((data.nodes || []).map(n => [n.id, n]));
    const css = getComputedStyle(document.documentElement);
    const v = k => css.getPropertyValue(k).trim();
    const maxDeg = Math.max(1, ...data.nodes.map(n => n.degree || 0));
    const palette = ['--n1', '--n2', '--n3', '--n4', '--n5', '--n6'];
    const elements = [];
    for (const n of data.nodes || []) {
      const isDoc = n.kind === 'document';
      const isNote = n.kind === 'note';
      const color = isDoc ? v('--node-doc') : isNote ? v('--node-note') : v(palette[(Number(n.partition_id || 0) - 1 + palette.length) % palette.length]);
      const size = isDoc ? 5 : isNote ? 5 : Math.min(22, 6 + 10 * Math.sqrt((n.degree || 0) / maxDeg));
      elements.push({ data: { ...n, color, size, label: n.label || '' } });
    }
    for (const e of data.edges || []) {
      elements.push({ data: { ...e, id: e.id || `${e.source}|${e.rel}|${e.target}` } });
    }
    try {
      if (window.cytoscapeFcose && !window.__doclibFcoseUsed) {
        window.cytoscape.use(window.cytoscapeFcose);
        window.__doclibFcoseUsed = true;
      }
    } catch (e) { console.warn('fcose register failed', e); }
    cy = window.cytoscape({
      container: document.getElementById('cy'),
      elements,
      wheelSensitivity: 0.18,
      minZoom: 0.05,
      maxZoom: 3,
      style: [
        { selector: 'node', style: {
          'background-color': 'data(color)', width: 'data(size)', height: 'data(size)',
          label: 'data(label)', 'font-family': v('--font-ui'), 'font-size': 10,
          color: v('--ink-2'), 'text-valign': 'bottom', 'text-margin-y': 4,
          'text-background-color': v('--graph-bg'), 'text-background-opacity': .76,
          'text-background-padding': '1px', 'text-opacity': 0, 'min-zoomed-font-size': 7,
          'text-wrap': 'wrap', 'text-max-width': '150px',
          'overlay-opacity': 0, 'border-width': 0,
          'transition-property': 'opacity, border-width', 'transition-duration': 120,
        }},
        { selector: 'node[kind="document"]', style: { 'background-opacity': 0, 'border-width': 1, 'border-color': v('--ink-3'), shape: 'ellipse' } },
        { selector: 'node[kind="note"]', style: { shape: 'round-rectangle', 'border-width': 1, 'border-color': v('--cue') } },
        { selector: 'node.show-label', style: { 'text-opacity': 1, 'border-width': 2, 'border-color': v('--accent') } },
        { selector: 'node.selected', style: { 'border-width': 3, 'border-color': v('--accent'), 'overlay-color': v('--accent'), 'overlay-opacity': .12, 'overlay-padding': 5 } },
        { selector: 'node.dim', style: { opacity: .25, 'text-opacity': 0 } },
        { selector: 'edge', style: {
          width: .8, 'line-color': v('--ink-3'), opacity: .18, 'curve-style': 'bezier',
          'target-arrow-shape': 'none', 'arrow-scale': .6,
        }},
        { selector: 'edge[rel="hierarchy"]', style: { 'line-style': 'dashed', opacity: .14 } },
        { selector: 'edge[rel="mount"]', style: { opacity: .20 } },
        { selector: 'edge[rel="manual"]', style: { 'line-color': v('--accent'), opacity: .36, width: 1.1 } },
        { selector: 'edge[rel="wikilink"]', style: { 'line-style': 'dotted', 'line-color': v('--cue'), opacity: .34 } },
        { selector: 'edge.hot', style: { opacity: .65, width: 1.2 } },
        { selector: 'edge.dim', style: { opacity: .05 } },
      ],
      layout: { name: 'preset' },
    });
    if (!cy) { errorView(host, 'Cytoscape 未加载', actions); return; }
    window.__doclibCy = cy;
    // 大图只给最重要的实体常显标签；其余 hover/选中显示，避免文字互相压住
    const labelNodes = Array.from(cy.nodes()).filter(n => n.data('kind') !== 'document')
      .sort((a, b) => (b.data('degree') || 0) - (a.data('degree') || 0));
    labelNodes.slice(0, 42).forEach(n => n.addClass('show-label'));
    cy.on('zoom', () => {
      const z = cy.zoom();
      if (z > 1.25) labelNodes.forEach(n => n.addClass('show-label'));
      else if (z < 0.75) labelNodes.slice(42).forEach(n => n.removeClass('show-label'));
    });
    const saved = savePos || {};
    cy.nodes().forEach(n => { const p = saved[n.id()]; if (p && Number.isFinite(p.x)) n.position(p); });
    cy.on('tap', 'node', evt => selectNode(evt.target));
    cy.on('dbltap', 'node', evt => openNode(evt.target.data()));
    cy.on('tap', evt => { if (evt.target === cy) clearSelection(); });
    cy.on('mouseover', 'node', evt => hoverNode(evt.target));
    cy.on('mouseout', 'node', () => { cy.nodes().removeClass('dim'); cy.edges().removeClass('dim hot'); });
    cy.on('dragfree', 'node', evt => {
      const n = evt.target;
      const positions = {};
      try { Object.assign(positions, JSON.parse(localStorage.getItem(POS_KEY) || '{}')); } catch {}
      positions[n.id()] = { x: n.position('x'), y: n.position('y') };
      localStorage.setItem(POS_KEY, JSON.stringify(positions));
    });
    if (data.truncated) {
      empty.hidden = false;
      clear(empty);
      empty.append(el('div', { class: 'box' }, [
        el('h3', { text: '图谱较大，已截断' }),
        el('p', { class: 'hint', text: `当前显示 ${data.stats?.nodes || 0} / ${data.stats?.total_nodes || 0} 个节点。建议切到当前分区或局部图谱。` }),
      ]));
    }
    runLayout(true);
  }

  function runLayout(force = true) {
    if (!cy) return;
    const hasFcose = typeof window.cytoscapeFcose !== 'undefined';
    const name = hasFcose ? 'fcose' : 'cose';
    const opts = name === 'fcose' ? {
      name, animate: false, randomize: force, quality: 'default',
      nodeSeparation: 110, idealEdgeLength: 120, nodeRepulsion: 9000,
      gravity: 0.25, packComponents: true,
      fit: true, padding: 60, numIter: 1400,
    } : {
      name, animate: false, randomize: force, fit: true, padding: 40,
      nodeRepulsion: 400000, idealEdgeLength: 80, numIter: 1000,
    };
    try {
      const lay = cy.layout(opts);
      lay.one('layoutstop', () => {
        try {
          cy.resize(); cy.fit(cy.elements(), 70);
          if (cy.zoom() > 1.15) { cy.zoom(1.15); cy.center(cy.elements()); }
        } catch {}
      });
      lay.run();
    } catch (e) {
      console.warn('layout failed', e);
      try {
        const lay = cy.layout({ name: 'cose', animate: false, fit: true, padding: 70 });
        lay.one('layoutstop', () => {
          try { cy.resize(); cy.fit(cy.elements(), 70); if (cy.zoom() > 1.15) { cy.zoom(1.15); cy.center(cy.elements()); } } catch {}
        });
        lay.run();
      } catch {}
    }
  }

  function fit() { if (cy) cy.fit(undefined, 40); }
  function rerunLayout() { runLayout(true); }

  function selectNode(n) {
    if (!cy) return;
    cy.nodes().removeClass('selected dim show-label');
    cy.edges().removeClass('hot dim');
    n.addClass('selected show-label');
    const nb = n.closedNeighborhood();
    cy.nodes().not(nb.nodes()).addClass('dim');
    cy.edges().not(nb.edges()).addClass('dim');
    nb.edges().addClass('hot');
    nb.nodes().addClass('show-label');
    selected = n.data();
    renderInspector(selected);
    actions.setActiveEntity && actions.setActiveEntity({ kind: selected.kind, id: selected.entity_id, title: selected.label });
  }
  function clearSelection() {
    if (!cy) return;
    cy.nodes().removeClass('selected dim show-label');
    cy.edges().removeClass('hot dim');
    selected = null; inspector.hidden = true;
  }
  function hoverNode(n) {
    if (!cy) return;
    cy.nodes().removeClass('dim'); cy.edges().removeClass('dim hot');
    const nb = n.closedNeighborhood();
    cy.nodes().not(nb.nodes()).addClass('dim');
    cy.edges().not(nb.edges()).addClass('dim');
    nb.edges().addClass('hot');
    nb.nodes().addClass('show-label');
  }
  function renderInspector(d) {
    if (!d) return;
    clear(inspector);
    inspector.hidden = false;
    const kind = d.kind === 'node' ? '知识节点' : d.kind === 'document' ? '资料' : '笔记';
    inspector.append(el('div', { class: 'kind' }, [el('span', { class: 'd' }), el('span', { text: kind })]));
    inspector.append(el('h3', { text: d.label || d.id }));
    const meta = d.meta || {};
    const path = meta.path || meta.file_path || '';
    if (path) inspector.append(el('div', { class: 'path', text: path }));
    const deg = d.degree || 0;
    const stats = el('div', { class: 'stats' });
    stats.append(stat('相连', deg));
    if (d.kind === 'node') stats.append(stat('资料', meta.doc_count || 0));
    stats.append(stat(d.kind === 'document' ? '资料' : d.kind === 'note' ? '笔记' : '知识节点', '类型'));
    inspector.append(stats);
    const acts = el('div', { class: 'actions' });
    if (d.kind === 'document') {
      acts.append(el('button', { class: 'btn primary', text: '打开资料', onClick: () => actions.openDoc(d.entity_id, d.label) }));
      acts.append(el('button', { class: 'btn', text: '局部图谱', onClick: () => actions.openGraph({ scope: 'local', center: d.id, title: d.label }) }));
      acts.append(el('button', { class: 'btn', text: '问 AI', onClick: () => actions.askWithContext({ kind: 'document', doc_id: d.entity_id, label: `当前文档 · ${d.label}` }) }));
    } else if (d.kind === 'note') {
      acts.append(el('button', { class: 'btn primary', text: '打开笔记', onClick: () => actions.openNote(d.entity_id, d.label) }));
      acts.append(el('button', { class: 'btn', text: '局部图谱', onClick: () => actions.openGraph({ scope: 'local', center: d.id, title: d.label }) }));
      acts.append(el('button', { class: 'btn', text: '问 AI', onClick: () => actions.askWithContext({ kind: 'note', note_id: d.entity_id, label: `当前笔记 · ${d.label}` }) }));
    } else {
      acts.append(el('button', { class: 'btn primary', text: '打开节点', onClick: () => actions.openNode(d.entity_id, d.label) }));
      acts.append(el('button', { class: 'btn', text: '局部图谱', onClick: () => actions.openGraph({ scope: 'local', center: d.id, title: d.label }) }));
      acts.append(el('button', { class: 'btn', text: '问 AI', onClick: () => actions.askWithContext({ kind: 'node', node_id: d.entity_id, label: `当前节点 · ${d.label}` }) }));
    }
    inspector.append(acts);
    const neighbors = (graph?.edges || []).filter(e => e.source === d.id || e.target === d.id).slice(0, 8);
    if (neighbors.length) {
      const box = el('div', { class: 'neighbors' });
      box.append(el('div', { class: 'x', style: { fontFamily: 'var(--font-mono)', fontSize: '8.5px', color: 'var(--ink-3)', marginBottom: '4px' }, text: '相连实体' }));
      for (const e of neighbors) {
        const otherId = e.source === d.id ? e.target : e.source;
        const other = dataById.get(otherId);
        if (!other) continue;
        const row = el('div', { class: 'nb' }, [el('span', { class: 'd', style: { background: other.kind === 'document' ? 'var(--node-doc)' : other.kind === 'note' ? 'var(--cue)' : 'var(--accent)' } }), el('span', { text: other.label })]);
        row.addEventListener('click', () => {
          const n = cy.getElementById(otherId);
          if (n && n.length) { cy.center(n); selectNode(n); }
        });
        box.append(row);
      }
      inspector.append(box);
    }
  }
  function stat(label, val) { return el('div', {}, [el('b', { text: String(val) }), el('span', { text: label })]); }
  function openNode(d) {
    if (d.kind === 'document') actions.openDoc(d.entity_id, d.label);
    else if (d.kind === 'note') actions.openNote(d.entity_id, d.label);
    else actions.openNode(d.entity_id, d.label);
  }

  // 清理：host 被替换时销毁 cy，避免 canvas 泄漏
  const obs = new MutationObserver(() => { if (!document.body.contains(host)) { try { cy && cy.destroy(); } catch {} obs.disconnect(); } });
  obs.observe(document.getElementById('app') || document.body, { childList: true, subtree: true });
}

/* ================= reader ================= */
async function renderReader(tab, host, state, actions) {
  const docId = Number(tab.params.docId);
  if (!docId) { errorView(host, '缺少文档 id', actions); return; }
  try { if (window.CSS && CSS.highlights) CSS.highlights.clear(); } catch {}
  loading(host, '正在读取文档…');
  let r;
  try {
    r = await api.get(`/api/v2/reader/${docId}`, { around: tab.params.chunkId || undefined, limit: 300 });
    if (!r || r.ok === false) throw new Error((r && r.error) || '文档读取失败');
  } catch (e) { errorView(host, e.message, actions, () => renderReader(tab, host, state, actions)); return; }

  clear(host);
  const doc = r.doc || {};
  const chunks = r.chunks || [];
  const view = el('div', { class: 'reader' });
  let tocOpen = innerWidth >= 1600;
  view.classList.toggle('toc-closed', !tocOpen);
  const head = el('div', { class: 'reader-head' });
  const kind = el('div', { class: 'reader-kind' });
  kind.append(el('span', { class: 'd' }));
  kind.append(el('span', { text: String(doc.file_type || '').toUpperCase() }));
  kind.append(el('span', { class: 'sep' }));
  kind.append(el('span', { text: (doc.nodes || []).map(n => n.name).join(' / ') || '未挂载' }));
  kind.append(el('span', { class: 'sep' }));
  kind.append(el('span', { text: `${chunks.length}${r.has_more ? '+' : ''} 块` }));
  head.append(kind);
  head.append(el('h1', { class: 'reader-title', text: doc.title || tab.title || '资料' }));
  const meta = el('div', { class: 'reader-meta' });
  meta.append(el('span', { class: 'path', text: doc.file_path || '' }));
  meta.append(el('span', { text: fmtSize(doc.file_size) }));
  if (doc.parse_status === 2) meta.append(el('span', { text: '已索引' }));
  head.append(meta);
  const acts = el('div', { class: 'reader-actions' });
  const focus = el('button', { class: 'btn primary', text: '问 AI 这篇资料', onClick: () => { actions.focusAI(); } });
  acts.append(focus);
  acts.append(el('button', { class: 'btn', text: '打开原文件', onClick: () => openOriginal(docId) }));
  acts.append(el('button', { class: 'btn', text: '局部图谱', onClick: () => actions.openGraph({ scope: 'local', center: `document:${docId}`, title: doc.title }) }));
  acts.append(el('button', { class: 'btn', text: '反向链接', onClick: () => showBacklinks('document', docId, actions) }));
  const tocBtn = el('button', { class: `btn${tocOpen ? ' primary' : ''}`, text: '目录' });
  tocBtn.addEventListener('click', () => {
    tocOpen = !tocOpen;
    view.classList.toggle('toc-closed', !tocOpen);
    tocBtn.classList.toggle('primary', tocOpen);
  });
  acts.append(tocBtn);
  head.append(acts);
  view.append(head);

  const main = el('div', { class: 'reader-main' });
  const toc = el('div', { class: 'reader-toc' });
  toc.append(el('div', { class: 'lab', text: '目录' }));
  const docPane = el('div', { class: 'reader-doc' });
  const inner = el('div', { class: 'reader-inner' });
  const body = el('div', { class: 'reader-body' });
  inner.append(body);
  docPane.append(inner);
  main.append(toc, docPane);
  view.append(main);
  host.append(view);

  const isPdf = String(doc.file_type || '').toLowerCase() === 'pdf';
  const isText = ['md', 'markdown', 'txt'].includes(String(doc.file_type || '').toLowerCase());
  let raw = null;
  if (isText) {
    try { raw = await api.get(`/api/v2/raw/${docId}`); } catch { raw = null; }
  }

  if (isPdf) {
    const pdfWrap = el('div', { class: 'reader-pdf-wrap' });
    const bar = el('div', { class: 'reader-pdf-bar' });
    bar.append(el('span', { class: 'mono', text: 'PDF 原文' }));
    bar.append(el('span', { class: 'spacer', style: { flex: 1 } }));
    const toggle = el('button', { class: 'btn sm', text: '解析文本' });
    bar.append(toggle);
    const iframe = el('iframe', { src: `/api/v2/file/${docId}${tab.params.chunkId ? '#page=' + guessPage(chunks, tab.params.chunkId) : ''}`, title: doc.title || 'PDF', class: 'reader-pdf' });
    pdfWrap.append(bar, iframe);
    docPane.append(pdfWrap);
    let parsed = false;
    toggle.addEventListener('click', () => {
      parsed = !parsed;
      toggle.textContent = parsed ? '原文 PDF' : '解析文本';
      iframe.style.display = parsed ? 'none' : '';
      body.parentElement.style.display = parsed ? '' : 'none';
    });
    body.parentElement.style.display = 'none';
  }

  // 目录
  const tocItems = r.toc || [];
  for (const t of tocItems) {
    const b = el('button', { class: `toc-item lv${Math.min(3, t.level || 1)}`, text: t.title || '' });
    b.addEventListener('click', () => {
      const c = docPane.querySelector(`[data-chunk="${t.chunk_id}"]`);
      if (c) { c.scrollIntoView({ block: 'start', behavior: 'smooth' }); return; }
      const target = (chunks || []).find(x => Number(x.id) === Number(t.chunk_id));
      const needle = (target && (target.heading_path || target.text)) || t.title || '';
      const range = findTextRange(body, needle.slice(-40));
      if (range) {
        const eln = range.startContainer.parentElement;
        eln && eln.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }
    });
    toc.append(b);
  }
  if (!tocItems.length) toc.append(el('div', { class: 'hint', text: '这份资料没有可用章节。' }));

  if (isText && raw && raw.ok) {
    body.innerHTML = markdown(raw.text || '');
  } else {
    renderChunks(body, chunks);
  }
  // 引用定位
  if (tab.params.chunkId) {
    requestAnimationFrame(() => {
      const c = body.querySelector(`[data-chunk="${tab.params.chunkId}"]`);
      if (c) {
        c.classList.add('target');
        c.scrollIntoView({ block: 'center', behavior: 'smooth' });
        return;
      }
      // Markdown/TXT 是渲染后的正文，没有 chunk 锚点：按 chunk 文本/引用片段定位
      const target = (chunks || []).find(x => Number(x.id) === Number(tab.params.chunkId));
      const needle = (tab.params.quote || (target && target.text) || '').replace(/\s+/g, ' ').trim();
      if (needle) {
        const range = findTextRange(body, needle.slice(0, 60));
        if (range) {
          const eln = range.startContainer.parentElement;
          eln && eln.scrollIntoView({ block: 'center', behavior: 'smooth' });
          try {
            if (window.CSS && CSS.highlights && window.Highlight) {
              CSS.highlights.set('doclib-cite', new Highlight(range));
            }
          } catch {}
        }
      }
    });
  }
  const savedScroll = Number(tab.params.scrollTop || 0);
  if (savedScroll) requestAnimationFrame(() => { docPane.scrollTop = savedScroll; });
  docPane.addEventListener('scroll', () => { tab.params.scrollTop = docPane.scrollTop; }, { passive: true });
  bindSelection(host, docId, actions);

  function renderChunks(root, list) {
    let lastHeading = null;
    for (const c of list) {
      const hp = c.heading_path || '';
      if (hp && hp !== lastHeading) {
        lastHeading = hp;
        const parts = hp.split('>').map(s => s.trim()).filter(Boolean);
        const h = el('h2', { text: parts[parts.length - 1] || hp });
        root.append(h);
        if (parts.length > 1) root.append(el('div', { class: 'chunk ch-head', text: parts.slice(0, -1).join(' › ') }));
      }
      const block = el('div', { class: 'chunk', dataset: { chunk: c.id } });
      if (c.is_table) block.append(el('pre', { text: c.text }));
      else {
        for (const para of String(c.text || '').split(/\n{2,}/)) {
          if (para.trim()) block.append(el('p', { text: para.trim() }));
        }
      }
      root.append(block);
    }
    if (!list.length) root.append(el('div', { class: 'empty' }, [el('h3', { text: '没有解析到正文' }), el('p', { text: '可以打开原文件查看，或在设置中重建索引。' })]));
  }
}

function guessPage(chunks, chunkId) {
  const c = (chunks || []).find(x => Number(x.id) === Number(chunkId));
  return c && c.page ? c.page : 1;
}
function openOriginal(docId) {
  api.post('/api/open', { doc_id: docId }).then(r => { if (r && r.ok === false) toast(r.error || '打开失败', { error: true }); }).catch(e => toast(e.message, { error: true }));
}
function highlightQuote(root, quote) {
  const q = String(quote || '').trim();
  if (!q || q.length < 3) return;
  const range = findTextRange(root, q.slice(0, 60));
  if (!range) return;
  try {
    if (window.CSS && CSS.highlights && window.Highlight) {
      CSS.highlights.set('doclib-cite', new Highlight(range));
    }
  } catch {}
}
function findTextRange(root, needle) {
  const q = String(needle || '').replace(/\s+/g, ' ').trim();
  if (!q) return null;
  try {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = (node.nodeValue || '').replace(/\s+/g, ' ');
      const idx = text.indexOf(q);
      if (idx >= 0) {
        const range = document.createRange();
        const raw = node.nodeValue || '';
        // 在原文中按非空白字符粗略定位；markdown 可能改变了换行，取前 12 字作为锚
        const probe = q.slice(0, Math.min(12, q.length));
        const at = raw.indexOf(probe);
        if (at < 0) continue;
        range.setStart(node, at);
        range.setEnd(node, Math.min(raw.length, at + q.length));
        return range;
      }
    }
  } catch {}
  return null;
}
function bindSelection(host, docId, actions) {
  let bar = null;
  const remove = () => { if (bar) { bar.remove(); bar = null; } };
  host.addEventListener('mouseup', () => {
    setTimeout(() => {
      remove();
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) return;
      const text = sel.toString().trim();
      if (text.length < 2) return;
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      if (!rect.width && !rect.height) return;
      const chunkEl = (range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement)?.closest?.('.chunk');
      bar = el('div', { class: 'sel-toolbar', style: { left: `${Math.max(8, rect.left)}px`, top: `${Math.max(8, rect.top - 38)}px` } });
      bar.append(el('span', { class: 'kv', text: `已选 ${text.length} 字` }));
      const ask = el('button', { text: '问 AI', onClick: () => {
        remove();
        actions.askSelection({ docId, chunkId: chunkEl ? Number(chunkEl.dataset.chunk) : null, quote: text, headingPath: '' });
      }});
      const copy = el('button', { text: '复制', onClick: () => { navigator.clipboard?.writeText(text); toast('已复制'); remove(); } });
      bar.append(ask, copy);
      document.body.append(bar);
    }, 0);
  });
  host.addEventListener('scroll', remove, true);
  document.addEventListener('mousedown', e => { if (bar && !bar.contains(e.target)) remove(); }, { capture: true });
}

/* ================= note ================= */
async function renderNote(tab, host, state, actions) {
  loading(host, '正在读取笔记…');
  let note = null;
  try {
    if (tab.params.noteId) {
      const r = await api.get(`/api/v2/notes/${tab.params.noteId}`);
      if (!r || r.ok === false) throw new Error((r && r.error) || '笔记不存在');
      note = r.note;
    } else {
      const r = await api.post('/api/v2/notes/save', {
        title: tab.params.title || '未命名笔记',
        body_md: '', partition_id: state.partitionId, node_id: tab.params.nodeId || null,
      });
      if (!r || r.ok === false) throw new Error((r && r.error) || '新建笔记失败');
      note = r.note;
      tab.params.noteId = note.id; tab.params.title = note.title; tab.title = note.title;
      save(state.workspace);
    }
  } catch (e) { errorView(host, e.message, actions, () => renderNote(tab, host, state, actions)); return; }
  clear(host);
  const view = el('div', { class: 'note-view' });
  const head = el('div', { class: 'note-head' });
  const title = el('input', { class: 'note-title', value: note.title, placeholder: '笔记标题' });
  const saveState = el('span', { class: 'save-state', text: timeAgo(note.updated_at) });
  const saveBtn = el('button', { class: 'btn primary sm', text: '保存' });
  head.append(title, saveState, el('div', { class: 'spacer', style: { flex: 1 } }), saveBtn);
  head.append(el('button', { class: 'btn icon', title: '在图谱中定位', html: icon('graph'), onClick: () => actions.openGraph({ scope: 'local', center: `note:${note.id}`, title: note.title }) }));
  head.append(el('button', { class: 'btn icon', title: '导出 Markdown', html: icon('external'), onClick: () => {
    const blob = new Blob([ta.value || ''], { type: 'text/markdown;charset=utf-8' });
    const a = el('a', { href: URL.createObjectURL(blob), download: `${title.value.trim() || 'note'}.md` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }}));
  head.append(el('button', { class: 'btn icon', title: '反向链接', html: icon('link'), onClick: () => showBacklinks('note', note.id, actions) }));
  view.append(head);
  const main = el('div', { class: 'note-main' });
  const editor = el('div', { class: 'note-editor' });
  const ta = el('textarea', { placeholder: '用 Markdown 记下你的理解；输入 [[ 可以链接笔记/资料/节点。' });
  ta.value = note.body_md || '';
  editor.append(ta);
  const split = el('div', { class: 'note-split' });
  const preview = el('div', { class: 'note-preview' });
  const md = el('div', { class: 'md' });
  preview.append(md);
  const back = el('div', { class: 'note-backlinks' });
  back.append(el('div', { class: 'lab', text: '反向链接' }));
  main.append(editor, split, preview, back);
  view.append(main);
  host.append(view);

  let dirty = false, saving = false, timer = 0, updated = note.updated_at;
  const renderPreview = () => {
    md.innerHTML = markdown(ta.value || '', { wikilink: true });
    md.querySelectorAll('[data-wikilink]').forEach(a => a.addEventListener('click', () => openWikilink(a.dataset.wikilink, actions)));
  };
  renderPreview();
  const doSave = async () => {
    if (saving) return; saving = true;
    try {
      const r = await api.post('/api/v2/notes/save', {
        note_id: note.id, title: title.value.trim() || '未命名笔记', body_md: ta.value,
        partition_id: note.partition_id || state.partitionId, node_id: note.node_id || null,
        expected_updated_at: updated,
      });
      if (!r || r.ok === false) throw new Error((r && r.error) || '保存失败');
      note = r.note; updated = note.updated_at; dirty = false; saveState.textContent = '已保存 · ' + timeAgo(updated);
      tab.params.title = note.title; tab.title = note.title;
      save(state.workspace);
      actions.refreshTabs && actions.refreshTabs();
      actions.refreshNotes && actions.refreshNotes();
      loadBacklinks();
    } catch (e) { toast(e.message, { error: true }); }
    finally { saving = false; }
  };
  const schedule = () => { dirty = true; saveState.textContent = '未保存'; clearTimeout(timer); timer = setTimeout(doSave, 900); };
  ta.addEventListener('input', () => { renderPreview(); schedule(); });
  title.addEventListener('input', schedule);
  title.addEventListener('keydown', e => { if (e.key === 'Enter') { ta.focus(); } });
  saveBtn.addEventListener('click', doSave);
  ta.addEventListener('keydown', e => { if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSave(); } });
  window.addEventListener('beforeunload', () => { if (dirty) navigator.sendBeacon?.('/api/v2/notes/save', new Blob([JSON.stringify({ note_id: note.id, title: title.value, body_md: ta.value, partition_id: note.partition_id, expected_updated_at: updated })], { type: 'application/json' })); }, { once: true });

  async function loadBacklinks() {
    try {
      const r = await api.get('/api/v2/backlinks', { kind: 'note', id: note.id });
      clear(back); back.append(el('div', { class: 'lab', text: '反向链接' }));
      const items = (r.items || []);
      if (!items.length) back.append(el('div', { class: 'hint', text: '还没有其他笔记或资料链接到这里。' }));
      for (const it of items.slice(0, 30)) {
        const b = el('button', { class: 'bl-item', title: it.title || '' }, [
          el('span', { class: 't', text: it.title || it.target_title || '未命名' }),
          el('span', { class: 's', text: it.heading_path || it.kind || '' }),
        ]);
        b.addEventListener('click', () => {
          if (it.kind === 'note' || it.note_id) actions.openNote(it.note_id || it.id, it.title);
          else if (it.doc_id) actions.openDoc(it.doc_id, it.title);
          else if (it.node_id) actions.openNode(it.node_id, it.title);
        });
        back.append(b);
      }
    } catch { back.append(el('div', { class: 'hint', text: '反链读取失败' })); }
  }
  loadBacklinks();
}
function openWikilink(raw, actions) {
  const s = String(raw || '').trim();
  let m = /^note:(\d+)$/.exec(s); if (m) return actions.openNote(Number(m[1]), '笔记');
  m = /^doc:(\d+)$/.exec(s); if (m) return actions.openDoc(Number(m[1]), '资料');
  m = /^node:(\d+)$/.exec(s); if (m) return actions.openNode(Number(m[1]), '节点');
  toast('按标题的链接待反链面板打开；稳定 ID 形式（note:/doc:/node:）可直接跳转');
}

/* ================= node ================= */
async function renderNode(tab, host, state, actions) {
  const id = Number(tab.params.nodeId);
  loading(host, '正在读取节点…');
  let r = null;
  try { r = await api.get('/api/v2/entity', { kind: 'node', id }); } catch {}
  let node = r?.entity;
  if (!node) {
    const found = findTreeNode(state.tree, id);
    node = found || { id, name: tab.title || '节点' };
  }
  const docs = r?.docs?.results || [];
  clear(host);
  const view = el('div', { class: 'node-view' });
  const head = viewHead(node.name || tab.title || '节点', `${docs.length} 份资料`, [
    { icon: 'graph', title: '局部图谱', onClick: () => actions.openGraph({ scope: 'local', center: `node:${id}`, title: node.name }) },
    { icon: 'note', title: '在此新建笔记', onClick: () => actions.newNote({ nodeId: id, partitionId: state.partitionId }) },
    { icon: 'history', title: '刷新', onClick: () => renderNode(tab, host, state, actions) },
  ]);
  view.append(head);
  const body = el('div', { class: 'node-body' });
  body.append(el('div', { class: 'node-kind', text: '知识节点' }));
  body.append(el('h1', { class: 'node-title', text: node.name || tab.title }));
  body.append(el('div', { class: 'node-path', text: node.path || '' }));
  const acts = el('div', { class: 'node-actions' });
  acts.append(el('button', { class: 'btn primary', text: '局部关系图谱', onClick: () => actions.openGraph({ scope: 'local', center: `node:${id}`, title: node.name }) }));
  acts.append(el('button', { class: 'btn', text: '问 AI 当前节点', onClick: () => actions.askWithContext({ kind: 'node', node_id: id, label: `当前节点 · ${node.name}` }) }));
  acts.append(el('button', { class: 'btn', text: '新建笔记', onClick: () => actions.newNote({ nodeId: id, partitionId: state.partitionId }) }));
  body.append(acts);
  body.append(el('div', { class: 'section' }, [
    el('h3', { text: `节点资料 · ${docs.length}` }),
    docs.length ? el('div', {}, docs.map(d => {
      const row = el('div', { class: 'doc-row' }, [
        el('span', { class: 'ic', html: icon(fileIcon(d.file_path)) }),
        el('span', { class: 'main' }, [el('span', { class: 't', text: d.title }), el('span', { class: 'm', text: `${d.node_names || ''} · ${d.chunks || 0} 块` })]),
        el('span', { class: 'go', text: '›' }),
      ]);
      row.addEventListener('click', () => actions.openDoc(d.doc_id, d.title));
      return row;
    })) : el('div', { class: 'hint', text: '这个节点下还没有资料。' }),
  ]));
  view.append(body);
  host.append(view);
}
function findTreeNode(nodes, id) {
  for (const n of nodes || []) {
    if (Number(n.id) === Number(id)) return n;
    const f = findTreeNode(n.children, id);
    if (f) return f;
  }
  return null;
}

/* ================= search ================= */
async function renderSearch(tab, host, state, actions) {
  clear(host);
  const view = el('div', { class: 'search-view' });
  const head = el('div', { class: 'search-head' });
  const input = el('input', { class: 'input', placeholder: '搜索资料、笔记、章节…', value: tab.params.q || '' });
  const scope = el('select', { class: 'select' }, [
    el('option', { value: 'all', text: '当前分区' }),
    el('option', { value: 'subtree', text: '当前节点含下级' }),
  ]);
  head.append(input, scope);
  const body = el('div', { class: 'search-body' });
  const results = el('div', { class: 'search-results' });
  body.append(results);
  view.append(head, body);
  host.append(view);
  let timer = 0;
  const run = async () => {
    const q = input.value.trim();
    if (!q) { clear(results); results.append(el('div', { class: 'empty', text: '输入关键词开始搜索。' })); return; }
    tab.params.q = q; tab.title = `搜索：${q}`;
    clear(results); results.append(el('div', { class: 'loading-line' }, [el('span', { class: 'spin' }), el('span', { text: '检索中…' })]));
    try {
      const [rd, rn] = await Promise.all([
        api.get('/api/rev/search', { q, scope: scope.value, partition: state.partitionId }),
        api.get('/api/v2/notes/search', { q, partition: state.partitionId }).catch(() => ({ items: [] })),
      ]);
      clear(results);
      const docs = rd.results || [];
      results.append(el('div', { class: 'search-group', text: `资料 · ${docs.length}` }));
      for (const d of docs) {
        const row = el('div', { class: 'result-row' }, [
          el('span', { class: 'ic', html: icon('filePdf') }),
          el('span', { class: 'main' }, [
            el('span', { class: 't', html: highlightTerms(d.title || '', [q]) }),
            el('span', { class: 'm', text: `${d.node_names || ''} · ${d.heading_path || ''}` }),
            el('span', { class: 'sn', html: highlightTerms(d.snippet || '', [q]) }),
          ]),
        ]);
        row.addEventListener('click', () => actions.openDoc(d.doc_id, d.title, { chunkId: d.chunk_id || null }));
        results.append(row);
      }
      if (!docs.length) results.append(el('div', { class: 'hint', text: '没有资料命中。' }));
      const notes = rn.items || [];
      if (notes.length) {
        results.append(el('div', { class: 'search-group', text: `笔记 · ${notes.length}` }));
        for (const n of notes) {
          const row = el('div', { class: 'result-row' }, [
            el('span', { class: 'ic', html: icon('note') }),
            el('span', { class: 'main' }, [
              el('span', { class: 't', html: highlightTerms(n.title || '', [q]) }),
              el('span', { class: 'sn', html: highlightTerms(n.snippet || n.body_md || '', [q]) }),
            ]),
          ]);
          row.addEventListener('click', () => actions.openNote(n.id, n.title));
          results.append(row);
        }
      }
      actions.refreshTabs && actions.refreshTabs();
    } catch (e) {
      clear(results); results.append(el('div', { class: 'error-box' }, [el('b', { text: '搜索失败' }), el('div', { text: e.message })]));
    }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 350); });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { clearTimeout(timer); run(); } });
  scope.addEventListener('change', run);
  setTimeout(() => { input.focus(); input.select(); }, 30);
  run();
}

/* ================= settings ================= */
async function renderSettings(tab, host, state, actions) {
  clear(host);
  const view = el('div', { class: 'settings-view' });
  const nav = el('div', { class: 'settings-nav' });
  const main = el('div', { class: 'settings-main' });
  view.append(nav, main);
  host.append(view);
  const sections = [
    { id: 'appearance', label: '外观' },
    { id: 'ai', label: 'AI 模型' },
    { id: 'data', label: '数据与索引' },
    { id: 'about', label: '关于' },
  ];
  let cur = 'appearance';
  const renderNav = () => {
    clear(nav);
    for (const s of sections) {
      const b = el('button', { class: cur === s.id ? 'on' : '', text: s.label, onClick: () => { cur = s.id; renderNav(); renderMain(); } });
      nav.append(b);
    }
  };
  const renderMain = () => {
    clear(main);
    if (cur === 'appearance') renderAppearance();
    else if (cur === 'ai') renderAI();
    else if (cur === 'data') renderData();
    else renderAbout();
  };
  const renderAppearance = () => {
    main.append(el('h2', { text: '外观' }));
    main.append(el('div', { class: 'sub', text: '浅色与深色只改变配色、字体色、边框和图谱视觉；三栏布局、面板尺寸、标签位置和 AI 面板结构完全一致。' }));
    const sec = el('div', { class: 'set-sec' }, [el('h3', { text: '主题' })]);
    const sel = el('select', { class: 'select' }, [
      el('option', { value: 'dark', text: '深色（默认）' }),
      el('option', { value: 'light', text: '浅色' }),
      el('option', { value: 'system', text: '跟随系统' }),
    ]);
    sel.value = state.workspace.theme || 'dark';
    sel.addEventListener('change', () => actions.setTheme(sel.value));
    sec.append(el('div', { class: 'set-row' }, [el('label', { text: '主题' }), sel]));
    sec.append(el('div', { class: 'hint', text: '主题选择会随工作区保存，重启后恢复。' }));
    main.append(sec);
  };
  const renderAI = () => {
    main.append(el('h2', { text: 'AI 模型' }));
    main.append(el('div', { class: 'sub', text: '复用现有 Gateway 与密钥管理；这里只切换默认模型，密钥仍用 DPAPI 加密。' }));
    const sec = el('div', { class: 'set-sec' }, [el('h3', { text: '已配置模型' })]);
    const items = state.providers || [];
    if (!items.length) sec.append(el('div', { class: 'hint', text: '还没有配置模型。可以在下方新增，或导入已有的模型配置。' }));
    for (const p of items) {
      const row = el('div', { class: 'provider-row' }, [
        el('span', { class: 'name', text: p.name }),
        el('span', { class: 'meta', text: `${p.model || ''} ${p.free ? '· 免费' : ''} ${p.is_default ? '· 默认' : ''}` }),
        el('span', { class: 'spacer', style: { flex: 1 } }),
      ]);
      if (!p.is_default) {
        row.append(el('button', { class: 'btn sm', text: '设为默认', onClick: async () => {
          const r = await api.post('/api/ai/providers/default', { name: p.name });
          if (r.ok === false) toast(r.error || '失败', { error: true }); else { state.provider = p.name; toast('已切换默认模型'); actions.refreshProviders(); }
        }}));
      }
      row.append(el('button', { class: 'btn sm', text: '测试', onClick: async (e) => {
        e.target.disabled = true; e.target.textContent = '测试中…';
        try { const r = await api.post('/api/ai/test', { name: p.name }); toast(r.ok ? '连接成功' : (r.error || '失败'), { error: !r.ok }); }
        catch (err) { toast(err.message, { error: true }); }
        finally { e.target.disabled = false; e.target.textContent = '测试'; }
      }}));
      sec.append(row);
    }
    main.append(sec);
    const add = el('div', { class: 'set-sec' }, [el('h3', { text: '新增模型配置' })]);
    const fields = {};
    const mk = (label, key, placeholder = '', type = 'text') => {
      const input = el('input', { class: 'input', type, placeholder });
      fields[key] = input;
      return el('div', { class: 'set-row' }, [el('label', { text: label }), input]);
    };
    add.append(mk('名称', 'name', '例如 deepseek'));
    add.append(mk('Base URL', 'base_url', 'https://api.deepseek.com/v1'));
    add.append(mk('模型', 'model', 'deepseek-chat'));
    add.append(mk('密钥键名', 'key_ref', 'deepseek'));
    const free = el('input', { type: 'checkbox' });
    add.append(el('div', { class: 'set-row' }, [el('label', { text: '免费' }), el('label', { class: 'check' }, [free, el('span', { text: '免费/本地模型' })])]));
    add.append(el('div', { class: 'set-row' }, [
      el('button', { class: 'btn primary', text: '保存模型配置', onClick: async () => {
        if (!fields.name.value.trim()) { toast('请填写名称'); return; }
        const r = await api.post('/api/ai/providers', {
          name: fields.name.value.trim(), base_url: fields.base_url.value.trim(),
          model: fields.model.value.trim(), key_ref: fields.key_ref.value.trim(),
          free: free.checked, enabled: true, is_default: !(state.providers || []).length,
        });
        if (r.ok === false) toast(r.error || '保存失败', { error: true });
        else { toast('模型配置已保存'); actions.refreshProviders(); renderMain(); }
      }}),
    ]));
    add.append(el('div', { class: 'hint', text: '密钥本身请在下方「密钥」区填写；这里只引用键名。' }));
    main.append(add);
    const secKey = el('div', { class: 'set-sec' }, [el('h3', { text: '密钥（DPAPI 加密）' })]);
    const kname = el('input', { class: 'input', placeholder: '键名，例如 deepseek' });
    const kval = el('input', { class: 'input', type: 'password', placeholder: '粘贴 API Key' });
    secKey.append(el('div', { class: 'set-row' }, [el('label', { text: '键名' }), kname]));
    secKey.append(el('div', { class: 'set-row' }, [el('label', { text: '密钥' }), kval]));
    secKey.append(el('div', { class: 'set-row' }, [
      el('button', { class: 'btn', text: '保存密钥', onClick: async () => {
        if (!kname.value.trim() || !kval.value.trim()) { toast('请填写键名和密钥'); return; }
        try {
          const r = await api.post('/api/secrets', { name: kname.value.trim(), value: kval.value.trim() });
          if (r.ok === false) throw new Error(r.error || '保存失败');
          toast('密钥已加密保存'); kval.value = '';
          actions.refreshProviders();
        } catch (e) { toast(e.message, { error: true }); }
      }}),
    ]));
    secKey.append(el('div', { class: 'hint', text: '密钥只保存在本机，用 Windows DPAPI 加密；界面不会回显明文。' }));
    main.append(secKey);
  };
  const renderData = () => {
    main.append(el('h2', { text: '数据与索引' }));
    main.append(el('div', { class: 'sub', text: '所有操作只作用于当前数据目录；备份/回收站仍走原有安全逻辑。' }));
    const importNote = () => {
      const input = el('input', { class: 'input', placeholder: 'Markdown / TXT 文件绝对路径' });
      const body = el('div', { class: 'field' }, [el('label', { text: '文件路径' }), input,
        el('div', { class: 'hint', text: '会作为新笔记导入，不覆盖已有笔记；标题取文件名。' })]);
      const d = modal({ title: '导入 Markdown 笔记', body, foot: [
        { label: '取消', onClick: (close) => close() },
        { label: '导入', primary: true, onClick: async (close) => {
          try {
            const r = await api.post('/api/v2/notes/import', {
              path: input.value.trim(), partition_id: state.partitionId,
            });
            if (r.ok === false) throw new Error(r.error || '导入失败');
            toast('已导入笔记'); close(); actions.refreshNotes(); actions.openNote(r.note.id, r.note.title);
          } catch (e) { toast(e.message, { error: true }); }
        }},
      ]});
    };
    const sec = el('div', { class: 'set-sec' }, [el('h3', { text: '备份与导入' })]);
    sec.append(el('div', { class: 'set-row' }, [
      el('button', { class: 'btn', text: '立即备份', onClick: async () => {
        try { const r = await api.post('/api/backup', {}); toast(r.ok ? '备份完成' : (r.error || '失败'), { error: !r.ok }); }
        catch (e) { toast(e.message, { error: true }); }
      }}),
      el('button', { class: 'btn', text: '导入资料', onClick: () => actions.importDialog() }),
      el('button', { class: 'btn', text: '导入 Markdown 笔记', onClick: () => importNote() }),
      el('button', { class: 'btn', text: '重建索引', onClick: async () => {
        if (!await confirmDialog('重建索引', '会按当前解析版本重新解析全部文档，可能耗时较长。继续？')) return;
        try { const r = await api.post('/api/rebuild', { filter: 'outdated' }); toast('重建完成'); actions.refreshData(); }
        catch (e) { toast(e.message, { error: true }); }
      }}),
      el('button', { class: 'btn', text: '回收站', onClick: () => showRecycle() }),
      el('button', { class: 'btn danger', text: '重置工作区', onClick: async () => {
        if (!await confirmDialog('重置工作区', '只重置标签/面板布局，不删除资料或笔记。继续？', { danger: true, okText: '重置' })) return;
        try { await api.post('/api/v2/workspace/reset', {}); location.reload(); }
        catch (e) { toast(e.message, { error: true }); }
      }}),
    ]));
    main.append(sec);
    const stats = state.stats || {};
    const info = el('div', { class: 'set-sec' }, [
      el('h3', { text: '当前库' }),
      el('div', { class: 'kv' }, [el('b', { text: '资料' }), el('span', { text: String(stats.documents || 0) })]),
      el('div', { class: 'kv' }, [el('b', { text: '切块' }), el('span', { text: String(stats.chunks || 0) })]),
      el('div', { class: 'kv' }, [el('b', { text: '节点' }), el('span', { text: String(stats.nodes || 0) })]),
      el('div', { class: 'kv' }, [el('b', { text: '数据库' }), el('span', { text: fmtSize(stats.db_size) })]),
    ]);
    main.append(info);
  };
  const renderAbout = () => {
    main.append(el('h2', { text: 'DocLib 2.0' }));
    main.append(el('div', { class: 'sub', text: '纯本地知识库 · 资料 / 图谱 / 笔记 / AI 伴学。' }));
    main.append(el('div', { class: 'set-sec' }, [
      el('div', { class: 'kv' }, [el('b', { text: '版本' }), el('span', { text: 'v2.0.0-dev' })]),
      el('div', { class: 'kv' }, [el('b', { text: '数据目录' }), el('span', { text: state.health?.db || '' })]),
      el('div', { class: 'kv' }, [el('b', { text: 'WebView2' }), el('span', { text: 'Chromium 157（本机）' })]),
    ]));
  };
  renderNav(); renderMain();
}

/* ================= mindmap ================= */
async function renderMindmapTab(tab, host, state, actions) {
  clear(host);
  const name = tab.params.mapName;
  if (!name) {
    const view = el('div', { class: 'mindmap-view' });
    view.append(viewHead('知识导图', '旧版 SVG 画板', [
      { icon: 'plus', title: '新建导图', onClick: () => actions.newMindmap() },
      { icon: 'refresh', title: '刷新', onClick: () => renderMindmapTab(tab, host, state, actions) },
    ]));
    const list = el('div', { class: 'map-list' });
    view.append(list);
    host.append(view);
    try {
      const r = await api.get('/api/maps');
      const maps = r.items || [];
      if (!maps.length) list.append(el('div', { class: 'empty' }, [el('h3', { text: '还没有导图' }), el('p', { text: '可以新建一张，或用当前资料生成一张。' }), el('div', { class: 'actions' }, [el('button', { class: 'btn primary', text: '新建导图', onClick: () => actions.newMindmap() }), el('button', { class: 'btn', text: '从资料生成', onClick: () => actions.generateMindmap() })])]));
      for (const m of maps) {
        const row = el('div', { class: 'map-row' }, [
          el('span', { html: icon('mind') }),
          el('span', { class: 't', text: m.title || m.name }),
          el('span', { class: 'm', text: `${m.items || 0} 节点 · ${timeAgo(m.updated_at)}` }),
          el('button', { class: 'btn sm', text: '打开', onClick: () => actions.openMindmap(m.name) }),
        ]);
        row.addEventListener('dblclick', () => actions.openMindmap(m.name));
        list.append(row);
      }
    } catch (e) { list.append(el('div', { class: 'error-box' }, [el('b', { text: '读取失败' }), el('div', { text: e.message })])); }
    return;
  }
  const view = el('div', { class: 'mindmap-view' });
  view.append(viewHead(name, '知识导图 · 旧版画板', [
    { icon: 'external', title: '回到导图列表', onClick: () => actions.openMindmapList() },
  ]));
  const theme = document.documentElement.dataset.theme || 'dark';
  const frame = el('iframe', { class: 'map-frame', src: `/mindmap.html?embed=1&map=${encodeURIComponent(name)}&theme=${theme}`, title: name });
  view.append(frame);
  host.append(view);
}

/* ================= welcome ================= */
function renderWelcome(host, state, actions) {
  clear(host);
  const view = el('div', { class: 'welcome-view' });
  const inner = el('div', { class: 'welcome-inner' });
  inner.append(el('div', { class: 'welcome-mark', html: `<svg viewBox="0 0 44 44" fill="none"><path d="M8 12c5-2 9-2 14 0 5 2 9 2 14 0v22c-5 2-9 2-14 0-5-2-9-2-14 0z" stroke="currentColor" stroke-width="1.6"/><path d="M22 12.5v21" stroke="currentColor" stroke-width="1" opacity=".5"/><circle cx="34" cy="10" r="3" fill="var(--bg)" stroke="currentColor" stroke-width="1.5"/></svg>` }));
  inner.append(el('h1', { text: '把资料、关系与问题放在同一张桌上。' }));
  inner.append(el('p', { class: 'lead', text: 'DocLib 2.0 把课程资料、知识图谱、笔记和 AI 伴学放在同一个工作区。AI 只根据你当前选择的资料范围回答，引用可以点回原文。' }));
  const steps = el('div', { class: 'welcome-steps' });
  const step = (no, t, p) => el('div', { class: 'welcome-step' }, [el('div', { class: 'no', text: no }), el('h3', { text: t }), el('p', { text: p })]);
  steps.append(step('01', '导入资料', 'Word、PDF、PPT、Markdown、TXT；自动解析、切块、挂载。'));
  steps.append(step('02', '打开图谱', '从全局或局部关系图谱进入，双击节点打开资料。'));
  steps.append(step('03', '向 AI 提问', '右侧选择当前文档/节点/选文范围，回答带真实引用。'));
  inner.append(steps);
  const acts = el('div', { class: 'welcome-actions' });
  acts.append(el('button', { class: 'btn primary', text: '导入资料', onClick: () => actions.importDialog() }));
  acts.append(el('button', { class: 'btn', text: '打开关系图谱', onClick: () => actions.openGraph({ scope: 'global' }) }));
  acts.append(el('button', { class: 'btn', text: '新建笔记', onClick: () => actions.newNote() }));
  acts.append(el('button', { class: 'btn', text: '设置', onClick: () => actions.openSettings() }));
  inner.append(acts);
  inner.append(el('div', { class: 'welcome-foot', text: `本地运行 · 数据不出本机 · ${state.stats?.documents || 0} 份资料 / ${state.stats?.nodes || 0} 个节点` }));
  view.append(inner);
  host.append(view);
}

/* ================= backlinks modal ================= */
async function showRecycle() {
  const d = modal({ title: '回收站', body: el('div', { class: 'hint', text: '读取中…' }), width: 'min(720px,96vw)' });
  try {
    const r = await api.get('/api/recycle');
    const box = el('div');
    const nodes = r.nodes || [];
    const docs = r.documents || [];
    if (!nodes.length && !docs.length) box.append(el('div', { class: 'hint', text: '回收站是空的。' }));
    if (nodes.length) {
      box.append(el('div', { class: 'search-group', text: `节点 · ${nodes.length}` }));
      for (const n of nodes) {
        const row = el('div', { class: 'doc-row' }, [
          el('span', { class: 'ic', html: icon('folder') }),
          el('span', { class: 'main' }, [el('span', { class: 't', text: n.name || '未命名节点' })]),
          el('button', { class: 'btn sm', text: '恢复', onClick: async () => {
            const x = await api.post('/api/recycle/restore', { node_id: n.id });
            if (x.ok === false) toast(x.error || '失败', { error: true }); else { toast('已恢复'); d.close(); }
          }}),
          el('button', { class: 'btn sm danger', text: '彻底删除', onClick: async () => {
            if (!await confirmDialog('彻底删除节点', '删除后不可恢复。继续？', { danger: true, okText: '删除' })) return;
            const x = await api.post('/api/recycle/purge', { node_id: n.id });
            if (x.ok === false) toast(x.error || '失败', { error: true }); else { toast('已彻底删除'); d.close(); }
          }}),
        ]);
        box.append(row);
      }
    }
    if (docs.length) {
      box.append(el('div', { class: 'search-group', text: `资料 · ${docs.length}` }));
      for (const x of docs) {
        const row = el('div', { class: 'doc-row' }, [
          el('span', { class: 'ic', html: icon(fileIcon(x.file_type || x.file_path)) }),
          el('span', { class: 'main' }, [el('span', { class: 't', text: x.title || x.file_path }), el('span', { class: 'm', text: x.file_path || '' })]),
          el('button', { class: 'btn sm', text: '恢复', onClick: async () => {
            const y = await api.post('/api/doc/restore', { doc_id: x.id });
            if (y.ok === false) toast(y.error || '失败', { error: true }); else { toast('已恢复'); d.close(); }
          }}),
          el('button', { class: 'btn sm danger', text: '彻底删除', onClick: async () => {
            if (!await confirmDialog('彻底删除资料', '会同时删除索引与引用快照；不可恢复。继续？', { danger: true, okText: '删除' })) return;
            const y = await api.post('/api/doc/purge', { doc_id: x.id });
            if (y.ok === false) toast(y.error || '失败', { error: true }); else { toast('已彻底删除'); d.close(); }
          }}),
        ]);
        box.append(row);
      }
    }
    clear(d.body); d.body.append(box);
  } catch (e) { clear(d.body); d.body.append(el('div', { class: 'error-box', text: e.message })); }
}

async function showBacklinks(kind, id, actions) {
  const d = modal({ title: '反向链接 / 关联', body: el('div', { class: 'hint', text: '读取中…' }), width: 'min(680px,96vw)' });
  try {
    const r = await api.get('/api/v2/backlinks', { kind, id });
    const box = el('div');
    const items = r.items || [];
    if (!items.length) box.append(el('div', { class: 'hint', text: '还没有已解析的链接。用 [[note:12|标题]] 或 [[doc:34|标题]] 建立关联。' }));
    for (const it of items) {
      const b = el('button', { class: 'doc-row', style: { width: '100%', textAlign: 'left' }, onClick: () => {
        d.close();
        if (it.kind === 'note' || it.note_id) actions.openNote(it.note_id || it.id, it.title);
        else if (it.doc_id) actions.openDoc(it.doc_id, it.title);
        else if (it.node_id) actions.openNode(it.node_id, it.title);
      }}, [
        el('span', { class: 'ic', html: icon(it.kind === 'note' ? 'note' : 'link') }),
        el('span', { class: 'main' }, [el('span', { class: 't', text: it.title || it.target_title || '未命名' }), el('span', { class: 'm', text: it.heading_path || it.rel || '' })]),
      ]);
      box.append(b);
    }
    clear(d.body); d.body.append(box);
  } catch (e) { clear(d.body); d.body.append(el('div', { class: 'error-box', text: e.message })); }
}
