# HANDOFF · DocLib 2.0 维护交接

> 交接对象：继续维护 DocLib 的开发者
> 仓库：https://github.com/donshirokmagixx/doclib
> 默认分支：`main`
> 当前源码基线：`64a27f0`（图谱实时物理增强）
> 最近 Release：https://github.com/donshirokmagixx/doclib/releases/tag/v2.0.0

## 1. 一句话

DocLib 是一个 **本地优先的 Windows AI 知识工作台**：资料库、真实关系图谱、文档阅读、Markdown 笔记/双链，以及带原文引用和上下文范围的 RAG 问答。数据默认只在本机，只有用户自己配置的模型请求会出网。

## 2. 接手前先读

按顺序读，不要先改代码：

1. `README.md`：功能、快速开始、测试命令、已知限制。
2. `docs/v2/PROGRESS.md`：Phase 0–6 完成情况与未完成项。
3. `docs/v2/TEST_REPORT.md`：真实测试、审计、打包结果。
4. `docs/v2/GRAPH_PHYSICS.md`：实时力导向图谱的选型、参数、降级与 WebView2 测试。
5. `docs/v2/ARCHITECTURE.md`、`docs/v2/DESIGN_SYSTEM.md`：数据/API/前端 token 约束。
6. `docs/v2/VISUAL_AUDIT.md`：视觉评分与已知 UI 缺口。

## 3. 环境

- 平台：Windows 10/11 x64
- Python：3.11（CI 同时测 3.12）
- 原生窗口：WebView2 Runtime（Windows 11 通常自带）
- 前端：原生 ES Modules，**无 Node/Vite 构建**
- 数据库：SQLite（WAL + FTS5 trigram）
- 打包：PyInstaller onedir
- 依赖：`requirements.txt`

```powershell
cd <repo>
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 4. 运行

```powershell
# 浏览器模式（开发最方便）
.venv\Scripts\python.exe -m doclib serve --no-browser --port 8765
# 打开 http://127.0.0.1:8765/

