# DocLib 2.0 实施进度

> 分支：`v2.0-dev` ｜ 基线：`v1.1.2-baseline` / `157bcbe` ｜ 开始：2026-11-19
> 规则：每阶段记录“已完成 / 文件 / 测试 / 决策 / 未解决 / 下一步”；测试必须用临时 `DOCLIB_DATA`；不 push。
> 最终布局：统一 A 三栏；浅/深仅主题；右侧 AI 完整高度；局部图谱只在中央标签页。

## 阶段状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 安全基线 | ✅ 完成 | 分支/tag、venv、guard、5 个基线、规划文档 |
| Phase 1 工作区壳/设计系统 | ✅ 基本完成 | 三栏壳、主题、树/标签/AI/状态、workspace 持久化、响应式抽屉、旧入口 |
| Phase 2 迁移+图谱 | ✅ 基本完成 | 0006/0007、迁移事务/备份、graph API、Cytoscape/fcose、全局/局部/筛选/信息面板/树联动 |
| Phase 3 阅读器+AI 上下文 | ✅ 基本完成 | reader/range/markdown/PDF 分支、选区、引用跳转；context 五模式、qa_v4、消息 context |
| Phase 4 笔记/双链/增强 | ✅ 基本完成 | notes/note_fts/note_links、编辑器/预览/反链、Markdown 导入导出、AI 存笔记、关系 API |
| Phase 5 质量/视觉 | 🟡 进行中 | 13 个 Python 测试全过；真实截图矩阵/视觉审计/WebView2/打包仍待完成 |
| Phase 6 交付 | ⬜ 未开始 | 本地构建/ZIP/README/CHANGELOG/限制说明 |

## 已完成（按文件）

### 后端
- `doclib/migrations/0006_graph_context.sql`：relations、messages/conversations.context_json、citations 扩展、doc_chunks page/offset。
- `doclib/migrations/0007_notes_links.sql`：notes/note_chunks/note_fts/note_links。
- `doclib/db.py`：事务迁移、迁移前备份、失败回滚、schema_version 修正、幂等。
- `doclib/graph.py`（子代理实现，主线复核）：实体/边投影、global/partition/local、过滤、BFS、limit。
- `doclib/notebook.py`、`doclib/links.py`（子代理实现）：笔记 CRUD/分块/FTS/冲突、wikilink 解析/反链/关系 CRUD。
- `doclib/reader.py`（子代理实现）：阅读分页/TOC/around、文件解析、raw、Range。
- `doclib/workspace.py`：data/workspace.json 原子读写、校验、损坏回退、重置。
- `doclib/context.py`：partition/node/document/selection/note 上下文校验与归一化。
- `doclib/ai/rag.py`：context 检索、selection 首条来源、笔记通道、prompt v4、缓存键、消息 context、引用快照。
- `doclib/citations.py`：document/selection/note 来源、page/quote/offset 快照与 resolve。
- `doclib/ai/prompts.py` + `qa_v4.txt`：PROMPT_VERSION=4，上下文/选文/笔记规则。
- `doclib/web/api_v2.py`：workspace/bootstrap/graph/entity/reader/raw/notes/relations/backlinks。
- `doclib/web/server.py`：v2 路由、MIME 表、404、Range、XFO SAMEORIGIN、CSP、文件流、ask context 透传、错误修复。
- `doclib/web/static/mindmap.html`：`?embed=1&theme=` 嵌入模式（header 隐藏、深色变量覆盖）。

### 前端
- `index.html`：仅壳 + 本地 vendor + ESM。
- `app/core.js`：API/DOM/图标/对话框/菜单/Toast/Markdown/格式化。
- `app/workspace.js`：工作区状态模型/标签/主题/持久化。
- `app/shell.js`：Ribbon/资料库树（节点 + 资料叶 + 未归档 + 笔记）/标签/状态/拖宽/折叠。
- `app/ai.js`：完整高度 AI 面板、模型切换、会话历史、上下文范围、引用、选中文字、存笔记、导出 Word。
- `app/views.js`：graph / reader / note / node / search / settings / mindmap / welcome。
- `styles/*.css`：tokens（dark/light）、base、layout、components、views。
- `vendor/*`：Cytoscape 3.35、fcose 2.2、cose-base、layout-base、marked 15、DOMPurify 3.3（本地离线）。

### 测试与工具
- 新增 `tests/test_graph.py`、`test_notebook.py`、`test_reader.py`、`test_context.py`、`test_migrations_v2.py`、`test_workspace.py`、`test_http_v2.py`。
- `scripts/v2_guard.py`、`scripts/make_demo.py`、`scripts/fake_llm.py`。
- `docs/v2/PLAN.md`、`DESIGN_SYSTEM.md`、`ARCHITECTURE.md` 已按最终布局更新。

## 测试结果（2026-11-19，真实执行）

| 测试 | 结果 |
|---|---|
| smoke / scope_isolation / partitions / citations / mindmap_gen | 全过 |
| graph / reader / notebook / context / migrations_v2 / workspace / http_v2 | 全过 |
| test_notes | 全过 |
| **合计** | **13/13 退出码 0** |

关键手工 E2E（Playwright + Edge，1440×900）：
- 图谱渲染 28 节点；单击节点显示信息面板；局部图谱打开中央新标签；树同步高亮。
- 读取 Markdown 资料；TOC 切换；选区→问 AI；选中文字请求 context=`selection`，引用来源标记为选文。
- 文档上下文请求只检索该文档；引用点击回原文并高亮。
- 新建笔记→保存→刷新后恢复；反链显示 3 条。
- 导入资料（路径）成功；导入 Markdown 笔记成功；Word 问答导出成功。
- 浅/深主题切换时 AI 面板尺寸/三栏宽度不变（374×874 / 268）。
- 920/1100 窄窗：抽屉布局可打开（待复测截图）。

## 未解决 / 下一步
- 视觉：最终 8 张矩阵截图、`ds-design-audit` 评分与修复；窄窗抽屉复测。
- WebView2 原生窗口实跑（当前用 Edge 无头 Playwright）；PDF 内嵌实测（无 PDF 样例）。
- `打包.bat` 仍为旧脚本，Phase 6 必须重写后再打包；当前未打包。
- `qa_regress` / `audit_doclib` 仍依赖正本数据，未建 fixture；需在 Phase 5 补齐或明确历史基线。
- 分屏、命令面板、未链接提及、标签拖拽/固定为 P1，尚未实现。
- 树节点创建 UI 需再手工确认（API 已验证）。
