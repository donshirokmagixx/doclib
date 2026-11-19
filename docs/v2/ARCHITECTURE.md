# DocLib 2.0 技术架构与文件级方案（已批准）

> 状态：2026-11-19 用户批准；最终布局为 **A 三栏统一结构**，浅/深仅为主题，右侧 AI 面板完整高度，局部图谱只在中央标签页。Phase 0 起按本方案实施。
> 现状证据：`docs/v2/research/01-frontend-audit.md`、`02-backend-data-audit.md`、`03-runtime-packaging-audit.md`、`04-obsidian-interactions.md`、`05-oss-graph-libs.md`。

---

## 1. 原则与硬约束

1. **保留核心后端**：Python 标准库 HTTP Server、SQLite、FTS5、RAG、Gateway、导入、Word 导出、WebView2、PyInstaller 全部保留；不换语言、不换数据库。
2. **旧能力不回归**：旧 `/api/*`、`/api/rev/*` 路由保留；旧数据库可原地升级；旧测试继续可跑。
3. **前端不进入构建链**：v2.0 使用原生 ES Modules + 本地 vendored 库，不引入 Node/Vite 作为发布依赖；离线、可打包、可读。
4. **数据先于界面**：先定 schema、迁移事务、备份与测试，再做图谱/笔记 UI。
5. **真实证据**：每个阶段用真实命令、真实 HTTP 请求、真实截图验收；不以“应该可以”结项。
6. **数据安全边界**：`dist/DocLib/data` 可能是真实资料库；任何迁移、测试、打包先在临时目录或备份上验证；不自动推送远程。
7. **布局不变量**：全应用只有一套三栏结构；浅/深只改主题；右侧 AI 面板完整高度、独立空间；文件/笔记/全局图谱/局部图谱全部在中央标签页；禁止 B 的右侧上下分栏和任何常驻局部图谱侧栏。

---

## 2. 前端技术选型

### 2.1 方案对比

| 标准 | 方案 A：原生 ES Modules（无构建） | 方案 B：现代框架 + Vite |
|---|---|---|
| 当前代码复用 | 保留 HTML/CSS 语义与 API 契约，重写渲染/状态层 | 同样要重写，收益主要在组件化 |
| 多标签/面板状态 | 自建 ~120 行 store + view 生命周期，足够 | 框架更省心，但需引入路由/状态约定 |
| 图谱整合 | vendored Cytoscape（UMD/ESM）直接挂载 | 同样需要三方图谱库，框架无额外收益 |
| WebView2 | Chromium 157；ESM/ES2022 全支持 | 同样支持；需处理 base/hash/资源路径 |
| 离线/打包 | 零 Node、零构建、`static/` 直接进 PyInstaller | 发布链多一步 build，忘 build 会打包旧页面 |
| 长期维护 | 文件多但显式；无框架升级负担 | 组件化更好，但项目只有 1 个前端开发者/代理 |
| 启动/体积 | 无 runtime 框架；vendor 约 200KB gzip | Vue/React runtime 增加 40–140KB |
| 风险 | 需要自律的状态/生命周期规范 | 构建链、base 路径、CI Node、离线资源 |

**决定：方案 A。** 理由：当前应用是单窗口、单用户、低路由复杂度；真正的复杂度在“面板/标签生命周期、图谱、阅读器”，而这些用显式 view 模块 + store 更透明。引入框架会把最容易出错的构建链带入 PyInstaller/离线发布，收益不足。若 2.0 后前端超过约 15k 行或需要插件化，再评估 Vite + Preact/Vue。

**替代保留**：所有新 API 保持 JSON/HTTP 语义，未来若迁移框架不需要改后端。

### 2.2 前端目录（新增）

```
doclib/web/static/
  index.html                     # 仅壳：meta、vendor script、#app、加载 app/main.js
  app/
    main.js                      # 启动：bootstrap、theme、workspace、命令、快捷键
    core/
      api.js                     # fetch 封装：超时/Abort/错误归一化
      store.js                   # 极简订阅 store（get/set/patch/subscribe）
      bus.js                     # 应用事件（open-entity、context-change、citation-jump）
      dom.js                     # createElement/textContent 工具，禁止未净化 innerHTML
      format.js                  # 时间/字节/路径/标题截断
      keys.js                    # 快捷键注册与冲突提示
      theme.js                   # system/light/dark + meta color-scheme
      router.js                  # 标签/窗格导航与历史
    workspace/
      workspace.js               # 状态模型、持久化、校验、恢复
      layout.js                  # 拖动宽度、折叠、split（P1）
      tabs.js                    # 标签渲染/关闭/溢出/拖拽
      history.js                 # 前进后退（docId+anchor+scroll）
      commands.js                # 命令注册表（Ribbon/菜单/面板共用）
    components/
      ribbon.js, explorer.js, tabstrip.js, dialog.js, menu.js,
      toast.js, empty.js, icons.js, markdown.js, tooltip.js
    views/
      graph.js, reader.js, note.js, node.js, search.js,
      mindmap.js, settings.js, welcome.js
    ai/
      panel.js, chat.js, context.js, citations.js
    graph/
      cy.js                      # Cytoscape 实例/布局/事件
      style.js                   # 节点/边样式（随主题）
      filters.js                 # 筛选状态 -> API 参数
      inspector.js               # 选中信息面板
    styles/
      tokens.css                 # 颜色/字号/间距/圆角（light/dark）
      base.css                   # reset、排版、焦点、滚动条
      layout.css                 # 应用网格/面板/响应式
      components.css             # 按钮/树/标签/对话框/菜单/表单
      views.css                  # reader/graph/note/search/AI
      themes.css                 # data-theme 覆盖
  vendor/
    cytoscape.min.js             # 3.35.x，MIT
    cytoscape-fcose.js           # 2.2.x，MIT（锁定版本）
    marked.min.js                # MIT
    purify.min.js                # DOMPurify，Apache-2.0/MPL-2.0
    codemirror5/                 # CodeMirror 5.65.x，MIT（笔记编辑器）
    icons.svg                    # Lucide 子集（ISC），一次性 sprite
  mindmap.html                   # 保留；仅加 ?embed=1 + 主题/标题 postMessage
```

