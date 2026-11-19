# DocLib v1 前端审计（index.html / mindmap.html）

对象：`doclib/web/static/index.html`（1837 行）、`mindmap.html`（1902 行）。只读两文件，未读 server.py，未运行程序；括注为行号。

## 1. DOM/布局与 CSS 体系

**骨架**（index）：`header`(256-278) → `main#main` 三栏 grid(280-334) → `footer`(336-339) → 模态 `#mask`(341-347) → `#toast`(348) → 单个 `<script>`(350-1835)。header 为 brand+`#subject`(257)、搜索区(258-267)、右侧 `.actions` 九个控件（导图/资料导图/分区/模型/导入/回收站/备份/设置，268-277），`flex-wrap:wrap`(23) 会折行。三栏 `272px minmax(320px,1fr) 400px`(49)，`.narrow` 变两栏并 `#detail{display:none}`(51-52)；每个 `.pane` 独立 `overflow:auto`(54)——三个互不联动的滚动容器。左 `#tree`(281-287) 一个 UL 承载整棵树；中 `#list`(289-292)；右 `#detail`(294-333) 上半为常驻 AI 问答区(295-330)，下半"内容预览"。

**变量**仅 12 个(8-13)：`--ink #242a33 / --sub #6b7480 / --line #e2e8f0 / --accent #1f4e79 / --accent2 #2e6da4 / --accent-soft / --bg #f5f7fa / --mark #ffe9a8 / --ok / --warn / --panel / --radius 10px`。字体 Microsoft YaHei/PingFang SC(17)，14px/1.6。圆角六档并存（6/7/8/10/14/20px），间距无 token；index 的 CSS 内 278 处 px（mindmap 94，合计 372）、em 仅 3 处；两文件共 52 个 hex、CSS 内 122 处颜色字面量，JS 另有硬编码（819、1330、1661）。

**组件类**：树 `node/caret/count`(70-87)、列表 `result/r-title/r-meta/chip/r-snip/r-foot`(90-102)、QA `qa-*`(106-142)、详情 `d-*`(145-151)、空态 `empty`(154-156)、模态 `mask/modal`(159-177)、报告 `tag.ok/up/fail/skip`(174-177)、`tagline`(204-207)、右键 `ctxmenu`(210-218)、树选择器 `tp-*`(221-234)、拖拽指示 `drop-before/after/child`(237-244)、回收站 `rb`(247-251)。**状态**：`.node.active`(75)、`.result.active`(95)、`.chip.bad/.sem`(196-197)、`#toast.show`(185-190)、`.spin`(191-194)、`button.danger`(233-234)。

**响应式**：两文件 **0 处 `@media`**，唯一断点是 JS 的 `innerWidth<1150`(1813-1814)。窄屏右栏 `display:none`(52)，而 `initSplitter` 注释自称"AI 区是抽屉"(1629)——实际无抽屉，**小屏 AI 不可达**。重复/覆盖：`.qa-bar` gap 先 8px(111) 后 6px(114)；`#detail` padding 在 57 与 128 行两次定义；`#detail-handle`(125-127) 是补丁。

**视觉**：桌面工具移植风的企业后台。白卡片 + 1px 浅灰描边 + 唯一深蓝 #1f4e79 强调、10px 圆角、极轻阴影(24)、12px 大写字距小节标题(59-62)、胶囊 chip、卡片 hover 抬边(94)。信息密度高，无插画无渐变，动效只有 .15s 边框过渡与 spinner。

## 2. JS 架构

经典 `<script>`（非 module），顶层函数即全局：`$`(351)、`api`(352-357)、`state`(358)。**state 只一个对象**但很浅：`{nodeId,scope,query,tree,currentDoc,partition}`(358)；另有模块级可变全局 `ctxEl`(458)、`rbTab`(719)、`qaConvId`(1463)、`PROVIDER_TPL`(1204)；`state.query` 决定全部列表分支（454、670、923、961）。

