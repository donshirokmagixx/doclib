// 右侧 AI 伴学：完整高度、独立滚动、上下文真实生效
import { el, clear, icon, api, toast, fmtTime, escapeHtml } from './core.js';

export function createAIPanel(state, actions) {
  if (!state.ai) {
    state.ai = { conversationId: null, messages: [], context: null, pendingSelection: null, busy: false, historyOpen: false, model: '', error: '' };
  }
  const head = el('div', { class: 'ai-head' });
  const historyBox = el('div', { class: 'ai-history', hidden: true });
  const contextBox = el('div', { class: 'ai-context' });
  const msgs = el('div', { class: 'ai-msgs' });
  const composer = el('div', { class: 'ai-composer' });
  const root = el('div', { style: { display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' } },
    [head, historyBox, contextBox, msgs, composer]);

  renderHead();
  renderContext();
  renderMessages();
  renderComposer();
  refreshHistory();

  function renderHead() {
    clear(head);
    head.append(el('span', { class: 'dot' }));
    head.append(el('b', { text: '伴学' }));
    const sel = el('select', { class: 'model-select', title: '当前模型' });
    const provs = state.providers || [];
    if (!provs.length) sel.append(el('option', { value: '', text: '未配置模型' }));
    for (const p of provs) {
      const o = el('option', { value: p.name, text: p.name + (p.is_default ? ' · 默认' : '') });
      if (p.name === state.provider || p.is_default) o.selected = true;
      sel.append(o);
    }
    sel.addEventListener('change', async () => {
      const name = sel.value; if (!name) return;
      try {
        const r = await api.post('/api/ai/providers/default', { name });
        if (r && r.ok === false) throw new Error(r.error || '切换失败');
        state.provider = name;
        toast(`已切换到 ${name}`);
        actions.onProviderChange && actions.onProviderChange(name);
      } catch (e) { toast(e.message || '切换失败', { error: true }); }
    });
    head.append(sel);
    head.append(el('div', { class: 'spacer' }));
    head.append(el('button', { class: 'btn icon', title: '历史会话', html: icon('history'), onClick: toggleHistory }));
    head.append(el('button', { class: 'btn icon', title: '导出当前会话 Word', html: icon('external'), onClick: exportWord }));
    head.append(el('button', { class: 'btn icon', title: '新对话', html: icon('plus'), onClick: newConversation }));
    head.append(el('button', { class: 'btn icon', title: '收起 AI 面板', html: icon('panelRight'), onClick: () => actions.toggleRight() }));
  }

  function renderContext() {
    clear(contextBox);
    const ctx = state.ai.context;
    const box = el('div', { class: 'context-box' });
    box.append(el('span', { class: 'lbl', text: '范围' }));
    box.append(el('span', { class: 'ctx-text', text: ctx ? (ctx.label || contextDefaultLabel(ctx)) : '当前分区' }));
    const sel = el('select', { class: 'ctx-select', title: '选择本轮 AI 检索范围' });
    const options = contextOptions();
    for (const o of options) {
      const opt = el('option', { value: o.mode, text: o.label });
      if (o.mode === state.ai.contextMode) opt.selected = true;
      sel.append(opt);
    }
    sel.addEventListener('change', () => {
      state.ai.contextMode = sel.value;
      state.ai.context = contextForMode(sel.value);
      state.ai.pendingSelection = state.ai.context?.kind === 'selection' ? state.ai.context : null;
      renderContext();
      renderMessages();
    });
    box.append(sel);
    contextBox.append(box);
    if (state.ai.pendingSelection) {
      contextBox.append(el('div', { class: 'hint', style: { marginTop: '4px' }, text: `已带入选文 ${state.ai.pendingSelection.quote.length} 字；发送后仅在该文档内检索。` }));
    }
  }

  function contextOptions() {
    const t = state.activeTab;
    const all = state.partitionId == null;
    const out = [{ mode: 'auto', label: '跟随当前内容' },
      { mode: 'partition', label: all ? '全部资料库' : '当前分区' }];
    if (t && t.kind === 'doc') out.push({ mode: 'document', label: '当前文档' });
    if (t && t.kind === 'note') out.push({ mode: 'note', label: '当前笔记' });
    if (t && (t.kind === 'node' || (t.kind === 'graph' && t.params?.scope === 'local'))) out.push({ mode: 'node', label: '当前节点' });
    if (state.ai.pendingSelection) out.push({ mode: 'selection', label: '选中文字' });
    if (state.ai.context && state.ai.contextMode && !out.some(o => o.mode === state.ai.contextMode)) {
      out.push({ mode: state.ai.contextMode, label: state.ai.context.label || '会话范围' });
    }
    return out;
  }

  function contextDefaultLabel(ctx) {
    if (!ctx) return '';
    return { partition: '当前分区', node: '当前节点', document: '当前文档', selection: '选中文字', note: '当前笔记', all: '全部资料库' }[ctx.kind] || '';
  }

  function partitionContext(pid) {
    if (pid == null) return { kind: 'all', partition_id: null, label: '全部资料库' };
    return { kind: 'partition', partition_id: pid, label: `当前分区 · ${state.partitions.find(p => p.id === pid)?.name || ''}` };
  }

  function contextForMode(mode) {
    const t = state.activeTab;
    const pid = state.partitionId;
    if (mode === 'auto') return defaultContextForTab(t);
    if (mode === 'selection' && state.ai.pendingSelection) return state.ai.pendingSelection;
    if (mode === 'document' && t && t.kind === 'doc') {
      return { kind: 'document', doc_id: t.params.docId, partition_id: pid, label: `当前文档 · ${t.title}` };
    }
    if (mode === 'note' && t && t.kind === 'note') {
      return { kind: 'note', note_id: t.params.noteId, partition_id: pid, label: `当前笔记 · ${t.title}` };
    }
    if (mode === 'node') {
      if (t && t.kind === 'node') return { kind: 'node', node_id: t.params.nodeId, partition_id: pid, label: `当前节点 · ${t.title}` };
      if (t && t.kind === 'graph' && t.params?.scope === 'local') {
        const c = String(t.params.center || '');
        const m = /^node:(\d+)$/.exec(c);
        if (m) return { kind: 'node', node_id: Number(m[1]), partition_id: pid, label: `当前节点 · ${t.params?.title || t.title}` };
        const d = /^document:(\d+)$/.exec(c);
        if (d) return { kind: 'document', doc_id: Number(d[1]), partition_id: pid, label: `当前文档 · ${t.params?.title || t.title}` };
      }
    }
    return partitionContext(pid);
  }

  function defaultContextForTab(tab) {
    if (!tab) return partitionContext(state.partitionId);
    if (tab.kind === 'doc') return { kind: 'document', doc_id: tab.params.docId, partition_id: state.partitionId, label: `当前文档 · ${tab.title}` };
    if (tab.kind === 'note') return { kind: 'note', note_id: tab.params.noteId, partition_id: state.partitionId, label: `当前笔记 · ${tab.title}` };
    if (tab.kind === 'node') return { kind: 'node', node_id: tab.params.nodeId, partition_id: state.partitionId, label: `当前节点 · ${tab.title}` };
    if (tab.kind === 'graph' && tab.params?.scope === 'local') {
      const c = String(tab.params.center || '');
      const m = /^node:(\d+)$/.exec(c);
      if (m) return { kind: 'node', node_id: Number(m[1]), partition_id: state.partitionId, label: `当前节点 · ${tab.params?.title || tab.title}` };
      const d = /^document:(\d+)$/.exec(c);
      if (d) return { kind: 'document', doc_id: Number(d[1]), partition_id: state.partitionId, label: `当前文档 · ${tab.params?.title || tab.title}` };
    }
    return partitionContext(state.partitionId);
  }

  function setActiveTab(tab) {
    state.activeTab = tab;
    const sel = state.ai.pendingSelection;
    if (sel && (tab?.kind !== 'doc' || Number(tab.params?.docId) !== Number(sel.doc_id))) {
      state.ai.pendingSelection = null;
      const ta = composer.querySelector('textarea');
      if (ta && ta.value === '解释这段内容：') ta.value = '';
      setComposerHint('实际检索范围以上方「范围」为准');
    }
    // 自动跟随中央内容；用户可随时用下拉改为当前分区/文档/节点
    state.ai.contextMode = 'auto';
    state.ai.context = defaultContextForTab(tab);
    renderContext();
  }

  function askSelection(sel) {
    const ctx = {
      kind: 'selection', doc_id: sel.docId, partition_id: state.partitionId,
      chunk_id: sel.chunkId || null, quote: sel.quote, heading_path: sel.headingPath || '',
      label: `选中文字 · ${sel.quote.slice(0, 18)}${sel.quote.length > 18 ? '…' : ''}`,
    };
    state.ai.pendingSelection = ctx;
    state.ai.context = ctx;
    state.ai.contextMode = 'selection';
    renderContext();
    const ta = composer.querySelector('textarea');
    ta.value = ta.value || '解释这段内容：';
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    setComposerHint('选文已带入；提问范围 = 当前文档 + 选文');
  }

  function setComposerHint(text) {
    const h = composer.querySelector('.hint');
    if (h) h.textContent = text;
  }

  function renderComposer() {
    clear(composer);
    const box = el('div', { class: 'composer-box' });
    const ta = el('textarea', { placeholder: '就当前内容继续追问…（Ctrl+Enter 发送）' });
    const bar = el('div', { class: 'composer-bar' });
    const hint = el('span', { class: 'hint', text: '实际检索范围以上方「范围」为准' });
    const send = el('button', { class: 'send-btn', title: '发送', html: icon('send') });
    send.addEventListener('click', sendQuestion);
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendQuestion(); }
    });
    bar.append(hint, send);
    box.append(ta, bar);
    composer.append(box);
    composer.append(el('div', { class: 'ai-hint' }, [
      el('span', { html: `<span class="kbd">Ctrl</span> <span class="kbd">Enter</span> 发送` }),
      el('span', { text: '资料不出本机' }),
    ]));
  }

  async function sendQuestion() {
    if (state.ai.busy) return;
    const ta = composer.querySelector('textarea');
    const q = (ta.value || '').trim();
    if (!q) { toast('先输入问题'); return; }
    const ctx = state.ai.context || defaultContextForTab(state.activeTab);
    if (!ctx) { toast('没有可用的检索范围'); return; }
    state.ai.busy = true;
    const send = composer.querySelector('.send-btn');
    if (send) send.disabled = true;
    const userMsg = { role: 'user', content: q, context: ctx, created_at: Date.now() };
    state.ai.messages.push(userMsg);
    renderMessages();
    setComposerHint('检索资料并生成回答…');
    try {
      const body = {
        question: q,
        context: contextPayload(ctx),
        conversation_id: state.ai.conversationId || null,
        partition: ctx.partition_id ?? state.partitionId,
        scope: ctx.kind === 'node' ? 'subtree' : 'all',
        node: ctx.node_id || null,
      };
      const r = await api.post('/api/rev/ask', body);
      if (!r || r.ok === false) throw new Error((r && r.error) || '提问失败');
      state.ai.conversationId = r.conversation_id || state.ai.conversationId;
      state.ai.messages.push({
        role: 'assistant', content: r.answer || '', sources: r.sources || [],
        insufficient: !!r.insufficient, notice: r.notice || '',
        model: r.model, provider: r.provider, usage: r.usage, cost_yuan: r.cost_yuan,
        latency_ms: r.latency_ms, cached: r.cached, context: r.context || ctx,
        citation_status: r.citation_status, created_at: Date.now(),
      });
      state.ai.pendingSelection = null;
      ta.value = '';
      setComposerHint('实际检索范围以上方「范围」为准');
      renderContext();
      renderMessages(true);
      refreshHistory();
    } catch (e) {
      state.ai.messages.push({ role: 'assistant', content: `请求失败：${e.message}`, error: true, created_at: Date.now() });
      renderMessages(true);
    } finally {
      state.ai.busy = false;
      if (send) send.disabled = false;
    }
  }

  function contextPayload(ctx) {
    const out = { kind: ctx.kind, partition_id: ctx.partition_id ?? null };
    if (ctx.node_id != null) out.node_id = ctx.node_id;
    if (ctx.doc_id != null) out.doc_id = ctx.doc_id;
    if (ctx.note_id != null) out.note_id = ctx.note_id;
    if (ctx.chunk_id != null) out.chunk_id = ctx.chunk_id;
    if (ctx.quote) out.quote = ctx.quote;
    if (ctx.heading_path) out.heading_path = ctx.heading_path;
    return out;
  }

  function renderMessages(scroll = false) {
    clear(msgs);
    if (!state.ai.messages.length) {
      msgs.append(emptyState());
      return;
    }
    for (const m of state.ai.messages) msgs.append(messageNode(m));
    if (scroll) requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
  }

  function emptyState() {
    const ctx = state.ai.context;
    const box = el('div', { class: 'ai-empty' });
    box.append(el('b', { text: ctx ? (ctx.label || '开始一次伴学') : '开始一次伴学' }));
    box.append(el('div', { text: ctx ? '我会只依据你选择的资料范围回答；引用可点回原文。' : '先打开一份资料或选择一个节点。' }));
    const examples = el('div', { class: 'examples' });
    const qs = ctx && ctx.kind === 'document'
      ? ['这篇资料的核心结论是什么？', '把这一节的概念用更直白的话解释。', '这一节和前后章节是什么关系？']
      : ['当前分区里最重要的三个概念是什么？', '把当前节点的资料整理成复习提纲。', '哪些资料支持这个结论？'];
    for (const q of qs) {
      const b = el('button', { class: 'example', text: q });
      b.addEventListener('click', () => {
        const ta = composer.querySelector('textarea');
        ta.value = q; ta.focus();
      });
      examples.append(b);
    }
    box.append(examples);
    return box;
  }

  function messageNode(m) {
    const isUser = m.role === 'user';
    const box = el('div', { class: `msg ${isUser ? 'user' : 'assistant'}` });
    box.append(el('div', { class: 'gutter', text: isUser ? '你' : 'AI' }));
    const body = el('div', { class: 'body' });
    if (isUser) {
      body.append(el('div', { text: m.content }));
    } else if (m.error) {
      body.append(el('div', { class: 'error-box' }, [el('b', { text: '请求失败' }), el('div', { text: m.content })]));
    } else {
      const html = escapeHtml(m.content || '')
        .replace(/\n/g, '<br>')
        .replace(/\[(\d+)\]/g, '<button class="cite" data-cite="$1">[$1]</button>');
      body.append(el('div', { html }));
      if (m.insufficient) {
        body.append(el('div', { class: 'tag warn', style: { marginTop: '6px', display: 'inline-block' }, text: m.notice || '资料不足：没有可引用的原文片段' }));
      }
      const sources = m.sources || [];
      if (sources.length) {
        const src = el('div', { class: 'sources' });
        for (const s of sources) {
          const b = el('button', { text: sourceLabel(s) });
          b.addEventListener('click', () => actions.openCitation(s));
          src.append(el('div', { class: 'src' }, [el('span', { class: 'i', text: `[${s.index || ''}]` }), b]));
        }
        body.append(src);
      }
      const meta = el('div', { class: 'meta' });
      if (m.model) meta.append(el('span', { text: m.model }));
      if (m.context?.label) meta.append(el('span', { text: `范围：${m.context.label}` }));
      if (m.latency_ms) meta.append(el('span', { text: `${m.latency_ms}ms` }));
      if (m.cached) meta.append(el('span', { class: 'ok', text: '缓存命中' }));
      if (m.usage?.tokens_in || m.usage?.tokens_out) meta.append(el('span', { text: `${m.usage.tokens_in || 0}→${m.usage.tokens_out || 0} tokens` }));
      if (m.cost_yuan) meta.append(el('span', { text: `≈${m.cost_yuan} 元` }));
      body.append(meta);
      const acts = el('div', { class: 'actions' });
      const copy = el('button', { text: '复制' });
      copy.addEventListener('click', () => { navigator.clipboard?.writeText(m.content || ''); toast('已复制'); });
      acts.append(copy);
      const save = el('button', { text: '存为笔记' });
      save.addEventListener('click', () => actions.saveAnswerAsNote(m));
      acts.append(save);
      body.append(acts);
    }
    box.append(body);
    const cites = body.querySelectorAll('.cite');
    cites.forEach(c => c.addEventListener('click', () => {
      const idx = Number(c.dataset.cite);
      const src = (m.sources || []).find(s => Number(s.index) === idx) || (m.citations || []).find(s => Number(s.index) === idx);
      if (src) actions.openCitation(src);
    }));
    return box;
  }

  function sourceLabel(s) {
    const t = s.title || s.doc_title || (s.source_kind === 'note' ? '笔记' : '资料');
    if (s.source_kind === 'note') return `笔记《${t}》${s.heading_path ? ' › ' + s.heading_path : ''}`;
    if (s.source_kind === 'selection') return `选文《${t}》${s.heading_path ? ' › ' + s.heading_path : ''}`;
    return `《${t}》${s.heading_path ? ' › ' + s.heading_path : ''}`;
  }

  async function toggleHistory() {
    state.ai.historyOpen = !state.ai.historyOpen;
    historyBox.hidden = !state.ai.historyOpen;
    if (state.ai.historyOpen) await refreshHistory(true);
  }

  async function refreshHistory(force = false) {
    if (!state.ai || (!state.ai.historyOpen && !force)) return;
    try {
      const r = await api.get('/api/conv/list');
      clear(historyBox);
      const items = (r.items || []).filter(x => x.turns > 0).slice(0, 30);
      if (!items.length) { historyBox.append(el('div', { class: 'empty', text: '还没有历史会话' })); return; }
      for (const c of items) {
        const it = el('div', { class: `item${c.id === state.ai.conversationId ? ' active' : ''}` }, [
          el('span', { class: 't', text: c.title || '未命名会话' }),
          el('span', { class: 'meta', text: `${c.turns} 轮` }),
        ]);
        it.addEventListener('click', () => loadConversation(c.id));
        historyBox.append(it);
      }
    } catch (e) { clear(historyBox); historyBox.append(el('div', { class: 'empty', text: '历史读取失败' })); }
  }

  async function loadConversation(id) {
    try {
      const r = await api.get(`/api/conv/${id}`);
      if (r.ok === false) throw new Error(r.error || '会话不存在');
      state.ai.conversationId = id;
      state.ai.messages = (r.messages || []).map(m => ({ ...m, sources: m.citations || [] }));
      state.ai.historyOpen = false;
      historyBox.hidden = true;
      const conv = r.conversation || {};
      if (conv.context_json) {
        try {
          const ctx = JSON.parse(conv.context_json);
          if (ctx && ctx.kind) {
            ctx.label = `会话范围 · ${ctx.label || ''}`.trim();
            state.ai.context = ctx; state.ai.contextMode = 'history';
          }
        } catch {}
      }
      renderContext(); renderMessages(true); refreshHistory(true);
    } catch (e) { toast(e.message, { error: true }); }
  }

  function newConversation() {
    state.ai.conversationId = null;
    state.ai.messages = [];
    state.ai.pendingSelection = null;
    state.ai.contextMode = 'auto';
    state.ai.context = defaultContextForTab(state.activeTab);
    renderContext(); renderMessages();
    composer.querySelector('textarea')?.focus();
  }

  async function exportWord() {
    if (!state.ai.conversationId) { toast('当前还没有可导出的会话'); return; }
    try {
      const r = await api.post('/api/conv/export', {
        id: state.ai.conversationId, mode: 'qa', snippet: true, open: true,
      });
      if (r.ok === false) throw new Error(r.error || '导出失败');
      toast('已导出 Word：' + (r.path || r.name || ''));
    } catch (e) { toast(e.message, { error: true }); }
  }

  return {
    root, setActiveTab, askSelection, renderContext, renderMessages,
    loadConversation, newConversation, refreshHistory,
    setContext(ctx) {
      if (!ctx) return;
      state.ai.context = ctx;
      state.ai.contextMode = 'external';
      renderContext();
    },
    focus() {
      const ta = composer.querySelector('textarea');
      ta && ta.focus();
    },
    get conversationId() { return state.ai.conversationId; },
  };
}