- 所有 vendor 文件本地提交；无 CDN、无远程字体。
- `index.html` 不含内联脚本/内联事件；vendor 用普通 `<script>`，应用用 `<script type="module">`。
- `.js` MIME 由服务端显式表保证；新增 `.mjs` 也显式映射（即使不采用）。
- 组件不使用虚拟 DOM；view 拥有容器、状态与 `mount/unmount`；切换标签隐藏而非销毁，保留滚动。
- 字符串一律 `textContent`；Markdown 渲染后用 DOMPurify；禁止 `innerHTML = userData`。

### 2.3 状态模型

```js
// 全局 UI（不进 DB）
ui = { theme, density, leftWidth, rightWidth, leftCollapsed, rightCollapsed }

// 工作区（服务端 data/workspace.json）
workspace = {
  version: 1,
  activePane: "p1",
  layout: { leftWidth: 268, rightWidth: 374, leftCollapsed: false,
            rightCollapsed: false, split: null },
  panes: [
    { id: "p1", activeTabId: "t2", tabs: [
      { id: "t1", kind: "graph", title: "关系图谱",
        params: { scope: "global", partitionId: 1, center: null,
                  filters: { types: ["node","document","note"],
                             rels: ["hierarchy","mount","manual","wikilink"],
                             q: "" } },
        pinned: false },
      { id: "t2", kind: "doc", title: "傅里叶变换.pdf",
        params: { docId: 12, chunkId: null, scrollTop: 0 }, pinned: false }
    ]}
  ],
  history: { p1: { entries: [], index: -1 } }
}
```

- 每个 tab 有稳定 `id`；实体引用用 `docId/noteId/nodeId`，绝不用路径/标题当主键。
- 视图局部状态（表单、展开、临时筛选）留在 view；可恢复状态（滚动、筛选、图谱相机）写回 tab params。
- 持久化：`GET /api/v2/workspace` 启动读取；变更 500ms debounce `POST /api/v2/workspace`；失败 toast + 保留内存状态。
- 启动校验：只做轻量结构校验；被删除实体在视图内显示“内容已删除”，不阻塞启动，不自动清理用户布局（用户可关标签）。
- 上限：12 tabs/窗格；workspace JSON ≤256KB；超过时拒绝并提示关闭旧标签。
- 主题偏好可在 workspace + localStorage 双写；以服务端为准，localStorage 只做首屏防闪。

---

## 3. 后端架构

### 3.1 路由分层

保留 `server.py` 的 HTTP/安全/静态职责；新增 v2 路由模块，不在旧 `api_dispatch` 里继续堆分支：

```
doclib/web/api_v2.py     # /api/v2/* 分发（新功能）
doclib/web/server.py     # HTTP、静态、安全头、Range、旧路由、ask context 扩展
doclib/graph.py          # 图投影（实体/边/筛选/局部 BFS）
doclib/notebook.py       # 笔记 CRUD、Markdown 分块、FTS
doclib/links.py          # wikilink 解析、解析/反链、关系 CRUD
doclib/workspace.py      # data/workspace.json 原子读写/校验
doclib/reader.py         # 阅读内容分页、PDF/原文件流、MIME/Range
doclib/context.py        # AI 上下文解析（document/selection/note）
doclib/migrations/0006_graph_context.sql
doclib/migrations/0007_notes_links.sql
```

`server.py` 只在 `api_dispatch` 最前面加：

```python
if path.startswith("/api/v2/"):
    return api_v2.dispatch(conn, method, path, query, body)
```

旧路由原样保留。新前端只使用 `/api/rev/*`（现有能力）+ `/api/v2/*`（新能力），不再做 v1/v2 三元分支。

### 3.2 静态层加固（Phase 1，前端前提）

现状问题（`03-runtime-packaging-audit.md`）：`read_bytes` 无 Range、MIME 依赖注册表、全局 `X-Frame-Options: DENY`、缺失资源回退 `index.html`、`no-store`。

改法：

