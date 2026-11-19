# DocLib 2.0 规划与实施资料索引

> 2026-11-19 用户批准实施。唯一布局为 A 三栏；浅/深仅为主题；右侧 AI 完整高度；局部图谱只在中央标签页。规划期间未改业务代码，仓库新增仅本目录。

## 先读这三份

1. **[PLAN.md](PLAN.md)** — 现状、开源调研、最终布局/主题、技术选型、阶段计划、验收、风险、已批准决定。
2. **[DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)** — 统一三栏、两套主题、tokens、组件、图谱/AI 设计、真实截图验收。
3. **[ARCHITECTURE.md](ARCHITECTURE.md)** — 数据模型（0006/0007）、API、前端模块、阅读器、AI 上下文、笔记双链、迁移/打包安全、文件级改动。

## 视觉概念稿

- [统一三栏 + 浅色主题（A）](concepts/study-1440.png)（源文件 `concepts/study.html`）
- [深色主题配色参考（B）](concepts/observatory-1440.png)（源文件 `concepts/observatory.html`；**其右侧上下分栏布局已否决，只看配色**）

> 概念稿是静态验证，不是业务页面；Phase 1 会用真实组件重建。

## 调研报告（带行号或 URL 证据）

- [01 前端审计](research/01-frontend-audit.md)：单文件结构、全局状态、52 处 fetch、51 色/6 圆角、XSS/性能/无响应式。
- [02 后端与数据审计](research/02-backend-data-audit.md)：schema/迁移/API、RAG 链路、引用快照、扩展点与坑。
- [03 运行时与交付审计](research/03-runtime-packaging-audit.md)：启动/单实例/数据目录、PyInstaller、打包脚本数据风险、WebView2 157、测试基线。
- [04 Obsidian 交互调研](research/04-obsidian-interactions.md)：工作区/标签/分屏/历史/命令面板/图谱/双链/PDF 适配，交互验收清单。
- [05 开源与图谱选型](research/05-oss-graph-libs.md)：Perlite/Nodum/Logseq/思源、Cytoscape/Sigma/d3/SVG 对比、数据模型、1k/5k 原型清单。

## 当前状态

- `git status`：仅 `docs/v2/` 未跟踪；`git diff` 空。
- 未安装依赖、未迁移数据库、未打包、未修改 `dist`/`data`。
- 本机 `dist/DocLib/data` 与 `DocLib/data` 当前不存在；真实资料库路径待 Phase 0 以只读方式确认。
