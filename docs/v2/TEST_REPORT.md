# DocLib 2.0 测试与验收报告

执行时间：2026-11-19 ｜ 分支 `v2.0-dev` ｜ 工作目录 `E:\user351282\知序\DocLib`
所有 Python 测试使用临时 `DOCLIB_DATA`，不读写真实 `dist/DocLib/data`；未 push。

## 1. 自动化测试（13/13）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `.venv\Scripts\python.exe tests\smoke.py` | ✅ 退出码 0 |
| 2 | `tests\test_scope_isolation.py` | ✅ |
| 3 | `tests\test_partitions.py` | ✅ |
| 4 | `tests\test_citations.py` | ✅ |
| 5 | `tests\test_mindmap_gen.py` | ✅ |
| 6 | `tests\test_graph.py` | ✅ |
| 7 | `tests\test_reader.py` | ✅ |
| 8 | `tests\test_notebook.py` | ✅ |
| 9 | `tests\test_context.py` | ✅ document/selection/node/note/all + 旧调用 |
| 10 | `tests\test_migrations_v2.py` | ✅ 旧库 1..5→7、备份、幂等、失败回滚 |
| 11 | `tests\test_workspace.py` | ✅ 校验/夹取/损坏回退/reset |
| 12 | `tests\test_http_v2.py` | ✅ CSP/XFO/MIME/404/Range/workspace/Host |
| 13 | `tests\test_notes.py` | ✅ |

补充：`git diff` 中全部前端 ES Module 通过 `node --check`；Playwright（Edge 157）无 pageerror。

## 2. 真实 HTTP / 打包

- `scripts/audit_doclib.py`（demo fixture，`DOCLIB_AUDIT_DATA` 指向临时库）：**58/60 通过**。
  - 未通过：`GET /api/search` 对“卷积定理”在 demo 语料无命中（v2 UI 走 `/api/rev/search` + `/api/v2/notes/search`，已手工验证）；`tree indent` 的 demo 层级前置条件。
  - 已修复：同秒重复备份的文件名冲突（`doclib/system.py`，`test_http_v2` 覆盖）。
  - 安全项：CSP、Host/Origin、JSON、路径穿越、CSRF、资料库外路径、2MB body 等均通过。
- `DocLib.spec` PyInstaller onedir 构建成功。
- 原生窗口冒烟：`DocLib.exe` 启动后主窗口标题 `DocLib 2.0 · 本地知识工作台`，进程响应；加载 `/api/v2/bootstrap`、`/api/v2/graph` 等 200。
- 打包 `DocLib.exe --browser --no-browser --port 8898` 冒烟：`/api/v2/bootstrap`、`/`、`/app/main.js`（MIME）、`/api/v2/workspace` 均 200；产物 56.7 MB（未含数据）。
- ZIP：`dist-v2.0/DocLib-2.0.0-win64.zip`，33.1 MB，SHA256 `FB526E0501EF90DD8EA63015C4FEA47C9AE6795E692E176FC6BAFD6E9CB9F309`；无 `data/`。
- 未做：WebView2 原生窗口的自动点击回归（只做启动/加载冒烟）；PDF 原生预览视觉回归（无 PDF 样例）。

## 3. 手工 E2E（Playwright + Edge，1440×900）

- 图谱：28→36 节点（两科目）渲染；节点点击信息面板；局部图谱打开中央标签；树同步高亮。
- 阅读：Markdown 文档标题/正文/TOC；目录按钮；PDF 分支未测；引用片段定位与 CSS Highlight。
- AI：文档上下文只检索该文档（请求体 `context.kind=document`）；选中文字请求 `context.kind=selection` 且首条来源 `selection`；全部资料库 `context.kind=all`；历史会话恢复；引用点击回原文。
- 笔记：新建→自动保存→刷新恢复；反链 3 条；`[[doc]]`/`[[node]]` 预览链接；Markdown 导入；Word 问答导出。
- 导入：路径导入 Markdown 成功（新增 1/更新 0/失败 0）。
- 主题：深→浅→深，AI 374×874、左栏 268、三栏宽度不变；刷新后主题保持。
- 窄窗：1100 默认 AI 抽屉可开；920 左抽屉+AI 抽屉可开；`scrollWidth==innerWidth`。

## 4. 未解决 / 风险

- `qa_regress.py` 需要真实语料，仓库不含；不在 CI 伪造“21/21”。
- 审计 3 项见上，其中 `/api/backup` 空参 500 需在审计专用数据副本上复现定位；直接调用 demo 服务正常。
- 分屏/命令面板/未链接提及/标签/CodeMirror 6 未实现，按 P1 记录。
- 打包版未签名；首次运行可能触发 SmartScreen。
- 旧 `dist/DocLib` 未被覆盖；2.0 构建在独立 `dist-v2.0`。

## 5. 截图

`docs/v2/screenshots/01..13-*.png`；审计评分见 `VISUAL_AUDIT.md`。