- 显式 MIME 表：`.html .js .mjs .css .svg .png .jpg .webp .woff2 .json .pdf`；未知扩展返回 `application/octet-stream` + `nosniff`。
- 缺失静态资源：带扩展名 → 404（不回落 HTML）；无扩展名的应用路径 → `index.html`。
- `/api/v2/file/<doc_id>` 支持 `Range`（206/416、`Accept-Ranges`、`Content-Range`），仅允许数据库中的未删除文档；`Content-Disposition: inline`，MIME 白名单。
- `X-Frame-Options: SAMEORIGIN`（或仅对 HTML/file），`Content-Security-Policy: frame-ancestors 'self'`；保证 `mindmap.html`/PDF 同源 iframe 可嵌入。
- 缓存：`/vendor/*` 长缓存 + 内容 hash 查询/文件名；HTML `no-cache`；API `no-store`。
- CSP：`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'`。Phase 1 先允许 style inline（动态样式），Phase 5 收紧到必要范围。
- 错误：500 返回通用消息 + `trace_id`，详情写日志；不把 `str(e)` 直接给前端（保留旧路由兼容时可标记）。

### 3.3 现有接口复用与扩展

| 能力 | 现有 | v2 处理 |
|---|---|---|
| 分区/树/资料/搜索 | `/api/rev/*` | 保留；前端唯一入口 |
| 问答 | `/api/rev/ask` | 扩展 `context` 字段；旧参数不变 |
| 会话 | `/api/conv/*` | 保留；详情补 `context`、引用 source |
| 导入 | `/api/rev/import` | 保留；修分区导入“收回即清空” |
| 导图 | `/api/map/*` | 保留；mindmap iframe 嵌入 |
| 模型/密钥/备份/回收站 | 现有 | 保留；设置页复用 |
| 图谱 | 无 | 新增 `/api/v2/graph` |
| 笔记 | 无（`notes.py` 是 Word 导出） | 新增 `/api/v2/notes/*` |
| 阅读 | 只有打开原文件 | 新增 `/api/v2/reader/*`、`/api/v2/file/*` |
| 工作区 | localStorage 4 个键 | 新增 `/api/v2/workspace` |
| 关系/反链 | 无 | 新增 `/api/v2/relations/*`、`/api/v2/backlinks` |

---

## 4. 数据模型与迁移

### 4.1 设计原则

- 真值（nodes/documents/notes）与派生（chunks/FTS/graph projection）分离。
- 所有用户数据软删除；唯一索引带 `WHERE deleted_at IS NULL`。
- 多态关系不能靠标题/路径；`kind + id` 是身份。
- 同名实体不自动合并；AI 推测与人工关系分 `origin`，默认不混显。
- 引用继续“快照 + hash”，不依赖 chunk_id 存活。

### 4.2 迁移 0006：关系 + AI 上下文 + 引用快照

```sql
-- 消息/会话上下文：每条消息可复现当时的范围
ALTER TABLE messages ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE conversations ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}';

-- 引用来源：document / note / selection；保留旧字段
ALTER TABLE message_citations ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'document';
ALTER TABLE message_citations ADD COLUMN note_id INTEGER;
ALTER TABLE message_citations ADD COLUMN doc_title TEXT NOT NULL DEFAULT '';
ALTER TABLE message_citations ADD COLUMN page INTEGER;
ALTER TABLE message_citations ADD COLUMN start_off INTEGER;
ALTER TABLE message_citations ADD COLUMN end_off INTEGER;
ALTER TABLE message_citations ADD COLUMN quote TEXT NOT NULL DEFAULT '';

-- 阅读定位（PDF 页/字符范围；docx/pptx 可为空）
ALTER TABLE doc_chunks ADD COLUMN page INTEGER;
ALTER TABLE doc_chunks ADD COLUMN start_off INTEGER;
ALTER TABLE doc_chunks ADD COLUMN end_off INTEGER;

-- 人工/AI 关系（树与挂载不复制，图谱时联查）
CREATE TABLE IF NOT EXISTS relations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    src_kind     TEXT NOT NULL CHECK (src_kind IN ('node','document','note')),
    src_id       INTEGER NOT NULL,
    dst_kind     TEXT NOT NULL CHECK (dst_kind IN ('node','document','note')),
    dst_id       INTEGER NOT NULL,
    rel          TEXT NOT NULL DEFAULT 'related',   -- related|prerequisite|contrast|example
    label        TEXT NOT NULL DEFAULT '',
    origin       TEXT NOT NULL DEFAULT 'manual'
                 CHECK (origin IN ('manual','ai','import')),
    confidence   REAL NOT NULL DEFAULT 1.0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    deleted_at   INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rel
    ON relations(src_kind,src_id,dst_kind,dst_id,rel,origin)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rel_src
    ON relations(src_kind,src_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rel_dst
    ON relations(dst_kind,dst_id) WHERE deleted_at IS NULL;
```

- `rel` 是受控枚举；`label` 给用户自定义短语（≤40 字）。
- `origin='ai'` 默认不在图谱显示；确认后才转 `manual` 或保留但打开“AI 推测”开关。
- 不把树层级/挂载复制进 `relations`，避免双写不一致；图谱 API 联查。

### 4.3 迁移 0007：笔记与双链

