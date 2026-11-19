// 工作区状态：唯一数据源（服务端 data/workspace.json）
import { api, debounce, toast, uid } from './core.js';

const ALLOWED = new Set(['graph', 'doc', 'note', 'mindmap', 'search', 'node', 'settings', 'welcome']);

export function defaultWorkspace() {
  return {
    version: 1,
    theme: 'dark',
    active_pane: 'p1',
    layout: { left_width: 268, right_width: 374, left_collapsed: false, right_collapsed: false, split: null },
    panes: [{
      id: 'p1', active_tab: 't_graph',
      tabs: [{
        id: 't_graph', kind: 'graph', title: '关系图谱', pinned: false,
        params: { scope: 'global', partitionId: null, center: null, depth: 1 },
      }],
    }],
    history: { p1: { entries: [], index: -1 } },
  };
}

export function pane(w) { return w.panes.find(p => p.id === w.active_pane) || w.panes[0]; }
export function activeTab(w) {
  const p = pane(w);
  return p.tabs.find(t => t.id === p.active_tab) || p.tabs[0] || null;
}
export function findTab(w, kind, key) {
  const p = pane(w);
  return p.tabs.find(t => t.kind === kind && tabKey(t) === key) || null;
}
export function tabKey(t) {
  const p = t.params || {};
  switch (t.kind) {
    case 'doc': return `doc:${p.docId}`;
    case 'note': return `note:${p.noteId}`;
    case 'node': return `node:${p.nodeId}`;
    case 'graph': return `graph:${p.scope || 'global'}:${p.center || ''}:${p.partitionId || ''}`;
    case 'mindmap': return `map:${p.mapName || ''}`;
    case 'search': return `search:${p.q || ''}`;
    default: return `${t.kind}:`;
  }
}

export function tabTitle(t) {
  const p = t.params || {};
  switch (t.kind) {
    case 'doc': return p.title || '资料';
    case 'note': return p.title || '笔记';
    case 'node': return p.title || '节点';
    case 'graph': return p.title || (p.scope === 'local' ? '局部图谱' : '关系图谱');
    case 'mindmap': return p.mapName || '知识导图';
    case 'search': return p.q ? `搜索：${p.q}` : '搜索';
    case 'settings': return '设置';
    default: return '欢迎';
  }
}

export function openTab(w, kind, params = {}, { title = '', activate = true, replace = false } = {}) {
  if (!ALLOWED.has(kind)) kind = 'welcome';
  const p = pane(w);
  const key = tabKey({ kind, params });
  let tab = p.tabs.find(t => t.kind === kind && tabKey(t) === key);
  if (tab) {
    Object.assign(tab.params, params);
    if (title) tab.title = title;
    tab.title = tab.title || tabTitle(tab);
    if (activate) p.active_tab = tab.id;
    return tab;
  }
  if (p.tabs.length >= 12) {
    const old = p.tabs.find(t => !t.pinned && t.id !== p.active_tab) || p.tabs[0];
    if (old) p.tabs = p.tabs.filter(t => t !== old);
  }
  tab = { id: uid('t_'), kind, params, title: title || '', pinned: false };
  tab.title = tab.title || tabTitle(tab);
  if (replace) {
    const idx = p.tabs.findIndex(t => t.id === p.active_tab);
    if (idx >= 0) p.tabs[idx] = tab; else p.tabs.push(tab);
  } else p.tabs.push(tab);
  if (activate) p.active_tab = tab.id;
  return tab;
}

export function closeTab(w, id) {
  const p = pane(w);
  const idx = p.tabs.findIndex(t => t.id === id);
  if (idx < 0) return null;
  p.tabs.splice(idx, 1);
  if (!p.tabs.length) {
    const t = openTab(w, 'welcome', {}, { activate: true });
    p.active_tab = t.id;
  } else if (p.active_tab === id) {
    p.active_tab = p.tabs[Math.max(0, idx - 1)].id;
  }
  return activeTab(w);
}

export function updateTab(w, tab, params = {}) {
  Object.assign(tab.params, params);
  tab.title = tabTitle(tab);
}

const saveDebounced = debounce(async (w) => {
  try {
    const r = await api.post('/api/v2/workspace', { workspace: w });
    if (r && r.ok === false) toast(r.error || '工作区保存失败', { error: true });
  } catch (e) { /* 离线时保留内存状态 */ }
}, 450);

export function save(w) { saveDebounced(w); }

export function applyTheme(w, theme) {
  const t = ['dark', 'light', 'system'].includes(theme) ? theme : 'dark';
  w.theme = t;
  const real = t === 'system' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : t;
  document.documentElement.dataset.theme = real;
  document.documentElement.dataset.themeSetting = t;
  return real;
}
