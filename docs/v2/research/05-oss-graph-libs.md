# 开源图谱方案调研：Perlite / Nodum / Logseq / 思源 与前端图谱库

> 2026-11-19；只读调研，未运行程序、未安装依赖。DocLib 基线 `157bcbe`，MIT。本地现状引自 `01-frontend-audit.md`、`02-backend-data-audit.md` 与 `mindmap.html`（83,846 B，1,902 行，gzip≈23.8 KB）。

## 1. 四个项目值得借鉴什么

### Perlite（MIT）
- 文件/链接：vault 目录即真值，Markdown + `[[wikilink]]`；图谱不自解析，读 Obsidian Metadata Extractor 的 `metadata.json`，按 md5 缓存，无数据库。
- 图谱：vis-network；全局 + 当前笔记局部图；可调 orphans/tags/节点大小/连线距离。大 vault 需关 orphans 提速，首次缓存可能 PHP 超时。
- 工作区：Web 根目录即 vault，文件优先、自托管，非单机桌面。插件：无 API，靠 Obsidian 元数据。
- 许可/复用：MIT，但 PHP+vis-network 栈不符；只能借鉴“元数据 JSON→图投影+缓存”架构，不复制代码。

### Nodum（MIT，v3.2.0）
- 文件/链接：Markdown 为真值；wikilink/别名/未解析链接用 ghost 节点承接，点击即建笔记；反链含 unlinked mentions。
- 图谱：`@cosmos.gl/graph`（WebGL2）力导，度数定大小、可拖、搜索/标签过滤、全局/局部，防护 context lost。
- 工作区：多租户 vault，自托管；Postgres+pgvector+Redis+MinIO，不是单文件夹本地优先，但可整库导入导出。
- 插件：sandbox iframe（allow-scripts、无 same-origin）、MCP、REST、剪藏。复用：栈差异大，代码不能搬；借鉴 ghost 节点、过滤、插件沙箱、可导出。

### Logseq（AGPL-3.0）
- 文件/链接：graph 目录 Markdown/Org 为真值；page/block 双粒度、block ref/双链；DataScript 内存索引；DB 版 SQLite（beta）。
- 图谱：V2 用 Pixi+graphology，d3-force 类布局、索引命中、缩放/拖拽；`pixi-graph` 仍 pre-release。
- 工作区：本地 graph 文件夹，可由 git/网盘同步；插件 SDK+市场；AGPL-3.0。
- 复用：无代码可复用（AGPL 与 MIT 不兼容）；借鉴 block 引用、文件优先+派生索引、插件模型。旧 issue 的 3.5k 节点卡顿说明大图需优化。

### 思源（AGPL-3.0）
- 文件/链接：workspace/data 下 notebook 存 `.sy` JSON+assets/plugins；SQLite 索引；block 引用/反链；Go kernel。
- 图谱：服务端 `graph.go` 从 SQL 块/引用构图，前后向各 16 层、`MaxBlocks` 截断、`MinRefs` 剪枝、按类型/日记/标签过滤；前端 `GraphEngine` 自研 WebGL+Canvas 兜底、Worker 分片（12ms/片）、独立 label canvas。
- 工作区/插件：本地 workspace、多 notebook，官方云同步付费；社区市场+petal API；AGPL-3.0。
- 复用：无代码（AGPL）；架构最接近 DocLib：服务端投影+Worker 布局+WebGL/Canvas 双路径+节点上限。

## 2. 图谱库硬对比