```sql
CREATE TABLE IF NOT EXISTS notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    body_md      TEXT NOT NULL DEFAULT '',
    node_id      INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    partition_id INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    deleted_at   INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_note_title
    ON notes(title COLLATE NOCASE) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_note_node
    ON notes(node_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_note_part
    ON notes(partition_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS note_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    ord          INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    text         TEXT NOT NULL,
    char_len     INTEGER NOT NULL,
    UNIQUE(note_id, ord)
);
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
    heading_path, text,
    content='note_chunks', content_rowid='id',
    tokenize='trigram'
);
-- 三个触发器与 chunk_fts 同构

CREATE TABLE IF NOT EXISTS note_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_kind  TEXT,                  -- node|document|note，未解析为 NULL
    target_id    INTEGER,
    target_title TEXT NOT NULL DEFAULT '',
    heading      TEXT NOT NULL DEFAULT '',
    alias        TEXT NOT NULL DEFAULT '',
    start_off    INTEGER NOT NULL DEFAULT 0,
    end_off      INTEGER NOT NULL DEFAULT 0,
    resolved     INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nl_note ON note_links(note_id);
CREATE INDEX IF NOT EXISTS idx_nl_target ON note_links(target_kind,target_id);
```

- 笔记标题全局唯一（不区分大小写）；`[[标题]]` 因此无歧义。文档标题可重复，文档链接使用 `[[doc:12|标题]]` 稳定形式。
- 笔记正文存 DB；备份随 `data/doclib.db`；导出 Markdown/Word 是显式动作。
- 笔记分区必填（默认当前分区），保证检索范围隔离；`node_id` 可选。
- 不把 PDF/Word 变成可编辑 Markdown；笔记是独立实体。

### 4.4 迁移器安全改造（Phase 2 前置）

当前 `db.migrate()`（`db.py:61-84`）问题：`executescript` 无事务、`schema_version` 永远 `"0001"`、无备份。

改法：

1. 发现待执行版本后，若 `DB_PATH` 存在且有数据，用 `sqlite3.Connection.backup()` 生成 `data/backups/pre-migrate-<ver>-<ts>.db`；保留最近 2 份。
2. 每个迁移作为 `BEGIN IMMEDIATE ... COMMIT` 执行（把 BEGIN/COMMIT 与版本插入放进同一 `executescript`）；异常 `ROLLBACK`，不写版本，抛错阻止启动（或进入只读模式并提示恢复）。
3. `schema_version` 写实际最大版本（如 `"0007"`），并保留 `schema_migrations` 为准。
4. 迁移脚本必须幂等（IF NOT EXISTS / 可重复 ALTER 检查）；新增测试模拟“第二个语句失败”，确认无半迁移与无版本记录。
5. 启动时若迁移失败，不自动删除/重建数据库；备份路径写日志。

### 4.5 数据完整性规则

- 硬删除（purge）时清理 `relations`、`note_links`、`message_citations` 中悬空引用；软删除只过滤。
- 删除文档：保留 citations 快照；relations 软删；图谱不出现；反链显示“已删除”。
- 删除节点子树：文档回到“未分类”（现有逻辑）；修复 `purge_node` 的孤儿问题（`tree.py:478-504`），把只挂被删节点且无其他挂载的文档收回“未分类”。
- 删除笔记：软删；`note_links` 保留但解析为未解析；恢复后重新解析。
- 同名：笔记标题唯一；文档/节点同名允许；链接/关系一律按 id；标题解析歧义时返回候选，不自动选。
- 改标题：笔记标题变更只影响显示；稳定 ID 链接不断；`[[旧标题]]` 在 P1 自动更新，失败则标未解析。
- 分区：笔记/关系必须落在同一分区；跨分区关系默认拒绝（409/400），避免图谱串科。

---

## 5. 图谱

### 5.1 投影

实体：

- `node`：知识节点/学科（nodes）
- `document`：资料（documents）
- `note`：笔记（notes）

边：

| rel | 来源 | 方向 | 说明 |
|---|---|---|---|
| `hierarchy` | nodes.parent_id | 父→子 | 知识结构 |
| `mount` | node_documents | 节点→资料 | 归属 |
| `manual` | relations(origin=manual) | 双向展示 | 人工关联 |
| `ai` | relations(origin=ai) | 双向展示 | 默认隐藏 |
| `wikilink` | note_links(resolved) | 笔记→目标 | 双链 |

- ID：`node:12`、`document:34`、`note:56`；边 `e:<kind>:<id>` 或 `src|rel|dst`。
- 度：最终选择的子图内计算；节点大小前端 `4 + 6*sqrt(deg/maxDeg)`，资料/笔记另设上下限。
- 颜色：知识节点按分区；资料灰/空心；笔记朱色方块；AI 边虚线低透明。

### 5.2 API

```http
GET /api/v2/graph?scope=global|partition|local
    &partition=1
    &center=node:7&depth=1|2
    &types=node,document,note
    &rels=hierarchy,mount,manual,wikilink,ai
    &q=傅里叶
    &limit=1500
```

返回：

```json
{
  "ok": true,
  "scope": "global",
  "center": null,
  "truncated": false,
  "stats": {"nodes": 128, "edges": 214, "total_nodes": 128},
  "nodes": [
    {"id":"node:7","kind":"node","entity_id":7,"label":"傅里叶变换",
     "partition_id":1,"degree":12,"meta":{"path":"/1/7/","doc_count":8}}
  ],
  "edges": [
    {"id":"e:...","source":"node:7","target":"document:34",
     "rel":"mount","origin":"system","weight":1.0,"directed":true}
  ]
}
```