**API 封装**：fetch → `r.json()` → 若 `j.error` 抛错(351-357)。不判 HTTP 状态、无超时、0 处 `AbortController`。共 52 处调用，分两套并行接口：legacy `/api/{tree,docs,search,ask,import,chunk,open}` 与 `/api/rev/{partitions,tree,docs,search,import,ask,mindmap/generate_from_docs}`，**每个读点都是三元分支**（441、872、896、986、1652）。其余覆盖 node create/rename/delete/reorder/move/indent/outdent(485-556)、doc move/set_nodes/delete/restore(666、919、957、811)、recycle 与 purge(750-811)、backup(1036)、maintenance/rebuild(1136、1152)、secrets(1164-1195)、ai providers CRUD(1264-1374)、ai/test、runs、embed(1326-1420)、conv list/detail/update/delete/export/export_batch(1469-1770)。

**事件绑定三套混用**：`.onclick=` 赋值 55 处（392、404、426、469、732、1024）；`addEventListener` 仅 5 处(479、480、981、1801、1814)；**HTML 内联** `onclick="closeModal()"` 6 处（581、731、999、1003、1023、1116）依赖全局函数，是模块化第一道墙。无委托，`renderTree` 每次全量重挂(392-409)。

**弹窗**：唯一 `#mask`+`.modal`(341-347)，`showModal/closeModal`(974-981) 用 innerHTML 注入 body/foot，点遮罩关闭(981)；无焦点陷阱、无 Esc、无滚动锁、不支持嵌套。原生 `prompt` 4 处(483、490、1518、1805)、`confirm` 8 处(497、747、791、955、1181、1309、1418、1512)。

**拖拽**：HTML5 DnD。`attachNodeDrag/Drop`(631-691) 按 `clientY` 三分区(650-652) 判 before/after/child，payload 为 `text/plain` 的 `{t:'node'|'doc',id}`；文档卡 dragstart 高亮 #tree(849-858)。无触摸、无悬停展开、dragleave 只清样式(654)。

**splitter 两页两套**。index 用绝对定位把手 `#detail-handle`(1596-1639) 改 `gridTemplateColumns`(1623、1631)，限 300–760px(1614)，松手写 `doclib_detail_w`(1637)。mindmap 用真实列 `30% 6px 70%`(33)+`#splitter`(1823-1835)，**每次 mousemove 都写 localStorage**(1831)。

**设置页** `openSettings`(1042-1131)：一个 modal 塞五段（索引/密钥/模型/向量/调用记录），编号错序（⑤在④前，1104/1112），并发五个 refresh(1117-1121)。

**AI 面板**：会话 = 单变量 `qaConvId`(1463)+"追问"复选框，勾选才带 `conversation_id`(1651-1658)，"新对话"清空(1793-1800)；历史 `refreshConvList`(1465-1534) 取前 50 条，支持 pin/fav/tag/导出/删除与勾选合并导出(1762-1776)；引用 = 正文 `[n]` 正则加粗(1676-1677)+`.qa-src` 点击 `showChunk`(1678-1688)；模型切换 = `#model-pick`(272) 与 `refreshModelPicker`(1426-1460) 双向绑定，切换即 POST default，失败回滚。

## 3. mindmap.html

**DOM**：header(115-125)+`main{grid-template-columns:30% 6px 70%}`(33)；左栏 tools(129-143)/swatches(144-146)/hint(147)/`#tree`(148)；右栏 `svg#cv`(152-165)，`g#world` 下五层 `layer-strokes|edges|items|clouds|temp`(158-164)，加 `#empty-tip`、`#marquee`(166-167)、`svg#mini`(168)、`input#inline`(169)；`#ctx`(173)。

**数据模型**(206-219)：`state.map={items,edges,strokes}`+`view{x,y,k}`+`sel/selIds/cloudSel/undo(≤80)/redo/treeMap`。item：id、node_id、text、x/y/w/h、shape(ellipse|rect|round|text)、color、fontSize、collapsed、hidden、cloud{show,dx,dy,w,h,link,words[{t,w,fs,color}]}；edge：id、from/to（**可为 null**，944-945）、x1y1x2y2、style(arrow|plain|dashed)、color；stroke：id、`d`、pts、color、width。

**接口**：`/api/map/save`(1776，payload={items,edges,strokes,view})、`/api/maps`(1784)、`/api/map/{name}`(1793)、`/api/map/new|rename|delete`(1619、1866、1877)、`/api/map/export`(1530)、`/api/tree`(705)、`/api/docs?node=`(688)。