| 维度 | Cytoscape.js + fcose | Sigma.js + graphology | d3-force 自绘 | 现有 DocLib SVG |
|---|---|---|---|---|
| 当前版本 | 3.35.0 / fcose 2.2.0 | 4.0.6 / 0.26.0 | 3.0.1 | 无库，`mindmap.html` |
| min+gzip | 442.9KB / 138.9KB；fcose 121.6KB min（gzip 待实测） | 96.9KB + 12.8KB ≈110KB | 5.8KB（另加自绘代码） | 83.8KB / 23.8KB |
| 许可证 | MIT / MIT | MIT / MIT | ISC | MIT（DocLib） |
| 渲染方式 | Canvas 默认；3.31+ WebGL 预览 | WebGL2 only（v4 起） | SVG/Canvas 自选 | SVG DOM |
| 1k/5k 证据 | 1.2k 节点/16k 边 20→100 FPS；3.2k/68k 边 3→10 FPS（官方，M1/Chrome）；5k 无数据 | 官方称数万节点/边；无 1k/5k 具体 FPS | 无官方数据；5k 必须 Worker | 无实测；全量重建，推断 1k 抖、5k 不可行 |
| 布局 | 内置多种 + fcose（光谱+力导、约束、≈2×CoSE） | 无内置；FA2 / forceatlas2 worker | Barnes-Hut 力导 | 手工树布局 |
| 六项 API | 齐全：选择器、`neighborhood()`、BFS/DFS、filter、标签、局部子图 | 渲染/相机强；邻居、局部图、拖拽需 graphology+reducer/captor 组合 | 仅布局，其余全自写 | 缩放/拖拽/折叠有；邻居、筛选、局部图无 |
| WebView2/离线 | Canvas 稳、WebGL 可选；单文件好打包 | WebGL2 依赖、无 Canvas 兜底；多包 | 稳；自绘成本高 | 稳；零依赖 |

- 体积取 npm/bundlephobia（2026-11-19）。fcose 的 gzip 值异常（718 B），不可信，以实际打包为准。
- Cytoscape 的 WebGL 是 3.31 起的**预览模式**，边样式受限（虚线/overlay、非三角箭头不支持）；官方数字是 M1/Chrome 初测。
- Sigma v4 标签迁到 WebGL（SDF）、合并单层、**放弃 WebGL1**；大图上限提升，也让 WebView2 的 GPU/驱动成为硬依赖。其性能文档强调边数/透明度/抗锯齿的影响可远超节点数。
- 维护：Cytoscape 月更、Sigma v4 活跃、d3 稳定；fcose 久未更新需锁版本；graphology 0.26.0（2025-01）。四者均可本地 vendoring；DocLib 的 `static` 已进 PyInstaller `datas`，新增 vendor 不用改 spec。

## 3. 结论

**首选：Cytoscape.js 3.35 + fcose 2.2（均 MIT）**。它最快做出完整图谱产品：选择器、邻域/局部图、事件、筛选、标签、PNG 导出、布局/固定节点约束都在一套 API 里；MIT 可闭源；Canvas 默认对 WebView2 最稳，WebGL 可按 1.5k+ 图开启；fcose 的 `fixedNodeConstraint` 能钉住拖好的位置。代价是 139KB gzip+fcose 且维护慢；5k 必须过性能门槛。

**备选：Sigma.js 4 + graphology（+ forceatlas2 worker）**。若 5k/1 万边是硬指标且目标机 WebGL2 可靠，它的原生 WebGL 吞吐和 SDF 标签更有优势，体积也更小。代价是图模型、拖拽、邻居高亮、局部图、筛选都要自己组合；WebGL2-only 无 Canvas 兜底，老集显/远程桌面风险高。

**不选**：d3-force 自绘做主方案（只给布局，交互全自建）；Logseq/思源代码（AGPL，不能复制）；继续用 SVG 做实体图谱（画板不是图谱）；Perlite/Nodum 整套（PHP、Next+Postgres，非本项目的库）。

**与手工导图共存**：保留 `mindmap.html` 的自由画板（画笔/词云/文本框/SVG 导出），新增独立 `graph.html` 做实体图谱；不共享渲染器、不双写。桥接只走 `node_id`/`entity_id`：图谱节点可“在导图中打开”，导图节点可“生成局部图谱”；固化时把图谱子图坐标一次性导出为新导图 JSON，反向不自动同步。手工导图的稳定性不被图谱性能问题拖累。

**最小原型验证清单**（2–3 天）：