- `scope=global`：当前分区或全库（有 partition 时只该分区）；按度截断到 limit，`truncated` 明示。
- `scope=local`：从 center 起 BFS，depth 1/2；包含层级父/子、挂载、手动、wikilink；≤800 节点。
- `q`：服务端按标签子串过滤（不改变度数前先过滤）。
- AI 边默认不返回，除非 `rels` 显式包含 `ai`。
- 局部图包含 center 的祖先一层，避免“节点 l 孤立”。

### 5.3 渲染（Cytoscape.js 3.35 + fcose 2.2）

- 库：Cytoscape 3.35.x（MIT）+ fcose 2.2（MIT），本地 vendor，锁定版本；Canvas 渲染；WebGL 预览暂不启用。
- 样式：
  - 知识节点：`background-color` 分区色，`width/height` 按度；选中 2px 外环。
  - 资料：空心圆（`background-opacity:0`、`border-width:1`），按文件类型微调边框色。
  - 笔记：小方块（`shape:round-rectangle`，朱色）。
  - 边：`hierarchy` dashed、`mount` 细实线、`manual` 实线、`wikilink` dotted、`ai` dashed 低透明；`curve-style: bezier` 或 haystack（性能优先）。
  - 标签：`font-family` UI，10–11px，`text-background` 纸色/墨色，按 zoom 阈值显隐。
- 交互：
  - `cy.on('tap','node')` 选中 + inspector；`dbltap` 打开实体；`mouseover` 邻居高亮；`drag` 固定 `locked`；右键菜单。
  - 缩放/平移用 Cytoscape 内置；`fit`/`reset` 按钮；滚轮阈值。
  - 布局：fcose 参数（quality=default, randomize=false, nodeRepulsion/idealEdgeLength 按规模），初始用缓存位置；重新布局按钮。
  - 位置持久化：`localStorage['doclib.graph.positions.v1']` 存被拖动节点 `{id:{x,y}}`；不存自动布局结果；重置时清空。
  - 相机/筛选存 workspace tab params。
  - 搜索：匹配节点高亮 + 相机居中；无匹配提示“仅筛选当前图，试试全局搜索”。
  - 大图：`hideEdgesOnViewport`、`textureOnViewport`（按实测）、批量 style；limit 1500。
- 性能门槛（Phase 2 原型）：1k 节点/3k 边首次可交互 ≤1.5s；5k 若 <15 FPS，退“全局限量 + 局部图”；详见 `05-oss-graph-libs.md`。
- 与手工导图：完全独立；图谱节点“在导图中打开”只传 `node_id`/`entity_id`，不共享渲染器。

### 5.4 图谱与树/搜索/阅读联动

- 树选中节点 → 图谱“聚焦此节点”（local，depth 1）；树右键“在图谱中显示”。
- 图谱双击知识节点 → 打开“节点概览”标签（资料 + 笔记 + 反链 + 局部图），不直接打开某一份资料；双击资料/笔记 → 对应阅读/编辑器。
- 图谱双击资料 → 树定位其主挂载节点，展开路径并高亮。
- 搜索命中节点 → 图谱搜索定位。
- AI 回答提到实体 → 侧栏“在图谱中显示”（P1）。

---

## 6. 文档阅读器

### 6.1 格式策略

| 格式 | 阅读方式 | 说明 |
|---|---|---|
| Markdown/TXT | 服务端返回原文，前端 marked + DOMPurify 渲染 | 保格式；引用跳转用文本匹配 + Highlight API |
| PDF | `iframe` 指向 `/api/v2/file/<id>#page=N`（WebView2 内置 PDF） | Phase 3 先做 spike；不可用则降级解析文本；P1 可换 PDF.js（MIT） |
| DOCX/DOC | 解析块（标题路径 + 正文）阅读 | 不承诺原版排版；提供“打开原文件”；公式/图片可能丢失，明确提示 |
| PPTX/PPT | 按“第 N 张幻灯片：标题”+ 正文块 | 提供“打开原文件” |
| 图片 | `<img>` + OCR 文本 | 图片本身可缩放；OCR 文本可搜索/引用 |

- 现有解析已产出 `doc_chunks`；阅读器用同一数据保证引用可定位。
- PDF 页号：在 `readers.py` 抽取时把页号写入块/chunk（新增 `page` 列）；DOCX/PPTX 为 NULL。引用快照带 page（有则显示“第 N 页”）。
- 段落偏移：Phase 3 先不做字符级 bbox；用 `chunk_id + heading_path + quote` 定位；P1 增加 `start_off/end_off`。

### 6.2 API

```http
GET /api/v2/reader/<doc_id>?around=<chunk_id>&limit=200
-> { ok, doc:{id,title,file_type,file_size,parse_status,partition_id,nodes,file_path},
     toc:[{level,title,chunk_id,ord}],
     chunks:[{id,ord,heading_path,text,page,start_off,end_off,is_table}],
     total, has_more }

GET /api/v2/file/<doc_id>          # Range、inline、MIME 白名单
GET /api/v2/raw/<doc_id>           # 仅 md/txt；{text, encoding, mtime}
```

