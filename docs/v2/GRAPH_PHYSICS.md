# 图谱实时物理拖动（Graph Live Force）

分支：`feat/graph-live-force` ｜ 目标：只增强图谱交互，不改工作区、数据模型和视觉结构。

## 1. 技术选型判断

| 方案 | 结论 | 原因 |
|---|---|---|
| **现有 Cytoscape + fCoSE** | 保留初排，不用于拖动 | fCoSE 是离散布局，每次 `runLayout` 都重算全图；拖动时重跑会抖动、抢视口，违反“不要每次 mousemove 从零重算”。 |
| `cytoscape.js-cola` | 不采用 | 有成熟 Cola.js 物理/约束，可处理拖动，但引入 webcola 体积与约束语义；`fit`/全布局仍会改变视口，需额外关掉。 |
| `cytoscape.js-d3-force` | 不采用 | API 最接近（`infinite`、`fixedAfterDragging`、d3-force 参数），但额外引入 d3-force + 扩展，维护状态较弱；当前只需少量可调物理量，自研更可控。参考：[README](https://github.com/shichuanpo/cytoscape.js-d3-force) |
| `force-graph` | 不采用 | 自带 HTML5 Canvas 渲染与 d3-force，会替换现有 Cytoscape 渲染、节点样式、筛选/搜索、点击/双击/高亮，收益不足以抵消回归风险。参考：[force-graph](https://github.com/vasturiano/force-graph) |
| `pixmix/obsidian-viewer-nextcloud` | 仅参考 | 只读 Nextcloud 应用，渲染 Obsidian vault、图谱、搜索和 canvas；不是可嵌入 Cytoscape 的物理层，但验证了“图谱是可拖拽、可探索视图”的产品预期。参考：[viewer-nextcloud](https://github.com/pixmix/obsidian-viewer-nextcloud) |
| `OutBlade/obsidian-vault-dashboard` | 仅参考 | Obsidian 插件，含 force-directed knowledge graph、tag cloud；其交互方向与本次目标一致，但插件代码/依赖不适合直接塞入现有渲染器。参考：[vault-dashboard](https://github.com/OutBlade/obsidian-vault-dashboard) |
| **自定义轻量力模拟 + 现有 Cytoscape 渲染** | **采用** | 只替换“拖动期间的节点位置更新”，保留所有元素与视觉；不新增依赖；可在同一事件循环里控制阻尼/停止/资源释放。 |

Obsidian 官方 Graph View 说明可确认其是可交互关系图谱，但内部算法未公开；这里按“弹簧 + 斥力 + 阻尼 + 慢回稳”的可观察行为实现，不冒充其源码。参考：[Obsidian Graph view](https://obsidian.md/help/plugins/graph)。

## 2. 实现结构

```
doclib/web/static/app/graph-force.js   新增：ForceSim（纯物理，不依赖 fCoSE）
doclib/web/static/app/views.js         renderGraph 接入：grab/drag/dragfree、参数面板、
                                        pin、位置持久化、生命周期清理、布局初排保留
doclib/web/static/app/main.js          activateTab 切换/关闭时调用旧 host.__cleanup()
doclib/web/static/styles/views.css     物理参数 details / pinned 节点边框
```

### 行为

- **初排**：仍由 fCoSE 完成。若该图已有保存位置，直接使用；若全部节点都有位置则不再跑 fCoSE；部分缺失时 `randomize=false` 初排后恢复已保存位置。
- **单击**：不启动模拟（`grab` 只记录锚点，`drag` 才创建 `ForceSim`），避免点击节点导致整图被推动。
- **拖动**：被拖节点按 1.3× 鼠标位移固定到指针位置；其他节点每一步计算：
  - 相连边的弹簧力（不同关系权重：mount 1.15 / manual 1.35 / wikilink 1.08 / hierarchy 0.85 / ai 0.55）；
  - 节点间斥力（小型图 O(N²)；>260 节点使用 3×3 网格近似，O(N)）；
  - 弱中心力 + 软半径环（用拖动开始时的图中心/RMS 半径，防止整图塌缩或漂走）；
  - 阻尼、速度上限和 alpha 衰减（默认约 3–4 秒回稳）。
- **松手**：被拖节点的最后位移转成速度，模拟继续衰减；alpha 到阈值后停止，保存全部节点位置。
- **不重算 fCoSE、不改 zoom/pan、不 fit**。
- **固定节点**：节点信息卡新增“固定位置/取消固定”；固定 ID 存 localStorage，模拟跳过其积分但仍受弹簧/斥力影响。
- **手动布局**：节点位置写入 `doclib.graph.positions.v1`；刷新/切标签/关窗保存。`重置布局` 只清当前显示节点的位置并重新 fCoSE。
- **资源释放**：切换标签/关闭图谱/切换主题时，`main.activateTab` 调用旧 host 的 `__cleanup`；`stopSim` 取消 rAF，销毁 Cytoscape；页面隐藏时停止；窗口 `beforeunload` 保存位置。`__doclibForce()` 在切换后返回 `null`。
- **参数面板**：图谱工具栏“物理参数”可调斥力、弹簧、阻尼，并恢复默认；参数存 localStorage，拖动时即时生效。默认：斥力 16000、弹簧 0.012、阻尼 0.88。

### 降级

| 节点数 | 帧间隔 | 说明 |
|---|---|---|
| ≤300 | 15ms（约 60fps） | 直接 O(N²) 斥力 |
| 301–600 | 15ms | 网格斥力 |
| 601–1200 | 33ms（约 30fps） | 网格 + 速度上限 11 |
| >1200 | 50ms（约 20fps） | 网格 + 降帧 |
| >2400 | 停止 | 图谱 API 上限 1500，正常不会触发 |

## 3. 验证记录

### 自动化/构建

- 原有 13 个 Python 测试保持通过（本次未改后端/数据库）。
- 6 个 ESM `node --check` 通过。
- `test_http_v2`/迁移/上下文等既有测试不涉及本次改动。

### Playwright（Edge/Chromium）

- 小图（demo 28 节点/28 边）：
  - 单击节点：`window.__doclibForce()` 为 `null`（不启动模拟）。
  - 拖动 80×50px：拖动中 `iterations=19`，`alpha=1`，`motion≈20.5`；松手 1s 后 `alpha≈0.34`；约 3.5s 后 `alpha=0`。
  - 邻居 `node:1/document:2/note:1` 均产生位移；视口 `zoom=1.05455`、`pan=(364.7,399.3)` 前后完全一致。
  - 切换“搜索”后 `window.__doclibForce()` 返回 `null`；位置条目 28 个已写入。
- 大图（临时 perf 库 804 节点/803 边，**独立 `DOCLIB_DATA`，不碰真实库**）：
  - 加载约 6.5s；拖动时 `nodes=804/edges=803`，`degraded=true`，`frameInterval=33`；视口 zoom/pan 前后一致；无 pageerror。
- 固定：
  - 固定 `node:1` 后拖动 `node:3`，`node:1` 位移 `0.0,0.0`；刷新后位置仍一致。
- 位置持久化：拖动后刷新，`node:1` 位置差 `0.0,0.0`。
- 重置布局/物理参数：参数面板 3 行可操作；`重置布局` 重新布局且不抛错。

### 实际 WebView2

用原生窗口 + `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`，通过 Playwright CDP 连接真实 WebView2：

- 窗口标题：`DocLib 2.0 · 本地知识工作台`（启动冒烟）。
- 拖动 `node:3`：`during {nodes:28,edges:28,iterations:17,alpha:1}`；1s 后 `iterations=77, alpha≈0.336`。
- 视口：`zoom=0.8104967`、`pan=(317.88,415.03)` 前后一致。
- 切换标签后 `window.__doclibForce()` 返回 `null`，rAF 已取消。
- 截图：`docs/v2/screenshots/native-webview2-force.png`（拖后；鼠标移开避免 hover 变暗）。

## 4. 性能与风险

- 小图：60fps，拖动中每帧只 O(N+E)，不跑 fCoSE；大图：30fps + 网格斥力；更大图自动降帧。
- 风险：
  1. 自研物理不是 Cola/d3 的严格实现，极端拓扑（多个高连接组件）可能需要调参；面板已提供三项关键参数。
  2. 800 节点以上会跳过部分远距离斥力（网格近似），局部布局可能与全量 O(N²) 略有差异。
  3. 物理参数/位置/固定状态存在 localStorage；清理浏览器数据会回到默认布局。
  4. 只在拖动/回稳时耗 CPU；空闲不跑 rAF；页面隐藏/切标签/关图停止。
  5. 未改后端/数据模型/密钥/真实库；perf 数据是临时 `DOCLIB_DATA` 副本。
- 回滚：只改 `views.js`、`main.js`、`views.css` 并新增 `graph-force.js`；回退这 4 个文件即可，数据库无需回滚。

## 5. 参考

- [cytoscape.js-cola](https://github.com/cytoscape/cytoscape.js-cola)（含 `animate`、`ungrabifyWhileSimulating`、拖动处理）
- [cytoscape.js-d3-force](https://github.com/shichuanpo/cytoscape.js-d3-force)（`infinite`、`fixedAfterDragging`、d3-force 参数）
- [force-graph](https://github.com/vasturiano/force-graph)（Canvas + d3-force，会替换渲染层）
- [Obsidian Graph view](https://obsidian.md/help/plugins/graph)
