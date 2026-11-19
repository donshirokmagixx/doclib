// DocLib 2.0 启动与工作区编排
import { el, clear, api, toast, modal, promptDialog, confirmDialog, icon, fmtTime } from './core.js';
import {
  defaultWorkspace, pane, activeTab, openTab as wsOpenTab, closeTab as wsCloseTab,
  save as saveWorkspace, applyTheme, tabTitle,
} from './workspace.js';
import { mountShell } from './shell.js';
import { createAIPanel } from './ai.js';
import { renderView } from './views.js';

const root = document.getElementById('app');
const state = {
  partitions: [], partitionId: null, tree: [], docs: [], notes: [], stats: {},
  health: {}, providers: [], provider: '', workspace: null, activeTab: null,
  activeEntity: null, ai: null,
};
let shell = null, ai = null;
const actions = {};

function bootError(e) {
  clear(root);
  root.append(el('div', { class: 'empty', style: { height: '100vh' } }, [
    el('span', { html: icon('alert') }),
    el('h3', { text: 'DocLib 2.0 启动失败' }),
    el('p', { text: e?.message || String(e) }),
    el('div', { class: 'actions' }, [
      el('button', { class: 'btn primary', text: '重试', onClick: () => location.reload() }),
    ]),
  ]));
}

async function boot() {
  try {
    let data;
    try {
      data = await api.get('/api/v2/bootstrap');
    } catch (e) {
      // 兼容：v2 未就绪时至少给出明确错误，不白屏
      throw new Error(`无法连接 DocLib 服务：${e.message}`);
    }
    if (!data || data.ok === false) throw new Error(data?.error || '服务返回异常');

    state.partitions = data.partitions || [];
    data.tree = data.tree || [];
    state.tree = data.tree || [];
    state.stats = data.stats || {};
    state.health = data.health || {};
    state.providers = data.providers || [];
    state.provider = data.current_provider || '';
    state.workspace = normalizeWorkspace(data.workspace);
    const savedPart = Number(localStorage.getItem('doclib.partition') || NaN);
    state.partitionId = state.partitions.some(p => p.id === savedPart)
      ? savedPart
      : (data.partition ?? state.partitions[0]?.id ?? null);
    applyTheme(state.workspace, state.workspace.theme || 'dark');
    await loadPartitionData(state.partitionId);

    shell = mountShell(root, state, actions);
    ai = createAIPanel(state, actions);
    shell.setAI(ai.root);
    state.ai = state.ai || null;

    const p = pane(state.workspace);
    const tab = p.tabs.find(t => t.id === p.active_tab) || p.tabs[0];
    if (tab) await activateTab(tab.id, { silent: true });
    else {
      const t = wsOpenTab(state.workspace, 'graph', { scope: 'global', partitionId: state.partitionId }, { title: '关系图谱' });
      await activateTab(t.id, { silent: true });
    }
    shell.renderAll();
    bindKeys();
    installDropImport();
    setInterval(() => { if (state.ai?.conversationId) ai.refreshHistory(); }, 30000);
  } catch (e) {
    console.error(e);
    bootError(e);
  }
}

function normalizeWorkspace(w) {
  if (!w || typeof w !== 'object' || !Array.isArray(w.panes) || !w.panes.length) return defaultWorkspace();
  if (!w.theme) w.theme = 'dark';
  if (!w.layout) w.layout = { left_width: 268, right_width: 374, left_collapsed: false, right_collapsed: false };
  const p = w.panes[0];
  if (!p.tabs || !p.tabs.length) {
    p.tabs = [{ id: 't_graph', kind: 'graph', title: '关系图谱', params: { scope: 'global', partitionId: null, center: null, depth: 1 }, pinned: false }];
    p.active_tab = 't_graph';
  }
  if (!p.tabs.some(t => t.id === p.active_tab)) p.active_tab = p.tabs[0].id;
  w.active_pane = p.id;
  return w;
}