# 原生 WebView2 窗口
.venv\Scripts\python.exe run.py --window
```

**不要**使用 `dist/DocLib/data` 或任何真实用户库做自动化测试。测试统一使用临时 `DOCLIB_DATA`；源码测试脚本已各自创建临时目录。

## 5. 数据与密钥（最重要）

- 数据默认在 `data/`：`doclib.db`、`workspace.json`、`backups/`、`exports/`、`mindmaps/`、密钥文件。
- **禁止把 `data/`、数据库、`secrets.bin`、`secrets.portable.json`、API Key 提交到 GitHub。**
- 仓库没有真实用户资料；`data/` 已在 `.gitignore`。
- 新维护者若要使用 AI：设置 → AI 模型 → 新增 provider → 在“密钥”区保存自己的 Key；不要向任何人索取原 Key。
- 迁移：启动时事务执行 0001–0007；迁移前自动备份到 `data/backups/`；失败回滚。
- 打包前不要盲删 `dist/DocLib/data`；新的打包命令输出到独立 `dist-v2.0`。

## 6. 测试

```powershell
$env:PYTHONUTF8="1"
.venv\Scripts\python.exe tests\smoke.py
.venv\Scripts\python.exe tests\test_scope_isolation.py
.venv\Scripts\python.exe tests\test_partitions.py
.venv\Scripts\python.exe tests\test_citations.py
.venv\Scripts\python.exe tests\test_mindmap_gen.py
.venv\Scripts\python.exe tests\test_graph.py
.venv\Scripts\python.exe tests\test_reader.py
.venv\Scripts\python.exe tests\test_notebook.py
.venv\Scripts\python.exe tests\test_context.py
.venv\Scripts\python.exe tests\test_migrations_v2.py
.venv\Scripts\python.exe tests\test_workspace.py
.venv\Scripts\python.exe tests\test_http_v2.py
.venv\Scripts\python.exe tests\test_notes.py
```

当前状态：13/13 通过（Python 3.11 本机实测）。CI 在 `windows-latest` 上跑 Python 3.11/3.12 矩阵，工作流见 `.github/workflows/ci.yml`。

- `tests/qa_regress.py` 需要真实 `dist/DocLib/data` 语料，仓库不带真实资料，**不要在 CI 中伪造通过**。
- `scripts/audit_doclib.py` 可用 `DOCLIB_AUDIT_DATA` 指向临时 demo 库；完整审计会报告 58/60，剩余两项是 demo 数据前置条件。
- 前端改动至少跑 `node --check` 对 `doclib/web/static/app/*.js`，并用浏览器实际截图/拖动验证。

## 7. 代码地图

| 目录/文件 | 作用 |
|---|---|
| `doclib/web/server.py` | HTTP 服务、旧 API、静态资源、安全校验 |
| `doclib/web/api_v2.py` | v2 工作区/图谱/阅读/笔记/关系 API |
| `doclib/web/static/index.html` | 前端壳；加载 styles/app/vendor |
| `doclib/web/static/app/` | `main` `shell` `ai` `views` `workspace` `core` `graph-force` |
| `doclib/web/static/styles/` | tokens / base / layout / components / views |
| `doclib/web/static/vendor/` | Cytoscape/fcose/marked/DOMPurify，离线必需 |
| `doclib/graph.py` | 图谱投影（node/document/note + 五类边） |
| `doclib/reader.py` | 阅读器分页/TOC/Range/文件解析 |
| `doclib/notebook.py` `links.py` | 笔记/FTS/双链/反链/关系 |
| `doclib/context.py` `ai/rag.py` | 六种 AI 上下文与检索 |
| `doclib/migrations/0006*.sql` `0007*.sql` | 图谱上下文、笔记与双链 |
| `doclib/workspace.py` | workspace.json 原子持久化 |
| `tests/` `scripts/` | 隔离测试、demo、guard、审计 |
| `docs/v2/` | 计划/架构/设计/进度/测试/图谱物理/截图 |

## 8. 图谱实时物理（最近改动）

- 新增 `doclib/web/static/app/graph-force.js`；Cytoscape 只负责渲染，fCoSE 只负责初排。
- 拖动时：弹簧 + 斥力 + 弱中心/软半径环 + 阻尼 + alpha 衰减；松手后约 3–4 秒回稳。
- 不重跑 fCoSE、不自动 fit/缩放；切标签/关图停止 rAF；固定节点、位置持久化。
- 工具栏“物理参数”可调斥力/弹力/阻尼；默认值接近 Obsidian Graph。
- 大图：>260 节点网格斥力，>600 节点约 30fps，>1200 节点约 20fps。
- 回归重点：`docs/v2/GRAPH_PHYSICS.md`；拖动、固定、刷新位置、切标签清理、WebView2 实际拖动。

## 9. GitHub 协作约定

- `main` 分支已配置保护：禁止直接 push/force push/删除；PR + 至少 1 个 approval + CI 检查（`test (3.11)`、`test (3.12)`）通过。
- Owner 账号仍可应急 bypass；日常改动请走 `feat/*`、`fix/*` 分支和 PR。
- 维护者 `lamchinhvk` 的权限应为 **Maintain**（Collaborator），邀请接受后生效；若用户名有误请 owner 在 Settings → Collaborators 修正。
- PR 要求：说明改动、测试命令/结果、截图（UI）、风险；不要提交 `data/`、密钥、真实资料。
- 发布：GitHub Release tag + Windows ZIP 附件；源码不要塞 ZIP。

## 10. 发布流程

```powershell
# 构建（输出到独立目录，不覆盖旧 dist）
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist-v2.0 --workpath build-v2.0 DocLib.spec

# 组装 ZIP 后，在 GitHub 创建 Release 并上传 dist-v2.0\DocLib-2.0.0-win64.zip
```

- 当前 Release `v2.0.0` 的 ZIP SHA256：`3CCDD7B862B5FCD5B48FDE6F47D9EB40ADC044E86A389DF40485550D22B0A0AB`
- 升级版本时同步：`doclib/__init__.py`、两处 UI 版本文字、`README`、`CHANGELOG`、ZIP 名、Release notes。

## 11. 已知限制 / 下一步

- 分屏、命令面板、未链接提及、标签、CodeMirror 6 尚未实现（P1）。
- PDF 原生预览依赖 WebView2，尚无真实 PDF 视觉回归样例。
- 打包版不包含本地向量推理；`qa_regress` 需要真实语料。
- CI 目前覆盖 13 个 Python 测试，但前端 Playwright/WebView2 拖动测试仍是手工脚本。
- 打包未签名，首次运行可能触发 SmartScreen。
- 视觉审计剩余项见 `docs/v2/VISUAL_AUDIT.md`（图谱标签碰撞、状态栏字号、浅色层级等）。

## 12. 接手后的第一步

1. clone 仓库，建 `.venv`，跑完整 13 个测试。
2. 读 `PROGRESS`/`TEST_REPORT`，确认已知限制。
3. 从 Issue 或 roadmap 挑一个 P1；开 `feat/*` 分支。
4. 改动后跑对应测试 + 全量测试 + `node --check`，提 PR。
5. UI 改动附真实截图；不要只描述“应该可以”。

---

Owner：`donshirokmagixx`  
Maintainer：`lamchinhvk`（Maintain，待邀请接受）  
问题/阻塞：在 GitHub Issues 记录；涉及数据/密钥的问题不要贴到公开 Issue。