- 阅读内容分页：默认前 200 块；滚动/“加载更多”取下一段；`around` 优先返回引用附近。
- 文件流只按 `doc_id` 解析真实路径；不接收任意路径。`Content-Type` 白名单；`Content-Disposition: inline; filename*=UTF-8''...`。
- `Range` 支持 `bytes=start-end`；416 正确；HEAD 可选。
- 无文本层/解析失败：返回 200 + `parse_status` + 明确提示，不 500。

### 6.3 阅读交互

- 文档头、TOC、正文、chunk 锚点、引用高亮、选区工具条、打开原文件、问 AI。
- 选区：`window.getSelection()`；取最近 `[data-chunk]`；限制 4000 字；工具条“问 AI / 复制 / 高亮 / 建立关联”。
- 引用跳转：`openEntity('document', id, {chunkId, quote})`；若标签已开则聚焦；滚动到 chunk；`CSS.highlights` 高亮 quote 2 秒；降级用 `<mark>` 包裹（仅文本节点）。
- 搜索：浏览器 Ctrl+F 可用；P1 加应用内“查找”条，高亮所有命中，Enter 下一个。
- 只读：不对导入资料做编辑；笔记是独立入口。

---

## 7. AI 上下文与引用

### 7.1 请求契约（扩展，不破坏旧调用）

```json
POST /api/rev/ask
{
  "question": "解释这里的 DFT 与 FFT 有什么关系？",
  "conversation_id": 12,
  "context": {
    "kind": "document|node|partition|selection|note",
    "partition_id": 1,
    "node_id": 7,
    "doc_id": 34,
    "note_id": 5,
    "chunk_id": 88,
    "quote": "……",
    "heading_path": "第 3 章 > 3.2 DFT"
  }
}
```

- 旧字段 `node/scope/partition/conversation_id` 继续有效；`context` 优先。
- 兼容规则：没有 `context` 时行为与 v1.1.2 完全一致；有 `context` 时按 kind 解析。
- 冲突：context 的 partition 与 conversation 分区不同 → 400 “上下文与分区不一致”，不静默跨区。
- `scope` 仍限制在 context 内：document 只检索该文档；selection 只检索该文档并把选文作为首条来源。

### 7.2 解析与检索

- `partition`：该分区全部资料（+笔记，若启用）。
- `node`：节点子树资料（现有 `tree.node_doc_ids`）。
- `document`：`doc_chunks WHERE doc_id=?`；检索在文档内；没有命中时返回“资料不足”，不扩大到全库。
- `selection`：文档块 + 选文;选文作为 `chunks[0]`，标记 `source_kind=selection`；模型必须引用 [1] 才能算使用选文；检索其余块作为补充。
- `note`：笔记块（`note_chunks`）；P1 可扩展到它链接的资料。
- 笔记默认纳入：新 UI 在 partition/node 上下文发送 `include_notes=true`；旧 `/api/ask` 默认 false，避免回归。响应中注明来源类型。
- 混合检索：沿用 `search.search`/`rag._chunk_candidates` 的 FTS + 向量 + RRF；笔记通道以相同 RRF 公式融合（权重可调）。
- Prompt：新增 `doclib/ai/prompts/qa_v4.txt`（`PROMPT_VERSION=4`），在原有硬规则上加：
  - 上下文块说明“这是用户当前资料/选文/笔记”；
  - 只能引用提供的片段编号；
  - 选文不足时明确说“仅凭这段选文无法判断”，可建议扩大范围；
  - 不得把笔记/推测当作原文事实。
- 缓存键包含 prompt 版本 + context 摘要 + chunk hashes；不同上下文不串缓存。

### 7.3 会话与持久化

- `conversations.context_json` 存最近一次上下文；`messages.context_json` 存每轮实际上下文（用户消息与助手消息都存）。
- 切换上下文：更新 conversation + `op_log('context_update')`；历史消息保留原 context，不追改。
- 会话详情 API 返回每条消息 `context`/`sources`，前端可在消息下显示“基于：文档 X”。
- 引用：`message_citations` 新增 `source_kind/note_id/doc_title/page/start_off/end_off/quote`；保存“真正被引用”的编号；无 `[n]` → `insufficient=true`，不伪造来源。
- `citations.resolve` 扩展：document 按 doc_id + text_hash；note 按 note_id + heading_path + hash；删除后返回 `found=false`，UI 显示“来源已删除”。
- 统一 `/api/conv/<id>` 与 `/api/conv/detail/<id>` 的回读逻辑（当前一个硬编码 `drifted:false`），Phase 3 修复。

---

## 8. 笔记与双链

### 8.1 存储与索引

- `notes` + `note_chunks` + `note_fts`（见 0007）。
- 保存流程：校验标题/分区 → upsert note → 解析 Markdown 标题分块 → 重建 note_chunks/FTS → 解析 wikilinks → 更新 note_links（事务）。
- 自动保存 800ms；显式保存 `Ctrl+S`；`expected_updated_at` 乐观锁；冲突返回 409 + 两份内容，UI 对比。
- 删除软删；恢复重新索引/解析链接。

### 8.2 Wikilink 语法