async function loadPartitionData(pid) {
  const [docs, notes, tree, stats] = await Promise.all([
    api.get('/api/rev/docs', { scope: 'all', partition: pid }).catch(() => ({ results: [] })),
    api.get('/api/v2/notes', { partition: pid }).catch(() => ({ items: [] })),
    api.get('/api/rev/tree', { partition: pid }).catch(() => ({ tree: [] })),
    api.get('/api/stats').catch(() => state.stats),
  ]);
  state.docs = docs.results || [];
  state.notes = notes.items || [];
  if (tree.tree) state.tree = tree.tree;
  if (stats) state.stats = { ...state.stats, ...stats };
  if (shell) { shell.renderExplorer(); shell.renderStatus(); }
}

function entityOfTab(tab) {
  if (!tab) return null;
  if (tab.kind === 'doc') return { kind: 'document', id: tab.params.docId, title: tab.title };
  if (tab.kind === 'note') return { kind: 'note', id: tab.params.noteId, title: tab.title };
  if (tab.kind === 'node') return { kind: 'node', id: tab.params.nodeId, title: tab.title };
  if (tab.kind === 'graph' && tab.params?.scope === 'local') {
    const m = /^(node|document|note):(\d+)$/.exec(String(tab.params.center || ''));
    if (m) return { kind: m[1] === 'document' ? 'document' : m[1] === 'note' ? 'note' : 'node', id: Number(m[2]), title: tab.title };
  }
  return null;
}

async function activateTab(id, { silent = false } = {}) {
  const p = pane(state.workspace);
  const tab = p.tabs.find(t => t.id === id);
  if (!tab) return;
  p.active_tab = tab.id;
  state.activeTab = tab;
  const ent = entityOfTab(tab);
  if (ent) state.activeEntity = ent;
  const host = el('div', { class: 'view-host' });
  clear(shell.refs.tabBody);
  shell.refs.tabBody.append(host);
  shell.renderTabs();
  shell.renderExplorer();
  shell.renderStatus();
  if (!silent) saveWorkspace(state.workspace);
  try {
    await renderView(tab, host, state, actions);
  } catch (e) {
    clear(host);
    host.append(el('div', { class: 'empty' }, [
      el('span', { html: icon('alert') }),
      el('h3', { text: '视图加载失败' }),
      el('p', { text: e.message || String(e) }),
      el('button', { class: 'btn', text: '重试', onClick: () => activateTab(id) }),
    ]));
  }
  ai && ai.setActiveTab(tab);
}

function currentPane() { return pane(state.workspace); }
function currentTab() { return activeTab(state.workspace); }

