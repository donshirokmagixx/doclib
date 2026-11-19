// 应用外壳：Ribbon / 资料库 / 标签 / 状态栏 / 面板拖拽
import { el, clear, icon, menu, confirmDialog, promptDialog, toast } from './core.js';
import { pane, activeTab, save, applyTheme, tabTitle } from './workspace.js';

const collapsedKey = 'doclib.explorer.collapsed.v2';

export function mountShell(root, state, actions) {
  clear(root);
  const app = el('div', { class: 'app-shell' });
  const ribbon = el('aside', { class: 'ribbon', 'aria-label': '主导航' });
  const explorer = el('aside', { class: 'explorer', 'aria-label': '资料库' });
  const center = el('main', { class: 'center' });
  const tabbar = el('div', { class: 'tabbar' });
  const tabBody = el('div', { class: 'tab-body' });
  const aiPanel = el('aside', { class: 'ai-panel', id: 'ai-panel', 'aria-label': 'AI 伴学' });
  const statusbar = el('footer', { class: 'statusbar' });
  center.append(tabbar, tabBody);
  app.append(ribbon, explorer, center, aiPanel, statusbar);
  root.append(app);

  const refs = { app, ribbon, explorer, tabbar, tabBody, aiPanel, statusbar };
  actions.refs = refs;
  renderRibbon();
  renderExplorer();
  renderTabs();
  renderStatus();
  initResizers();
  applyLayout();

  function renderRibbon() {
    clear(ribbon);
    ribbon.append(el('button', {
      class: 'rbtn', title: 'DocLib 2.0', html: `<svg class="logo" viewBox="0 0 28 28" fill="none" aria-hidden="true">
        <path d="M6 8.2c3.2-1.2 5.6-1.2 8 0 2.4 1.2 4.8 1.2 8 0v12c-3.2 1.2-5.6 1.2-8 0-2.4-1.2-4.8-1.2-8 0z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
        <path d="M14 8.4v11.8" stroke="currentColor" stroke-width="1.1" opacity=".55"/>
        <circle cx="20.6" cy="6.7" r="2.2" fill="var(--ribbon)" stroke="currentColor" stroke-width="1.3"/></svg>`,
      onClick: () => actions.openWelcome(),
    }));
    const cur = activeTab(state.workspace);
    const btn = (name, title, fn, active) => el('button', {
      class: `rbtn${active ? ' active' : ''}`, title, html: icon(name), onClick: fn,
    });
    ribbon.append(btn('files', '资料库', () => actions.toggleLeft(), cur && cur.kind === 'doc'));
    ribbon.append(btn('search', '搜索（Ctrl+Shift+F）', () => actions.openSearch(''), cur && cur.kind === 'search'));
    ribbon.append(btn('graph', '关系图谱', () => actions.openGraph({ scope: 'global' }), cur && cur.kind === 'graph'));
    ribbon.append(btn('note', '新建笔记', () => actions.newNote(), cur && cur.kind === 'note'));
    ribbon.append(btn('mind', '知识导图', () => actions.openMindmapList(), cur && cur.kind === 'mindmap'));
    ribbon.append(el('div', { class: 'grow' }));
    ribbon.append(btn('spark', 'AI 伴学（Ctrl+Alt+B）', () => actions.toggleRight(), false));
    ribbon.append(btn('theme', '切换主题', () => {
      const real = document.documentElement.dataset.theme;
      actions.setTheme(real === 'dark' ? 'light' : 'dark');
    }));
    ribbon.append(btn('settings', '设置', () => actions.openSettings()));
  }

  function renderExplorer() {
    clear(explorer);
    const part = state.partitions.find(p => p.id === state.partitionId);
    const head = el('div', { class: 'exp-head' }, [
      el('b', { text: '资料库' }),
      el('span', { class: 'count', text: String(state.stats?.documents ?? state.docs.length ?? 0) }),
      el('div', { class: 'spacer' }),
      el('button', { class: 'btn icon', title: '搜索', html: icon('search'), onClick: () => actions.openSearch('') }),
      el('button', { class: 'btn icon', title: '导入资料', html: icon('plus'), onClick: () => actions.importDialog() }),
      el('button', { class: 'btn icon', title: '收起资料库', html: icon('panelLeft'), onClick: () => actions.toggleLeft() }),
    ]);
    explorer.append(head);
    const psel = el('select', { class: 'select', title: '切换科目分区' });
    for (const p of state.partitions) {
      const o = el('option', { value: String(p.id), text: `${p.name}${p.doc_count ? ` · ${p.doc_count}` : ''}` });
      if (p.id === state.partitionId) o.selected = true;
      psel.append(o);
    }
    psel.addEventListener('change', () => actions.changePartition(Number(psel.value)));
    explorer.append(el('div', { class: 'partition-row' }, [
      el('span', { class: 'dot' }), psel,
    ]));

    const scroll = el('div', { class: 'exp-scroll' });
    scroll.append(section('知识结构', state.tree.length, treeList(state.tree, 0)));
    const unmounted = state.docs.filter(d => !(d.node_ids || []).length);
    if (unmounted.length) scroll.append(section('未归档资料', unmounted.length, docList(unmounted)));
    scroll.append(section('笔记', state.notes.length, noteList()));
    explorer.append(scroll);
    explorer.append(el('div', { class: 'exp-foot' }, [
      el('span', { class: 'mono', text: `${state.stats?.nodes ?? 0} 节点` }),
      el('span', { class: 'spacer', style: { flex: 1 } }),
      el('button', { class: 'btn icon', title: '在资料库中搜索', html: icon('search'), onClick: () => actions.openSearch('') }),
    ]));
  }

  function section(title, count, body) {
    return el('div', { class: 'exp-section' }, [
      el('div', { class: 'exp-title' }, [
        el('span', { text: title }),
        el('span', { class: 'spacer', style: { flex: 1 } }),
        el('span', { text: String(count || 0) }),
      ]),
      body,
    ]);
  }

  function treeList(nodes, depth) {
    const ul = el('ul', { class: 'tree-root' });
    for (const n of nodes || []) {
      const hasKids = (n.children || []).length > 0;
      const key = String(n.id);
      const collapsed = collapsedSet().has(key);
      const active = state.activeEntity && state.activeEntity.kind === 'node' && Number(state.activeEntity.id) === Number(n.id);
      const row = el('div', { class: `tree-row${active ? ' active' : ''}`, title: n.name, dataset: { id: n.id } }, [
        el('span', { class: 'caret', text: hasKids ? (collapsed ? '▸' : '▾') : '' }),
        el('span', { class: 'nm', text: n.name }),
        el('span', { class: 'cnt', text: String(n.doc_count ?? n._sub_count ?? '') }),
      ]);
      row.addEventListener('click', e => {
        if (e.target.closest('.caret') && hasKids) {
          const s = collapsedSet();
          if (s.has(key)) s.delete(key); else s.add(key);
          localStorage.setItem(collapsedKey, JSON.stringify([...s]));
          renderExplorer();
          return;
        }
        actions.openNode(n.id, n.name);
      });
      row.addEventListener('contextmenu', e => {
        e.preventDefault();
        menu(e.clientX, e.clientY, [
          { label: '打开节点概览', icon: 'bookOpen', onClick: () => actions.openNode(n.id, n.name) },
          { label: '局部关系图谱', icon: 'graph', onClick: () => actions.openGraph({ scope: 'local', center: `node:${n.id}`, nodeId: n.id, title: n.name }) },
          { sep: true },
          { label: '新建子节点', icon: 'plus', onClick: () => actions.createNode(n.id) },
          { label: '新建笔记', icon: 'note', onClick: () => actions.newNote({ nodeId: n.id, partitionId: state.partitionId }) },
          { sep: true },
          { label: '重命名', icon: 'edit', onClick: () => actions.renameNode(n.id, n.name) },
          { label: '删除节点', icon: 'trash', danger: true, onClick: () => actions.deleteNode(n.id, n.name) },
        ]);
      });
      const li = el('li', {}, [row]);
      if (hasKids && !collapsed) li.append(treeList(n.children, depth + 1));
      if (!collapsed) {
        for (const d of docsUnder(n.id)) {
          const activeDoc = state.activeEntity && state.activeEntity.kind === 'document' && Number(state.activeEntity.id) === Number(d.doc_id);
          const docRow = el('div', { class: `tree-row doc${activeDoc ? ' active' : ''}`, title: d.title }, [
            el('span', { class: 'caret' }),
            el('span', { html: icon(fileIconFor(d.file_path)) }),
            el('span', { class: 'nm', text: d.title }),
          ]);
          docRow.addEventListener('click', () => actions.openDoc(d.doc_id, d.title));
          li.append(docRow);
        }
      }
      ul.append(li);
    }
    return ul;
  }

  function collapsedSet() {
    try { return new Set(JSON.parse(localStorage.getItem(collapsedKey) || '[]')); } catch { return new Set(); }
  }

  function docsUnder(nodeId) {
    return (state.docs || []).filter(d => (d.node_ids || []).map(Number).includes(Number(nodeId)));
  }

  function fileIconFor(path) {
    const p = String(path || '').toLowerCase();
    if (p.includes('.pdf')) return 'filePdf';
    if (p.includes('.doc')) return 'fileDoc';
    if (p.includes('.md') || p.includes('.txt')) return 'fileText';
    return 'fileText';
  }

  function docList(docs = state.docs) {
    const ul = el('div', { class: 'doc-list' });
    const shown = docs.slice(0, 120);
    if (!shown.length) {
      ul.append(el('div', { class: 'hint', style: { padding: '4px 7px' }, text: '还没有资料，点右上角 ＋ 导入。' }));
      return ul;
    }
    for (const d of shown) {
      const active = state.activeEntity && state.activeEntity.kind === 'document' && Number(state.activeEntity.id) === Number(d.doc_id);
      const row = el('div', { class: `tree-row doc${active ? ' active' : ''}`, title: d.title }, [
        el('span', { class: 'caret' }),
        el('span', { html: icon('filePdf') }),
        el('span', { class: 'nm', text: d.title }),
      ]);
      row.addEventListener('click', () => actions.openDoc(d.doc_id, d.title));
      row.addEventListener('contextmenu', e => {
        e.preventDefault();
        menu(e.clientX, e.clientY, [
          { label: '打开阅读', icon: 'bookOpen', onClick: () => actions.openDoc(d.doc_id, d.title, { chunkId: d.chunk_id || null }) },
          { label: '局部关系图谱', icon: 'graph', onClick: () => actions.openGraph({ scope: 'local', center: `document:${d.doc_id}`, title: d.title }) },
          { sep: true },
          { label: '打开原文件', icon: 'external', onClick: () => actions.openOriginal(d.doc_id) },
        ]);
      });
      ul.append(row);
    }
    if (state.docs.length > shown.length) {
      ul.append(el('div', { class: 'hint', style: { padding: '5px 7px' }, text: `还有 ${state.docs.length - shown.length} 份，用搜索查找。` }));
    }
    return ul;
  }

  function noteList() {
    const box = el('div', { class: 'doc-list' });
    if (!state.notes.length) {
      box.append(el('div', { class: 'hint', style: { padding: '4px 7px' }, text: '还没有笔记，点 Ribbon 的笔记按钮新建。' }));
      return box;
    }
    for (const n of state.notes.slice(0, 60)) {
      const active = state.activeEntity && state.activeEntity.kind === 'note' && Number(state.activeEntity.id) === Number(n.id);
      const row = el('div', { class: `tree-row note${active ? ' active' : ''}`, title: n.title }, [
        el('span', { class: 'caret' }), el('span', { class: 'dot' }),
        el('span', { class: 'nm', text: n.title }),
      ]);
      row.addEventListener('click', () => actions.openNote(n.id, n.title));
      box.append(row);
    }
    return box;
  }

  function renderTabs() {
    clear(tabbar);
    const p = pane(state.workspace);
    const scroll = el('div', { class: 'tabs-scroll' });
    for (const t of p.tabs) {
      const active = t.id === p.active_tab;
      const tab = el('div', { class: `tab${active ? ' active' : ''}`, title: t.title, dataset: { id: t.id } }, [
        el('span', { class: 'icon', html: icon(tabIcon(t)) }),
        el('span', { class: 't', text: t.title || tabTitle(t) }),
        el('button', { class: 'x', title: '关闭', html: icon('close'), onClick: (e) => { e.stopPropagation(); actions.closeTab(t.id); } }),
      ]);
      tab.addEventListener('click', () => actions.activateTab(t.id));
      tab.addEventListener('contextmenu', e => {
        e.preventDefault();
        menu(e.clientX, e.clientY, [
          { label: '关闭', icon: 'close', kbd: 'Ctrl+W', onClick: () => actions.closeTab(t.id) },
          { label: '关闭其他标签', onClick: () => actions.closeOtherTabs(t.id) },
          { sep: true },
          { label: '复制标签标题', icon: 'copy', onClick: () => navigator.clipboard?.writeText(t.title) },
        ]);
      });
      scroll.append(tab);
    }
    tabbar.append(scroll);
    tabbar.append(el('button', { class: 'btn icon add', title: '新建标签', html: icon('plus'), onClick: (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      menu(r.left, r.bottom + 4, [
        { label: '关系图谱', icon: 'graph', onClick: () => actions.openGraph({ scope: 'global' }) },
        { label: '新建笔记', icon: 'note', onClick: () => actions.newNote() },
        { label: '搜索', icon: 'search', onClick: () => actions.openSearch('') },
        { label: '知识导图', icon: 'mind', onClick: () => actions.openMindmapList() },
        { label: '设置', icon: 'settings', onClick: () => actions.openSettings() },
      ]);
    } }));
    tabbar.append(el('div', { class: 'spacer' }));
    tabbar.append(el('div', { class: 'tools' }, [
      el('button', { class: 'btn icon', title: '收起/展开资料库 (Ctrl+B)', html: icon('panelLeft'), onClick: () => actions.toggleLeft() }),
      el('button', { class: 'btn icon', title: '收起/展开 AI (Ctrl+Alt+B)', html: icon('panelRight'), onClick: () => actions.toggleRight() }),
    ]));
  }

  function tabIcon(t) {
    switch (t.kind) {
      case 'graph': return 'graph';
      case 'doc': return 'filePdf';
      case 'note': return 'note';
      case 'node': return 'bookOpen';
      case 'search': return 'search';
      case 'mindmap': return 'mind';
      case 'settings': return 'settings';
      default: return 'book';
    }
  }

  function renderStatus() {
    clear(statusbar);
    const s = state.stats || {};
    const seg = (text, cls = '') => el('span', { class: cls, text });
    statusbar.append(seg(`${s.documents ?? state.docs.length ?? 0} 份资料`));
    statusbar.append(el('span', { class: 'sep' }));
    statusbar.append(seg(`${s.chunks ?? 0} 块`));
    statusbar.append(el('span', { class: 'sep' }));
    statusbar.append(seg(`${s.nodes ?? 0} 节点`));
    statusbar.append(el('span', { class: 'sep' }));
    statusbar.append(seg(state.health?.trigram ? '索引就绪' : '索引检查中', 'ok'));
    statusbar.append(el('span', { class: 'sep' }));
    statusbar.append(seg(state.provider ? `模型 ${state.provider}` : '未配置模型'));
    statusbar.append(el('div', { class: 'grow', style: { flex: 1 } }));
    statusbar.append(seg('本地运行 · 数据不出本机'));
    statusbar.append(seg('v2.0.0-dev'));
  }

  function applyLayout() {
    const l = state.workspace.layout || {};
    app.style.setProperty('--left-w', `${app.classList.contains('left-collapsed') ? 0 : (l.left_width || 268)}px`);
    app.style.setProperty('--ai-w', `${app.classList.contains('right-collapsed') ? 0 : (l.right_width || 374)}px`);
    app.classList.toggle('left-collapsed', !!l.left_collapsed || isNarrowLeft());
    app.classList.toggle('right-collapsed', !!l.right_collapsed);
  }

  function isNarrowLeft() { return innerWidth <= 920 && !app.classList.contains('left-open'); }

  function initResizers() {
    // 左侧分隔条：放在 explorer 内
    const left = el('div', { class: 'resizer left', title: '拖动调整资料库宽度' });
    const right = el('div', { class: 'resizer right', title: '拖动调整 AI 面板宽度' });
    explorer.append(left);
    aiPanel.append(right);
    bindResize(left, 'left');
    bindResize(right, 'right');
  }

  function bindResize(handle, side) {
    let startX = 0, startW = 0, dragging = false;
    const onMove = e => {
      if (!dragging) return;
      const l = state.workspace.layout;
      if (side === 'left') {
        const pw = Math.max(200, Math.min(420, startW + (e.clientX - startX)));
        l.left_width = Math.round(pw);
        app.style.setProperty('--left-w', `${l.left_width}px`);
      } else {
        const pw = Math.max(300, Math.min(560, startW - (e.clientX - startX)));
        l.right_width = Math.round(pw);
        app.style.setProperty('--ai-w', `${l.right_width}px`);
      }
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false; handle.classList.remove('dragging');
      document.body.style.cursor = '';
      save(state.workspace);
    };
    handle.addEventListener('pointerdown', e => {
      if (innerWidth <= 1180) return;
      dragging = true;
      startX = e.clientX;
      startW = side === 'left' ? (state.workspace.layout.left_width || 268) : (state.workspace.layout.right_width || 374);
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      handle.setPointerCapture?.(e.pointerId);
      e.preventDefault();
    });
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
    handle.addEventListener('pointercancel', onUp);
    handle.addEventListener('dblclick', () => {
      if (side === 'left') state.workspace.layout.left_width = 268;
      else state.workspace.layout.right_width = 374;
      applyLayout(); save(state.workspace);
    });
  }

  return {
    refs,
    renderAll() { renderRibbon(); renderExplorer(); renderTabs(); renderStatus(); applyLayout(); },
    renderExplorer, renderTabs, renderStatus, applyLayout, renderRibbon,
    setAI(panel) { clear(aiPanel); aiPanel.append(panel); },
  };
}