**渲染**：五层全量 innerHTML 重建 `renderItems`(309-356)/`renderEdges`(382-414)/`renderStrokes`(424-434)/`renderClouds`(511-562)/`renderMini`(1358-1396)，由 `renderAll`(272-279) 串联；拖动时每 pointermove 重渲三层(884)，每帧重算 `childCount`(323→263-269) 与 `hiddenSet`(244-262)——**O(节点×边)/帧**。

**编辑**：画笔(765-776、824-834，每 2px 采点直改 `d`，无平滑)；橡皮扫擦(1120-1170，半径 12/k)；文本框(777-786)+内联 input 换算(1087-1117)；词云 `layoutCloud` 贪心换行+6 次缩容(444-469)、双击加词、prompt 改词(582)、右键菜单(589-673)、`autoFillCloud` 拼节点关键词+子节点名+文档标题(676-701)；连线/端点/中点插入节点(1334-1355)；套索多选(796-808、893-911)；吸附辅助线(836-877)。

**撤销**：快照 `snap=JSON.stringify(items,edges,strokes)`(1712-1719)，栈 80，**不含 view 与选中态**；`pushUndo` 在 pointerdown 处调(1033、1047)，粒度为一次手势；Ctrl+Z/Y、Delete/Backspace(1738-1760)。

**缩放/导出/保存**：wheel 以指针为锚 0.2–3×(977-986)，中键或空白平移，`applyView` 设 transform(234-238)，mini 可点跳(1398-1418)，`fitView`(1444-1456)；导出手拼 SVG `buildSvgString`(1458-1519) 后 POST `/api/map/export`；PNG = SVG→Image→canvas 2×→toBlob→FileReader→同接口(1544-1568)；`download()`(1521-1527) 定义后从未调用；保存 debounce 1200ms(1764-1768)，beforeunload 用 `sendBeacon`(1887-1894)。

**生成导图**：①从树：`openGeneratePicker`(1630-1698) 自建浮层勾选 → `generateFromTree`(1571-1627) 横向布局 COL250/ROW74 → new+save；②从资料：入口在 index `#btn-map-docs`(1707-1720)，POST `/api/rev/mindmap/generate_from_docs` 后跳转。

**?map= 嵌入**：**非 iframe，是整页跳转** `/mindmap.html?map=<name>`(index 1718)；boot 读 `?map`(1808-1815)，缺省回退 `doclib_mm_last` 再回退列表首项；另有调试钩子 `?autogen=名称`(1837-1839) 直接生成并覆盖。

## 4. 可复用与必须重写

**可复用**（契约与语义，非代码）：①API 字段（tree 的 `_sub_count/is_system`、results 的 `chunk_id/heading_path/semantic/score`、conv 的 `messages/citations/drifted`、providers 的 `free/is_default/key_ok`）；②交互语义（树三分区拖拽、卡片四动作、`[n]` 引用可点、会话 pin/fav/tag/合并导出、词云挂节点、扫擦橡皮）；③视觉原子（变量命名、#1f4e79 主色、chip/tag/tagline/empty/spin）；④算法（指针锚定缩放、contentBBox+fitView、mini 视口框、连线边界交点 358-370）。

**必须重写**：①渲染层（index 49 处、mindmap 20 处 innerHTML 拼接，79 处 `.onclick=` 赋值）；②状态层（全局可变 state 加十余个自由变量，含 `savedFlag/erasing/dragging/showHidden`）；③布局层（固定 272/1fr/400 与 JS 断点；多标签与嵌套分割需面板级上下文）；④弹窗层（单 mask、prompt/confirm 12 处）；⑤AI 面板（右栏固定块 → 可停靠侧栏+阅读器引用锚点）；⑥图谱（现 mindmap 是自由画板，无实体/关系/布局引擎，除 `node_id` 外不绑数据，不能当知识图谱用）；⑦单文件架构（3739 行内联 CSS/JS，无构建无模块）。