| 写法 | 解析 |
|---|---|
| `[[note:12|标题]]` | 稳定 ID，直接解析 |
| `[[doc:34|标题]]` | 稳定 ID |
| `[[node:7|标题]]` | 稳定 ID |
| `[[标题]]` | 笔记标题唯一 → 笔记；否则文档标题唯一 → 文档；否则未解析 |
| `[[标题#章节]]` | 目标 + heading；笔记/文档均可 |
| `[[标题|别名]]` | 显示别名，解析目标 |
| `![[...]]` | P1 嵌入；v2.0 只记录为链接并显示提示 |

- 代码块/行内代码中的 `[[...]]` 不解析。
- 未解析链接不自动建空笔记；反链面板显示“未解析”，提供“创建笔记/选择目标”。
- 标题重命名：稳定 ID 链接不受影响；标题式链接 P1 自动更新（仅唯一旧标题），否则保留并提示。
- 解析器：`doclib/links.py`，纯函数 + 单元测试；输出 offsets 供编辑器高亮。

### 8.3 反向链接与关系

- `GET /api/v2/backlinks?kind=document&id=34` 返回：
  - incoming：notes 的 note_links、relations manual/ai；
  - outgoing：relations + 该文档挂载节点（可选）；
  - 每条带标题、类型、分区、片段、是否已删除。
- 人工关系：`POST /api/v2/relations/save`（创建/更新）、`/delete`；UI 选择目标（搜索实体）+ 关系类型 + 备注。
- AI 推测：P2；只有显式“发现关联”才生成 `origin='ai'`，默认隐藏；不自动写入手工关系。

### 8.4 编辑器

- CodeMirror 5.65（MIT）Markdown 模式；行号可选；搜索/替换；Tab 缩进；`[[` 触发实体补全（P1 可用简单弹层）。
- 预览：marked + DOMPurify；与正文共享 token；不加载远程图片（本地 data 图片走 `/api/v2/file`）。
- 顶部：标题、分区/节点选择、保存状态、字数；右侧/底部：反链、出链、元信息。
- AI 整理为笔记：回答下方按钮 → 后端生成 markdown（含引用链接）→ 保存 → 打开编辑器；可编辑后再保存。

---

## 9. 工作区持久化

- 文件：`data/workspace.json`；原子写（临时文件 + `os.replace`），保留 `workspace.bak.json`（上一版）。
- API：`GET /api/v2/workspace`、`POST /api/v2/workspace`（保存）、`POST /api/v2/workspace/reset`。
- 校验：版本、类型、长度（≤256KB）、tab 数（≤24）、实体 id 为正整数；未知字段丢弃；不执行任意路径/HTML。
- 损坏：改名 `workspace.corrupt-<ts>.json`，返回默认布局 + 提示；不静默删除。
- 旧 localStorage 偏好迁移：读取一次 `doclib_detail_w` 等，映射到新布局后不再依赖。
- 备份包含 `workspace.json`（`system.backup` 已复制 data 目录）。

---

## 10. 安全与数据保护

| 风险 | 对策 |
|---|---|
| XSS（笔记/Markdown/AI 回答/导图 JSON） | 全文本节点渲染；Markdown DOMPurify；禁止未净化 innerHTML；CSP；测试 payload |
| CSRF/跨站 | 保留 Host/Origin/Sec-Fetch-Site；POST 强制 JSON；新增路由同样校验；不引入 cookie 鉴权 |
| 路径穿越/任意文件 | `/api/v2/file` 只接受 doc_id；路径来自 DB 且未删除；MIME 白名单；Range 解析校验 |
| 密钥泄露 | 密钥仍走 secrets/DPAPI；日志/错误/诊断不回显；请求体不含密钥 |
| 迁移失败 | 先备份；事务；失败不删库；测试注入失败 |
| 真实数据被测试污染 | 所有测试 `DOCLIB_DATA=tmp`；Phase 0 写 guard；禁止对 `dist/DocLib/data` 跑破坏性测试 |
| 打包清空 data | 重写打包脚本为先备份/校验、构建到临时目录、成功后合并；`_pkgdata_tmp` 加 .gitignore |
| 远程推送 | 不执行 `git push`；本地分支/tag 由用户决定 |
| 第三方许可 | Cytoscape/fcose/marked/DOMPurify/CodeMirror/Lucide 许可写入 `THIRD_PARTY_NOTICES.md`；不复制 AGPL 代码 |
| AI 编造 | 只保存被引用编号；无引用=资料不足；prompt 硬规则；引用可核对 |

---

## 11. 文件级改动清单

### 11.1 新增（后端）

| 文件 | 职责 |
|---|---|
| `doclib/web/api_v2.py` | `/api/v2/*` 分发、参数校验、统一错误 |
| `doclib/graph.py` | 实体/边投影、全局/局部、筛选、截断 |
| `doclib/notebook.py` | 笔记 CRUD、分块、FTS、保存冲突 |
| `doclib/links.py` | wikilink 解析、反链、关系 CRUD/校验 |
| `doclib/workspace.py` | workspace.json 原子读写/校验/默认布局 |
| `doclib/reader.py` | 阅读分页、文件 Range/MIME、PDF/图片 |
| `doclib/context.py` | context 解析、RAG 范围、会话回写 |
| `doclib/migrations/0006_graph_context.sql` | 见 4.2 |
| `doclib/migrations/0007_notes_links.sql` | 见 4.3 |
| `doclib/ai/prompts/qa_v4.txt` | 上下文/选文/笔记规则 |