1. 数据：1k 节点/3k 边与 5k/10k 边，30% 中文标签（4–12 字）、8 种类型、2 个分区、50 组同名实体。
2. 启动/布局：1k 首次可交互 ≤1.5s，5k ≤5s；布局完成 1k ≤2s、5k ≤8s；首屏后主线程无 >200ms 长任务。
3. 帧率：目标机 WebView2 内，1k 平移/缩放 ≥45 FPS，5k ≥25 FPS；拖节点跟手 ≤50ms；标签按缩放显隐。
4. 图操作：邻居高亮 ≤100ms；按类型/置信度筛选 ≤150ms；局部图深度 2 ≤300ms；搜索定位 ≤200ms。
5. WebView2：真机检查 WebGL2；Sigma 无兜底时验证失败提示/降级；连续操作 30 分钟不崩、内存 <350MB。
6. 离线：断网冷启动，vendor 本地加载，无 CDN；PyInstaller 打包版可跑。
7. 数据：点击边可看来源引文并打开 chunk；置信度筛选；软删除/恢复；同名实体不被自动合并；合并/拆分有审计。
8. 判定：≥7/8 通过才选；5k <15 FPS 或布局 >15s 就退“全局限量+局部图 ≤800 节点”。

## 4. 数据模型建议

```
entities(id PK, kind, name, norm_name, disambig,
         aliases_json, status, confidence, merged_into, deleted_at)
edges(id PK, src_id, dst_id, rel, confidence, status,
      origin, evidence_n, deleted_at)
edge_sources(edge_id, doc_id, chunk_id, quote, page, start, end, confidence)
entity_aliases(entity_id, alias, norm_alias, source_id)
```

- 唯一键：`UNIQUE(kind,norm_name,disambig) WHERE deleted_at IS NULL`，**绝不做全局 `UNIQUE(name)`**；`disambig` 填分区/文档/义项 id。边唯一键 `(src_id,dst_id,rel)`，同为软删除条件索引，允许同两端不同类型边。
- 防同名误连：名称只是属性，id 才是身份；先抽 mention，按同文档/分区/上下文/向量相似度给候选打分，歧义时保留独立实体并标 `candidate`；别名表带来源，合并需 2 个独立来源或人工确认；跨分区默认不自动合并；合并用 `merged_into` 而非删除；展示不做“同名即同点”。
- 来源/置信度：一条边可有多条 `edge_sources`（doc/chunk/quote/页码/字符偏移），边置信度取各来源最大值或 noisy-OR，保存每条来源分；`status` 用 candidate/confirmed/rejected/merged，人工确认优先。引用沿用“快照+hash”，文档删除后仍可核对。
- 软删除：`deleted_at`+部分唯一索引；删实体时级联隐藏其边但不物理删；恢复/清理分离；`merged_into` 处理重定向。合并/拆分、确认/否决写 append-only 事件表，避免重跑抽取覆盖人工结论。
- 展示：全局图按分区/类型/置信度/度数过滤，超过上限明示“已截断”；局部图从当前文档/实体 BFS 深度 ≤2；默认不画低置信边，可在侧栏打开。

## 资料

1. https://github.com/secure-77/Perlite
2. https://github.com/secure-77/Perlite/blob/dev/perlite/Demo/Documentation/06-Graph.md
3. https://github.com/nodummd/nodum
4. https://github.com/logseq/logseq
5. https://github.com/logseq/logseq/blob/master/LICENSE.md
6. https://github.com/logseq/logseq/commit/1f9c017998e1472f413165c30e6df08663338ab1
7. https://github.com/logseq/logseq/issues/2089
8. https://github.com/logseq/pixi-graph
9. https://github.com/siyuan-note/siyuan
10. https://github.com/siyuan-note/siyuan/blob/master/kernel/model/graph.go
11. https://github.com/siyuan-note/siyuan/blob/master/app/src/layout/dock/graph/GraphEngine.ts
12. https://www.npmjs.com/package/cytoscape/v/3.35.0
13. https://bundlephobia.com/package/cytoscape@3.35.0
14. https://blog.js.cytoscape.org/2025/01/13/webgl-preview/
15. https://js.cytoscape.org/#performance
16. https://github.com/iVis-at-Bilkent/cytoscape.js-fcose
17. https://www.npmjs.com/package/sigma/v/4.0.6
18. https://bundlephobia.com/package/sigma@4.0.6
19. https://github.com/jacomyal/sigma.js/blob/main/CHANGELOG.md
20. https://www.sigmajs.org/how-to/technical/performance/
21. https://www.npmjs.com/package/graphology/v/0.26.0
22. https://github.com/graphology/graphology/tree/master/src/layout-forceatlas2
23. https://www.npmjs.com/package/d3-force/v/3.0.1
24. https://bundlephobia.com/package/d3@7.9.0
25. https://learn.microsoft.com/microsoft-edge/webview2/
26. `./01-frontend-audit.md`、`./02-backend-data-audit.md`
27. `../../../doclib/web/static/mindmap.html`

