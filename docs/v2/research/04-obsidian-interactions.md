# Obsidian 交互调研：工作区、图谱、链接与阅读流

**范围**：Obsidian 是本地优先的 Markdown 知识库[home]；本报告只据官方帮助文档、官方 API 仓库与官方示例插件；帮助页为 2026-11 快照，`help.obsidian.md` 会 301 到 `obsidian.md/help`。社区论坛只用于核对导航历史现状；标「推断」处不是官方实现。

## 1. 工作区

| 元素 | 可观察行为 | 迁移到 DocLib | 不该照搬 |
|---|---|---|---|
| Ribbon | 左侧竖条；侧栏收起仍可见；图标可拖排序、右键隐藏、设置整体隐藏[ribbon] | 左轨 4–6 个主动作（库树/搜索/图谱/复习/设置），由命令注册表生成 | 仓库切换器/帮助/设置三件套；移动端快捷区 |
| 文件资源管理器 | 树；新建/重命名/删除/拖放移动；按名称/修改/创建排序；可自动定位当前文件；Alt/Shift 多选；右键菜单齐全[files] | 科目分区树+过滤；单击选中预览、双击固定；自动定位；虚拟滚动 | “拖入文件夹即移动/复制”的隐式语义；纯路径层级 |
| 标签页/关闭/固定 | 任意多标签；Ctrl+T、Ctrl+Tab、Ctrl+1..9、Ctrl+Shift+T；右键“锁定”，锁定标签里的链接总在新标签打开；可拖出成窗、可堆叠[tabs][sidebar] | 单窗格标签上限 12；恢复关闭；拖拽排序；固定=防替换；固定状态入布局 | 堆叠标签、拖出窗口、多窗口、侧栏“拖入即锁定” |
| 分割视图 | 右键标签左右/上下拆分；拖标签到边缘拆分；拖边框调大小；多标签组[tabs] | 最多 3 窗格，左右为主，可选上下；双击分隔条复位；每窗格独立标签与历史 | 无限嵌套、任意拖放拆分 |
| 左右侧栏 | 左 Ribbon+侧栏，右反链/出链；图标+tooltip；笔记可拖入侧栏并排；可折叠、可调宽、可多组[sidebar] | 左=库树，右=检查器（反链/出链/大纲/属性/AI）；折叠成图标条；宽度持久化 | 侧栏内多组垂直拆分 |
| 可调尺寸 | 拖标签组与侧栏边缘；侧栏宽度随 Workspaces 布局保存；窗格尺寸是否持久化未单列[tabs][sidebar][workspaces] | 三栏+窗格分隔条；最小/最大约束；侧栏宽度入布局，窗格尺寸需实测 | 假设所有窗格尺寸都自动持久化 |
| 前进/后退 | “Navigate back/forward”命令（Alt+←、Ctrl+[ 等随平台）；历史记录视图状态变化（`ViewStateResult.history`）[api]；论坛称历史不跨重启/工作区切换保存，页内链接不回到光标[forum1][forum2] | 每窗格独立栈；条目=docId+anchor+scroll；后退精确回位；新跳转清空前进栈；会话快照持久化 | 浏览器式页面重载；只按“文件”不按位置；不持久化 |
| 命令面板 | Ctrl+P；模糊匹配；最近使用置顶；可置顶命令；显示快捷键[palette] | Ctrl+P；同一命令注册表；最近+常用；分组；全键盘可用 | 把低频命令全塞进面板 |
| 快捷键 | 设置→快捷键；单命令多绑定；冲突/已分配筛选；恢复默认；按美式布局显示[hotkeys] | 可改键+冲突检测+导入导出；默认集克制；保留 Ctrl+P/Ctrl+W/Alt+←→ | 无冲突检测；把系统键当应用键 |
| 右键菜单 | 文件树/标签/正文/图谱节点各有菜单；标签菜单含关闭/锁定/关联/移窗；项随插件变化[more][files] | 统一命令源，按上下文启用；树/标签/正文/图谱/反链五类；Shift+F10 可开 | 菜单随功能膨胀、不可搜索 |
| 布局恢复 | 自动保存 `workspace.json`/`workspace-mobile.json`；Workspaces 插件保存命名布局（文件、标签、侧栏折叠与宽度）[ribbon][workspaces] | 冷启动恢复上次布局 + 3 个预设（阅读/复习/写作）；布局存 SQLite；带版本号与容错回退 | 任意命名布局管理、跨设备同步 |

API 侧面：`Workspace` 管理 splits、tab groups、sidedocks、leaves，`registerView` 可注册视图，示例插件演示 `addRibbonIcon`/`addCommand`[apireadme][sample]；插件 API 文档见 [docs]。这支持“命令注册表 + 可插拔视图”，但不提供现成的布局 UI。

## 2. 知识图谱

**可观察**：全局图节点=笔记/附件（附件可开关），连线=内部链接；节点度数越大，节点越大；hover 高亮相邻连线；单击开笔记、右键出菜单；滚轮或 `+/-` 缩放，拖拽/方向键平移，Shift 加速。筛选含搜索词、标签、附件、仅已创建笔记、孤立文件；忽略文件不出现。颜色组=搜索词+颜色；外观可调箭头、文本透明度、节点大小、连线粗细；力可调向心/排斥/相连吸引/连线长度；可按创建时间播放生长动画。局部图用命令打开，独有深度滑块（深度=从当前笔记最多经几篇笔记到达）[graph]。

**推断（非官方实现）**：帮助页只给“力”的语义，不给算法、渲染方式或数值；公开类型定义里检索不到图谱视图类型或物理参数[api]。因此只能复现交互契约，不能假设底层是 d3-force/Canvas，也不能假设布局可复现。图谱设置属于应用配置而非笔记内容（推断）。

**迁移**：SQLite `edges`（source_doc, target_doc, type）；局部图默认深度 1–2，BFS；节点大小=log(度数+1)；颜色=分区/标签组；筛选走 SQL；hover 只亮邻居、其余降透明；单击定位 anchor；拖动固定节点；全局图按需打开并限 2,000 节点；物理只给“紧凑/舒展”等 2–3 个参数预设；生长动画默认关。

**不照搬**：全库实时图当首页；把物理滑杆交给用户；用图谱替代树/搜索作为主入口；3D。

## 3. 知识链接

**Wikilink**：`[[笔记]]`、`[[笔记#标题]]`、`[[笔记#^块]]`、`[[笔记|显示文本]]`、`![[嵌入]]`；也支持 Markdown 链接，可关闭 wikilink 改用 Markdown；重命名时自动更新内部链接（可设“总是更新”）[links]。

**反链/出链/未链接提及/别名**：反链面板分“链接当前文件”和“提到当前文件名”（即未链接提及），可折叠、显示更多上下文、排序、过滤；忽略文件不出现[backlinks]。出链分“当前笔记中的链接”和“潜在链接”（与笔记名或别名匹配），点按钮可转正式链接；代码块内的潜在链接不进“当前链接”[outgoing]。别名写在 YAML `aliases` 列表；用别名建链会生成 `[[真名|别名]]`，别名也参与潜在链接/未链接提及[aliases]。

**Markdown 笔记适配**：保留 `[[...]]` 输入体验，但解析到 `docId`+标题/块 anchor；落库 `links`（source, target, anchor, display, resolved）；重命名不改 docId；未链接提及用 FTS 匹配标题/别名并回传段落位置。

**PDF 适配**：官方查看器支持页/选区链接（`[[x.pdf#page=1&selection=32,0,32,14|Gemmy, page 1]]`）、复制引用/选区链接、桌面端搜索，但不支持批注/高亮[pdf]。DocLib 用 `docId#page=12&rect=...`，反链显示“第 12 页”；不能只存页号，缩放/重排会漂移；未链接提及只在有文本层（或 OCR 文本入库）时做。

**Word 适配**：Obsidian 原生支持列表不含 `.docx`[formats]，DocLib 需自建锚点层：标题书签/段落索引/字符范围（页号只作展示缓存）；链接形如 `doc://<id>#p=37` 或 `[[文档#p=37]]`；反链显示段落摘要；标题改名不影响 docId。

**不照搬**：以文件名/路径作链接主键；点击未解析链接就静默新建空文档；只存链接文本不存结构化边。

## 4. 阅读工作流

1. **树选中**：Obsidian 单击即替换当前标签，Ctrl+单击新标签，右键可“在新标签/新标签组/新窗口打开”[files]。DocLib 建议单击选中并预览、双击/Enter 固定打开，避免浏览时误替换；树始终高亮当前 docId。
2. **分屏**：右键标签拆分，或把标签拖到窗格边缘；拖边框调比例[tabs]。DocLib 从树/链接“在右侧打开”，每窗格独立标签与历史。
3. **链接跳转**：默认同窗格替换；hover 预览（页面预览，编辑模式需 Ctrl+hover）[preview]；Ctrl+单击新标签，Ctrl+Alt+单击新标签组[tabs]。DocLib 做 300ms peek、Esc 关闭、点击后定位 anchor。
4. **返回原位置**：Obsidian 有视图后退/前进，但页内链接不回到光标，历史默认不跨重启保存[forum1][forum2]。DocLib 必须把 anchor+scrollTop 作为历史条目，后退精确回位，这是硬需求。
5. **历史导航**：视图状态变化可标记进入导航历史（`ViewStateResult.history`）[api]；DocLib 每窗格栈、Alt+←/→ 与按钮、上限 100 条、关会话保存、启动恢复；右检查器“跟随活动文档”可锁定。

## 5. 对 DocLib 的适配结论

**必须做（P0）**
- 三栏骨架：左库树/中标签+分屏/右检查器；宽度、折叠、窗格树可持久化。
- 命令注册表：Ribbon、命令面板、右键菜单、快捷键共用同一 command id 与启用条件。
- 每窗格历史 + 精确回位（docId/锚点/滚动）；冷启动恢复布局与历史。
- 稳定 docId + `links` 表：反链、出链、未链接提及、别名；重命名不断链。
- 局部图谱（1–2 跳）+ 筛选/颜色/邻居高亮 + 点击定位；全局图按需。
- Markdown/PDF/Word 三种 anchor 解析与坏链提示；空态/索引中/文件丢失态。

**可简化（P1）**
- Ribbon 只留 5 个主动作；设置放顶栏，不做仓库切换器。
- 标签不做堆叠/拖出窗口；上限 12，超出提示关闭旧标签。
- 图谱不做物理面板/生长动画；只给 2–3 个参数预设。
- 工作区不做任意命名管理；上次布局 + 3 个预设足够。
- PDF 只做页/选区链接，不做批注；Word 只做段落/书签锚。

**不要做（P2/负清单）**
- 不做 Obsidian 插件系统/第三方插件 API；不做多窗口/弹出窗/移动端手势。
- 不以文件名/路径为真相；不做悬挂链接自动建空文档。
- 不做全库实时图首页、3D 图、按创建时间的生长动画。
- 不做 PDF 全文未链接提及（除非 OCR 文本已入库且有页码映射）。
- 不把布局做成可跨设备同步的复杂快照。

**交互验收清单（可观察/可测）**
1. 冷启动：窗格数、活动标签、侧栏宽度/折叠、最后 anchor 与退出前一致。
2. 树：当前 docId 高亮；自动定位开关生效；过滤后仍能定位；单击预览、双击固定。
3. 标签：Ctrl+单击新标签；固定标签被链接跳转不替换；Ctrl+Shift+T 恢复关闭；拖拽排序持久化。
4. 分屏：左右/上下拆分；拖分隔条改宽；关闭一窗格不影响其他；布局重启后一致。
5. 历史：A→B→C 后退两次回 A、前进回 C；新跳转清空前进栈；上限 100。
6. 回位：从搜索到第 3 页/第 5 段，后退再前进回同一 anchor，滚动误差 ≤1 行。
7. 命令面板：Ctrl+P 模糊搜“拆分/反链/导出”；最近使用置顶；全键盘完成打开/分屏/关闭。
8. 快捷键：改键即时生效；冲突提示；恢复默认；导入导出配置。
9. 右键：树/标签/正文/图谱/反链五类菜单；项随上下文启用；与面板同一 command id。
10. 链接：`[[文档#标题]]`、`[[文档#^块]]`、`![[图]]`、`doc://id#p=37` 均可解析；反链/出链/未链接提及可折叠、过滤、跳转；坏链提示不崩溃。
11. 重命名：改标题后入链仍可跳；标题变化导致 heading anchor 失效时有回退提示。
12. 图谱：节点大小随度数；hover 只亮邻居；滚轮缩放/拖拽平移；筛选后节点数变化；局部深度 1↔2 节点集变化；点击定位。
13. 规模：2,000 节点全局图打开 ≤2s、拖拽可用；10,000 文档库树滚动不卡。
14. 状态：无文档、索引中、源文件丢失、模型不可用均有明确文案与下一步。

## 6. 可迁移交互决策（≤20）

1. docId 是链接、反链、图谱的唯一主键，路径只用于展示。
2. 三栏骨架固定，可折叠可调宽，布局持久化。
3. 单窗格多标签，最多 3 窗格；不做多窗口。
4. 标签可固定；固定标签不被链接跳转替换。
5. 树单击预览、双击固定；Ctrl+单击新标签（有意区别于 Obsidian 单击即打开）。
6. 每窗格独立历史；Alt+←/→；新跳转清空前进栈。
7. 历史条目含 docId+anchor+scrollTop；后退精确回位。
8. 命令注册表是唯一命令源，四个入口共用。
9. Ctrl+P 命令面板：模糊、最近、置顶、分组。
10. 快捷键可改、可检冲突、可导入导出、可恢复默认。
11. 右键菜单按上下文启用，键盘可开。
12. 冷启动恢复布局；另存 3 个场景预设。
13. 右检查器标签化：反链/出链/大纲/属性/AI，可跟随、可锁定。
14. 反链分“已链接/未链接提及”，支持折叠、过滤、跳转。
15. 出链分“已有/潜在”，潜在链接一键转正式。
16. 别名参与链接解析、未链接提及与搜索，不改显示文本。
17. Markdown 用标题/块锚；PDF 用 page+rect；Word 用段落/书签锚。
18. 图谱默认局部图（深度 1–2），全局图按需且限节点。
19. 节点大小=log 度数，颜色=分区/标签，hover 邻居高亮；只给参数预设，不做滑杆/动画/3D。

## 来源

[ribbon]: https://help.obsidian.md/ribbon
[tabs]: https://help.obsidian.md/tabs
[sidebar]: https://help.obsidian.md/sidebar
[files]: https://help.obsidian.md/plugins/file-explorer
[palette]: https://help.obsidian.md/plugins/command-palette
[hotkeys]: https://help.obsidian.md/hotkeys
[more]: https://help.obsidian.md/more-options-menu
[workspaces]: https://help.obsidian.md/plugins/workspaces
[graph]: https://help.obsidian.md/plugins/graph
[links]: https://help.obsidian.md/links
[backlinks]: https://help.obsidian.md/plugins/backlinks
[outgoing]: https://help.obsidian.md/plugins/outgoing-links
[aliases]: https://help.obsidian.md/aliases
[preview]: https://help.obsidian.md/plugins/page-preview
[pdf]: https://help.obsidian.md/pdf
[formats]: https://help.obsidian.md/file-formats
[api]: https://github.com/obsidianmd/obsidian-api/blob/master/obsidian.d.ts
[apireadme]: https://github.com/obsidianmd/obsidian-api
[sample]: https://github.com/obsidianmd/obsidian-sample-plugin/blob/master/src/main.ts
[docs]: https://docs.obsidian.md/
[home]: https://obsidian.md/
[forum1]: https://forum.obsidian.md/t/backward-navigation/97829/2
[forum2]: https://forum.obsidian.md/t/remember-navigation-history-when-closing-obsidian-or-switching-workspace-layouts/103437/2