### 11.2 新增（前端）

见 2.2；核心为 `app/main.js`、`core/*`、`workspace/*`、`views/{graph,reader,note}.js`、`graph/*`、`ai/*`、`styles/*`、`vendor/*`。

### 11.3 修改

| 文件 | 改动 | 风险 |
|---|---|---|
| `doclib/web/server.py` | v2 路由入口、静态 MIME/404/Range/XFO/CSP/缓存、ask context 透传、错误脱敏 | 高：所有请求经过 |
| `doclib/db.py` | 迁移事务/备份/schema_version | 高：启动即执行 |
| `doclib/ai/rag.py` | context 范围、选文/笔记检索、prompt v4、缓存键 | 高：问答正确性 |
| `doclib/citations.py` | source_kind/note/page/quote 快照与 resolve | 中 |
| `doclib/tree.py` | purge 孤儿修复、图谱所需元数据（只读函数） | 中 |
| `doclib/importer.py` | PDF 页号/offsets（可选）、分区导入不回退清空、mtime 统一 | 中 |
| `doclib/search.py` | 笔记检索通道（P1）、过滤参数 | 中 |
| `doclib/mindmap.py` | 不改存储；`mindmap.html` embed 模式 | 低 |
| `doclib/web/static/index.html` | 替换为壳；旧页面逻辑迁移到 app/ | 高 |
| `doclib/web/static/mindmap.html` | embed/theme/postMessage/样式隔离（不动画板逻辑） | 中 |
| `DocLib.spec` | static 已整体包含；确认 vendor/字体/新提示词；无 Node | 低 |
| `打包.bat` | 数据安全重写（备份/校验/临时 dist/失败中止） | 高 |
| `start.bat` / `诊断.bat` | 数据目录/说明修正 | 低 |
| `.gitignore` | `_pkgdata_tmp`、`.venv`、测试 artfacts | 低 |
| `README.md` / `CHANGELOG.md` | v2.0 能力、限制、许可一致（LICENSE 是 MIT，README 第九节需改） | 低 |
| `scripts/audit_doclib.py` | 新增 v2 路由检查、临时库、报告路径 | 中 |

### 11.4 测试新增

| 文件 | 覆盖 |
|---|---|
| `tests/test_migrations_v2.py` | 0006/0007、备份、事务失败回滚、幂等、schema_version |
| `tests/test_graph.py` | 全集/分区/局部/筛选/截断/软删/同名/无重复边 |
| `tests/test_notebook.py` | CRUD、唯一标题、冲突、wikilink、反链、FTS、恢复/清除 |
| `tests/test_context.py` | document/selection/node/partition/note、引用、资料不足、会话隔离 |
| `tests/test_workspace.py` | 保存/读取/损坏/大小/原子写/旧偏好迁移 |
| `tests/test_reader.py` | 分页、around、Range、MIME、缺失文件、路径安全 |
| `tests/test_http_v2.py` | 真 HTTP：Host/Origin、CSP、404、Range、XFO、32MB |
| `tests/test_graph_perf.py` | 1k/3k/5k 合成数据 API/JSON 时间；阈值 |
| `tests/fixtures/` | 合成资料/笔记/关系，qa_regress/audit 可复现 |
| `tests/e2e/` | Playwright（dev 依赖）+ Edge channel，5 条流程 + 截图 |

---

## 12. 阶段依赖与顺序

```
Phase 0 安全基线
  └─ Phase 1 静态层 + 工作区壳 + 设计系统
       ├─ Phase 2 0006 + 图谱（数据/API/Cytoscape）
       │    └─ Phase 4 笔记/双链/关系/分屏（依赖 0006 + 壳 + 图谱）
       └─ Phase 3 阅读器 + AI 上下文（依赖 壳 + 0006 的 context 列）
            └─ Phase 5 质量/视觉/打包验证
                 └─ Phase 6 交付
```

- Phase 1 先用临时占位阅读视图验证标签/布局；Phase 3 替换为真实阅读器。
- Phase 2 的 0006 必须在 Phase 3 之前（context/citation 列）。
- Phase 4 的 0007 必须在 0006 之后；图谱自动出现笔记节点。
- Phase 5 才做全量回归/视觉精修/打包；打包脚本改动可提前在 Phase 0 加 guard，但正式打包在 Phase 6。

---

## 13. 已批准的决定（2026-11-19）

1. **视觉/布局**：统一 A 三栏；浅/深仅为主题；默认深色、完整浅色；右侧 AI 完整高度、默认 374px；局部图谱只在中央标签页；**禁止 B 的右侧上下分栏**。
2. **笔记**：SQLite `notes/note_chunks/note_fts/note_links`，支持 Markdown 导入导出。
3. **PDF**：WebView2 原生内嵌 + 解析文本备用；失败再评估 PDF.js（P1）。
4. **分屏**：P0 多标签 + 可调三栏 + 布局恢复；左右分屏 P1，仅作用于中央工作区。
5. **发布**：本地构建 + 干净 Windows ZIP；不推送远程。
6. **数据位置**：Phase 0 只读定位真实库；若在其他路径，只备份不写入。

> 实施中如遇与上述冲突的需求，先停下更新文档并报告，不擅自回到 B 布局。