Object.assign(actions, {
  refs: null,
  setActiveEntity(ent) {
    state.activeEntity = ent;
    if (shell) shell.renderExplorer();
  },
  openTab(kind, params = {}, title = '') {
    const t = wsOpenTab(state.workspace, kind, params, { title });
    saveWorkspace(state.workspace);
    activateTab(t.id);
    return t;
  },
  activateTab,
  closeTab(id) {
    const next = wsCloseTab(state.workspace, id);
    if (!next) return;
    activateTab(next.id);
    saveWorkspace(state.workspace);
  },
  closeOtherTabs(keepId) {
    const p = currentPane();
    p.tabs = p.tabs.filter(t => t.id === keepId || t.pinned);
    if (!p.tabs.some(t => t.id === p.active_tab)) p.active_tab = p.tabs[0]?.id;
    shell.renderTabs();
    if (p.active_tab) activateTab(p.active_tab);
    saveWorkspace(state.workspace);
  },
  refreshTabs() { if (shell) shell.renderTabs(); },
  refreshExplorer() { if (shell) shell.renderExplorer(); },
  refreshStatus() { if (shell) shell.renderStatus(); },
  openDoc(docId, title = '资料', params = {}) {
    const t = wsOpenTab(state.workspace, 'doc', { docId: Number(docId), title, chunkId: params.chunkId || null, quote: params.quote || '', scrollTop: 0 }, { title });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openNote(noteId, title = '笔记') {
    const t = wsOpenTab(state.workspace, 'note', { noteId: Number(noteId), title }, { title });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  newNote(opts = {}) {
    const t = wsOpenTab(state.workspace, 'note', {
      noteId: null, title: '未命名笔记', partitionId: opts.partitionId || state.partitionId,
      nodeId: opts.nodeId || null,
    }, { title: '未命名笔记' });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openNode(nodeId, title = '节点') {
    const t = wsOpenTab(state.workspace, 'node', { nodeId: Number(nodeId), title }, { title });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openGraph(opts = {}) {
    const scope = opts.scope || 'global';
    const center = opts.center || (scope === 'local' ? centerOfActive() : null);
    const title = opts.title || (scope === 'local' ? `局部图谱 · ${opts.title || ''}` : '关系图谱');
    const t = wsOpenTab(state.workspace, 'graph', {
      scope, center: center || null, partitionId: state.partitionId,
      depth: opts.depth || 1, title: opts.title || '',
    }, { title: scope === 'local' ? '局部图谱' : '关系图谱' });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openSearch(q = '') {
    const t = wsOpenTab(state.workspace, 'search', { q }, { title: q ? `搜索：${q}` : '搜索' });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openSettings() {
    const t = wsOpenTab(state.workspace, 'settings', {}, { title: '设置' });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openWelcome() {
    const t = wsOpenTab(state.workspace, 'welcome', {}, { title: '欢迎' });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openMindmapList() {
    const t = wsOpenTab(state.workspace, 'mindmap', {}, { title: '知识导图' });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  openMindmap(name) {
    const t = wsOpenTab(state.workspace, 'mindmap', { mapName: name }, { title: name });
    saveWorkspace(state.workspace);
    activateTab(t.id);
  },
  async newMindmap() {
    const name = await promptDialog({ title: '新建知识导图', label: '导图名称', value: '未命名导图' });
    if (!name) return;
    try {
      const r = await api.post('/api/map/new', { name });
      if (r.ok === false) throw new Error(r.error || '新建失败');
      actions.openMindmap(r.name || name);
    } catch (e) { toast(e.message, { error: true }); }
  },
  async generateMindmap() {
    const tab = currentTab();
    const nodeId = tab?.kind === 'node' ? tab.params.nodeId : null;
    if (!nodeId && !state.partitionId) { toast('先选一个节点或分区'); return; }
    toast('正在按资料生成导图…');
    try {
      const r = await api.post('/api/rev/mindmap/generate_from_docs', {
        node: nodeId, scope: nodeId ? 'subtree' : 'all', partition: state.partitionId,
      });
      if (r.ok === false) throw new Error(r.error || '生成失败');
      if (r.warning) toast(r.warning, { ms: 4500 });
      actions.openMindmap(r.name);
    } catch (e) { toast(e.message, { error: true }); }
  },
  async openOriginal(docId) {
    try {
      const r = await api.post('/api/open', { doc_id: Number(docId) });
      if (r.ok === false) toast(r.error || '打开失败', { error: true });
    } catch (e) { toast(e.message, { error: true }); }
  },
  focusAI() {
    if (!shell) return;
    shell.refs.app.classList.remove('right-collapsed');
    shell.refs.app.classList.add('ai-open');
    state.workspace.layout.right_collapsed = false;
    saveWorkspace(state.workspace);
    requestAnimationFrame(() => ai && ai.focus());
  },
  askWithContext(ctx) {
    if (!ai) return;
    ai.setContext({ ...ctx, partition_id: ctx.partition_id || state.partitionId });
    actions.focusAI();
  },
  askSelection(sel) {
    if (!ai) return;
    ai.askSelection(sel);
    actions.focusAI();
  },
  async openCitation(src) {
    if (!src) return;
    const kind = src.source_kind || 'document';
    if (kind === 'note' || src.note_id) {
      actions.openNote(src.note_id, src.doc_title || src.title || '笔记');
      return;
    }
    if (src.doc_id) {
      actions.openDoc(src.doc_id, src.doc_title || src.title || '资料', {
        chunkId: src.chunk_id, quote: src.quote || src.snippet || '',
      });
      return;
    }
    toast('这条引用没有可定位的原文');
  },
  async saveAnswerAsNote(m) {
    const ctx = m.context || state.ai?.context;
    const sources = (m.sources || []).map(s => `- [${s.index || ''}] ${s.title || s.doc_title || ''}${s.heading_path ? ' › ' + s.heading_path : ''}`).join('\n');
    let body = `${m.content || ''}\n\n---\n\n来源：\n${sources || '（无）'}\n`;
    if (ctx?.kind === 'document' && ctx.doc_id) {
      body = `关联资料：[[doc:${ctx.doc_id}|${ctx.label || '当前文档'}]]\n\n` + body;
    }
    try {
      const r = await api.post('/api/v2/notes/save', {
        title: `伴学笔记 · ${new Date().toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`,
        body_md: body, partition_id: ctx?.partition_id || state.partitionId,
        node_id: ctx?.node_id || null,
      });
      if (r.ok === false) throw new Error(r.error || '保存失败');
      toast('已存为笔记');
      actions.openNote(r.note.id, r.note.title);
      actions.refreshNotes();
    } catch (e) { toast(e.message, { error: true }); }
  },
  toggleLeft() {
    if (!shell) return;
    const app = shell.refs.app;
    const narrow = innerWidth <= 920;
    if (narrow) { app.classList.toggle('left-open'); return; }
    const collapsed = !state.workspace.layout.left_collapsed;
    state.workspace.layout.left_collapsed = collapsed;
    app.classList.toggle('left-collapsed', collapsed);
    saveWorkspace(state.workspace);
  },
  toggleRight() {
    if (!shell) return;
    const app = shell.refs.app;
    const narrow = innerWidth <= 1180;
    if (narrow) { app.classList.toggle('ai-open'); return; }
    const collapsed = !state.workspace.layout.right_collapsed;
    state.workspace.layout.right_collapsed = collapsed;
    app.classList.toggle('right-collapsed', collapsed);
    saveWorkspace(state.workspace);
  },
  setTheme(theme) {
    applyTheme(state.workspace, theme);
    saveWorkspace(state.workspace);
    if (shell) shell.renderRibbon();
    const t = currentTab();
    if (t && t.kind === 'graph') activateTab(t.id, { silent: true });
    if (t && t.kind === 'settings') activateTab(t.id, { silent: true });
    toast(theme === 'system' ? '跟随系统主题' : theme === 'light' ? '浅色主题' : '深色主题');
  },
  async changePartition(pid) {
    if (!pid || pid === state.partitionId) return;
    state.partitionId = pid;
    localStorage.setItem('doclib.partition', String(pid));
    const t = currentTab();
    if (t && t.kind === 'graph') { t.params.partitionId = pid; }
    await loadPartitionData(pid);
    shell.renderExplorer(); shell.renderStatus();
    if (t && t.kind === 'graph') activateTab(t.id, { silent: true });
    else if (t && t.kind === 'search') activateTab(t.id, { silent: true });
    saveWorkspace(state.workspace);
  },
  async refreshData() {
    await loadPartitionData(state.partitionId);
    const t = currentTab();
    if (t && (t.kind === 'graph' || t.kind === 'node')) activateTab(t.id, { silent: true });
  },
  async refreshNotes() {
    const r = await api.get('/api/v2/notes', { partition: state.partitionId }).catch(() => ({ items: [] }));
    state.notes = r.items || [];
    if (shell) shell.renderExplorer();
  },
  async refreshProviders() {
    try {
      const r = await api.get('/api/ai/providers');
      state.providers = r.items || [];
      state.provider = r.current || state.provider;
      if (shell) shell.renderStatus();
    } catch {}
  },
  async createNode(parentId) {
    const name = await promptDialog({ title: '新建节点', label: '节点名称', value: '' });
    if (!name) return;
    try {
      const r = await api.post('/api/node/create', { name, parent_id: parentId ?? null });
      if (r.ok === false) throw new Error(r.error || '新建失败');
      await actions.refreshData();
    } catch (e) { toast(e.message, { error: true }); }
  },
  async renameNode(id, oldName) {
    const name = await promptDialog({ title: '重命名节点', label: '名称', value: oldName });
    if (!name || name === oldName) return;
    try {
      const r = await api.post('/api/node/rename', { id, name });
      if (r.ok === false) throw new Error(r.error || '重命名失败');
      await actions.refreshData();
    } catch (e) { toast(e.message, { error: true }); }
  },
  async deleteNode(id, name) {
    if (!await confirmDialog('删除节点', `删除「${name}」及其子树？只挂在这些节点上的资料会回到「未分类」。`, { danger: true, okText: '删除' })) return;
    try {
      const r = await api.post('/api/node/delete', { id });
      if (r.ok === false) throw new Error(r.error || '删除失败');
      await actions.refreshData();
    } catch (e) { toast(e.message, { error: true }); }
  },
  importDialog() {
    const body = el('div');
    const path = el('input', { class: 'input', placeholder: '输入文件/文件夹的绝对路径，或点“选择…”' });
    const result = el('div', { class: 'import-result' });
    const run = async (mode) => {
      clear(result); result.append(el('div', { class: 'loading-line' }, [el('span', { class: 'spin' }), el('span', { text: mode ? '请在弹出的系统窗口中选择…' : '正在导入…' })]));
      try {
        const payload = mode ? { mode, partition: state.partitionId } : { path: path.value.trim(), partition: state.partitionId };
        const r = await api.post('/api/rev/import', payload);
        if (r.ok === false) throw new Error(r.error || '导入失败');
        clear(result);
        const summary = el('div', { class: 'hint', text: `新增 ${r.imported || 0} · 更新 ${r.updated || 0} · 未变 ${r.unchanged || 0} · 失败 ${r.failed || 0}` });
        result.append(summary);
        for (const it of (r.items || []).slice(0, 200)) {
          const status = it.status === 'imported' ? '新增' : it.status === 'updated' ? '更新' : it.status === 'unchanged' ? '未变' : it.status === 'relocated' ? '迁移' : it.status === 'failed' ? '失败' : '跳过';
          result.append(el('div', { class: 'import-row' }, [
            el('span', { class: `st ${it.status === 'failed' ? 'fail' : 'ok'}`, text: status }),
            el('span', { class: 'nm', text: it.title || it.file || '' }),
            el('span', { class: 'note', text: it.note || '' }),
          ]));
        }
        await actions.refreshData();
      } catch (e) {
        clear(result); result.append(el('div', { class: 'error-box' }, [el('b', { text: '导入失败' }), el('div', { text: e.message })]));
      }
    };
    body.append(el('div', { class: 'field' }, [el('label', { text: '路径' }), path]));
    body.append(el('div', { class: 'row' }, [
      el('button', { class: 'btn', text: '选择文件…', onClick: () => run('files') }),
      el('button', { class: 'btn', text: '选择文件夹…', onClick: () => run('folder') }),
      el('button', { class: 'btn primary', text: '导入路径', onClick: () => run('') }),
    ]));
    body.append(el('div', { class: 'hint', style: { marginTop: '8px' }, text: '导入会解析全文、切块并自动挂载；失败原因会逐条显示。' }));
    body.append(result);
    modal({ title: '导入资料', body, width: 'min(720px,96vw)' });
  },
});

function centerOfActive() {
  if (state.activeEntity) return `${state.activeEntity.kind === 'doc' ? 'document' : state.activeEntity.kind}:${state.activeEntity.id}`;
  return null;
}

function bindKeys() {
  document.addEventListener('keydown', e => {
    const tag = (e.target?.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || e.target?.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      if (typing) return; // 笔记编辑器自己处理
      e.preventDefault(); toast('当前视图没有需要保存的内容');
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'w') { e.preventDefault(); const t = currentTab(); if (t) actions.closeTab(t.id); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Tab') {
      e.preventDefault();
      const p = currentPane(); const i = p.tabs.findIndex(t => t.id === p.active_tab);
      const n = p.tabs[(i + (e.shiftKey ? -1 : 1) + p.tabs.length) % p.tabs.length];
      if (n) actions.activateTab(n.id);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); actions.openSearch(''); return; }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'b') { e.preventDefault(); actions.toggleLeft(); return; }
    if ((e.ctrlKey || e.metaKey) && e.altKey && e.key.toLowerCase() === 'b') { e.preventDefault(); actions.toggleRight(); return; }
    if (e.key === 'Escape') {
      if (shell) { shell.refs.app.classList.remove('ai-open', 'left-open'); }
      document.querySelectorAll('.modal-mask,.menu,.sel-toolbar').forEach(n => n.remove());
    }
  });
}

function installDropImport() {
  document.addEventListener('dragover', e => { e.preventDefault(); });
  document.addEventListener('drop', e => {
    e.preventDefault();
    const files = e.dataTransfer?.files;
    if (!files || !files.length) return;
    toast('桌面拖入导入将在后续版本提供；请使用「导入资料」选择文件。');
  });
}

boot();