## 关键事实

1. 四项目中只有 Perlite、Nodum 是 MIT；Logseq、思源是 AGPL-3.0，代码不能复制进 MIT 的 DocLib，只能借鉴架构。
2. Perlite 图谱不自解析链接，读 Obsidian 插件的 `metadata.json`；无数据库、vis-network、全局/局部图。
3. Nodum 用 Markdown 做真值、ghost 节点承接未解析链接、WebGL2 图+sandbox 插件，是产品形态参考，不是可直接搬的库。
4. Logseq 以 Markdown/Org 文件为真值、block 引用为核心；思源以 `.sy` JSON+SQLite 索引、服务端构图+前端自研 WebGL/Canvas 引擎，是四者中最接近 DocLib 的。
5. Cytoscape.js 3.35（MIT）Canvas 默认、WebGL 预览；官方 1.2k/16k 边 20→100 FPS、3.2k/68k 边 3→10 FPS；138.9KB gzip，API 完整度最高。
6. Sigma.js 4.0.6（MIT）WebGL2-only、SDF 标签，约 110KB gzip（含 graphology）；官方只称“数万节点/边”，无 1k/5k 具体数字。
7. d3-force 3.0.1（ISC）只有布局，5.8KB gzip；1k/5k 性能无官方数据，需自建渲染/交互并用 Worker。
8. 现有 `mindmap.html` 是 84KB 单文件、SVG、全量 innerHTML 重建，适合手工画板，不适合作为 1k+ 实体图谱的渲染层。

## 未确认

1. DocLib 真实中文标签数据在 1k/5k 下的 FPS、布局耗时、内存，未实测；Cytoscape/Sigma 的数字均来自官方或非本项目场景。
2. 目标用户机器（集显/远程桌面/旧 WebView2）是否稳定提供 WebGL2；Sigma v4 无 Canvas 兜底，必须真机验证。
3. fcose 的真实 gzip 体积与 5k 布局时间；bundlephobia 的 718 B 明显异常，且 fcose 久未更新。
4. DocLib 2.0 的“图谱”是实体关系图、文档/块引用图，还是二者混合；这会影响标签、边数与交互，需产品定调。
5. Nodum 的“本地优先”表述：它是自托管服务器+Postgres，不是单文件夹本地应用；若要求离线单机，不能照搬。
6. Logseq 当前 Pixi 图谱在 3.5k+ 节点的实际表现；issue #2089 是旧版本证据，不能代表 V2。

## 推荐

1. **选 Cytoscape.js 3.35 + fcose 2.2 做第一版**，Canvas 默认、WebGL 按图规模开启；锁定 fcose 版本，自测 5k 门槛。
2. **Sigma 4 + graphology 作为备选**，只在“5k 是硬指标且 WebGL2 可靠”时启用；同时准备 Canvas/SVG 降级或“局部图”降级。
3. **保留 SVG 手工导图**，新增独立图谱页；二者只通过 `node_id`/`entity_id` 和一次性导出桥接，不合并渲染器。
4. **先定数据模型再做 UI**：entities/edges/edge_sources + 部分唯一索引 + 软删除 + 合并审计；同名只做候选，不自动连。
5. **原型用同一份 1k/5k 合成数据对比 Cytoscape 与 Sigma**，按第 3 节清单打分；达不到 5k 门槛就退“全局限量+局部图”，不为全量图牺牲主流程。
6. 不复制 Logseq/思源代码；MIT 的 Perlite/Nodum 如需复用，保留版权声明，但按栈差异只取架构。