**技术债/风险**：①**XSS**：innerHTML 全量拼串；`esc()`(364) 只转 `& < > "`、**漏单引号**；多处不走 esc 插属性——`fill="${col}"`(mindmap 293-306、487、1501、1510)、`data-node`(333)、`value="${p.id}"`(index 423、1442)，正常路径受控，但导图 JSON 由服务端回放，篡改或导入他人导图即成注入面；`highlight`(365-373) 先转义再插 `<mark>`，会对实体二次匹配。②**内联事件** 6 处依赖全局函数，迁 module 即失效。③**prompt/confirm** 共 17 处（index 12、mindmap 5），阻塞不可测。④**无 CSP、无 CSRF token、无鉴权头**。⑤**性能**：mindmap 每帧全量重建、index 每次动作 `loadTree` 全树重建、splitter 每帧写 localStorage、无 AbortController/去抖/虚拟列表。⑥无 a11y（div/g 无 role、无键盘可达、11px 字号多）、无测试/类型/lint、错误只 toast。⑦死代码与小错：`download()` 未用、窄屏"抽屉"注释与实现不符、`reorderNode` 后误刷模型选择器(508)、`renderClouds` 的 typeof 守卫(512)。

## 5. 状态持久化现状

**localStorage 仅 4 键，全是 UI 偏好**：`doclib_detail_w`（右栏宽，index 1618/1620/1637）；`doclib_mm_last`（最后导图，index 1716 写，mindmap 1624/1848/1857/1869 写、1810 读、1878 删）；`doclib_mm_collapsed`（左树折叠，710/730）；`doclib_mm_split`（左右比例，1831/1834）。

**存后端**：知识树与统计、文档与切块、搜索、分区、回收站、备份、维护状态、密钥（仅回掩码）、模型配置与默认模型、AI 调用记录、向量索引状态、会话与消息、导图数据（含 view）。

**不持久化、刷新即丢**：index 的 `nodeId/scope/query/partition/currentDoc`（仅靠 `?node/?q/?partition/?conv/?chunk/?ask/?settings` 深链恢复，1816-1832）、`qaConvId`、追问开关、滚动位置；mindmap 的工具/颜色/选中/`showHidden`/撤销栈。

## 关键事实

1. 两文件均单文件自包含，零外部依赖、零构建；合计 3739 行，CSS 352 行、230 个选择器。
2. 统一范式：全局单例 state+字符串 HTML+逐元素绑定；无框架/组件/路由（换页靠 `location.href`）。
3. 双 API 面并存（`/api/*` 与 `/api/rev/*`），5 处 API 读点在运行时三元选择。
4. 响应式=JS 单断点 1150px，0 处 `@media`；窄屏右栏 `display:none`，AI 不可达。
5. 设计系统只有雏形：12 变量对 52 个硬编码色、6 档圆角、0 间距 token、372 处 px。
6. 最大资产是 AI 闭环：检索→引用→会话→导出 Word→模型切换与免费/付费标记。
7. mindmap 是画板而非图谱：自由节点/边/画笔/词云/文本/撤销/缩放/PNG·SVG/自动保存。

## 未确认

- server.py 的路由、安全头、CSRF/Origin 校验、绑定地址（超出"只读两个 HTML"授权）。
- 导图数据在磁盘的存储与校验（决定上文 XSS 路径是否真的可达）。
- `/api/rev/*` 与 `/api/*` 的关系；`partition` 与 `nodeId` 混用（431 行把 partition id 当 node 传）。
- 窄屏"抽屉"是否有未提交实现；`doclib_mm_last` 两页耦合是否有意。
- 真实观感与可访问性实测（禁止运行程序，无截图验证）。

## 对 2.0 的含义

1. **不要增量改造 index**：渲染层与状态层同时是重写对象，保留 API 契约即可。
2. **先收敛 API**：去掉 `/api/rev` 分支，否则每个新视图都要写两套。
3. **面板=独立上下文**：多标签与分割要求 state 按面板实例化，nodeId/query/partition/conv 从 URL 升为面板级路由。
4. **AI 侧栏**：从右栏固定块升级为可停靠面板+引用锚点，复用 conversation/citations 契约。
5. **阅读器需新容器**：现在三栏各自滚动、详情是卡片，缺连续阅读与目录。
6. **图谱与画板分家**：画板保留交互语义重写渲染；图谱要独立数据模型（实体/关系/布局）。
7. **token 化**：52 色收敛为 ≤12 语义色，圆角/间距/字号建尺度。
8. **安全基线前置**：CSP+全文本节点渲染（禁 innerHTML）+真 dialog+去 prompt/confirm，是门槛不是优化项。
