## V2.0.0（2026-11-19，v2.0-dev）

Obsidian 式 AI 知识工作台升级：

- 统一三栏工作区：左侧资料库树、中央多标签、右侧固定完整高度 AI 伴学；浅/深主题仅改变 token，不改变尺寸/布局
- 真正的知识图谱：`/api/v2/graph`、节点/资料/笔记实体、层级/挂载/手工/AI/wikilink 边、全局/局部、过滤、局部图谱中央标签、树联动
- 文档阅读器：`/api/v2/reader|raw|file`、TOC、分页、Markdown/TXT、PDF iframe + 解析文本回退、Range、引用定位高亮、反向链接
- AI 上下文：`partition | all | node | document | note | selection` 六种范围、实际范围可见、`qa_v4` / `PROMPT_VERSION=4`、选文/笔记来源、消息级 context、引用回跳
- 笔记与双链：`0007_notes_links`、SQLite Markdown 笔记、FTS、自动保存/冲突、`[[doc|node|note]]` 稳定 ID、反链、Markdown 导入导出
- 迁移与持久化：`0006_graph_context`、事务迁移 + 迁移前备份 + 失败回滚、`schema_version=0007`、`workspace.json` 原子持久化/损坏回退
- 旧功能保留：分区/全部科目、导入、搜索、模型/密钥、Word 问答导出、导图嵌入、备份/回收站/重建索引、安全校验
- 安全：CSP、XFO SAMEORIGIN（PDF 需要）、Host/Origin/JSON 校验、Range、静态 404/MIME
- 图谱交互修正：层级/挂载/手工/wikilink/AI 连边常显（不再只在 hover 时出现）；滚轮缩放灵敏度 0.18→0.52；节点拖动 1.3× 跟手，仍以抓取点为锚，拖动结束位置正常保存
- 测试：13 个 Python 测试全过（含 context/migrations/workspace/http_v2）；Playwright E2E 覆盖图谱/阅读/AI/选文/引用/笔记/导入/主题/窄窗
- 文档：`docs/v2/PLAN|DESIGN_SYSTEM|ARCHITECTURE|PROGRESS|DECISIONS`、截图矩阵、第三方许可



- 导图导出落盘：PNG/SVG 统一保存到 `data/mindmaps/`，界面提示完整路径（不再依赖浏览器下载目录）
- 生成导图可选择节点：默认全选，勾父带子、取消同理；只对选中节点布局
- 右键菜单连续调参：字号/颜色/形状修改后菜单不关闭；多选节点批量应用
- 词云菜单：字号与颜色可连续调整
- 手册更新为 `UserNotesV1.1.1.docx`（版本标识）
- 便携包命名：`MySoftWare_Vision1_1_1`

## V1.1.1（2026-11-18，补丁）

- 修复 Python 3.10/3.11 下的语法错误：`gateway.py` 的 f-string 同引号嵌套（3.12+ 才支持）
- 新增 GitHub Actions CI（Windows，Python 3.11/3.12：冒烟、导出、隔离、分区、引用、导图）
- 仓库完善：README 徽章与界面预览、SECURITY.md、Release 源码包
- 说明：V1.1.0 的 wheel/源码在 3.11 下会 ImportError，请使用 V1.1.1

﻿# 更新记录

## V1.1.0（2026-11-18，内部构建 r15）

在 V1.0.0 基础上完成第二版第一批（REV-103/101/102/104/P1）：

- 会话隔离：会话只按 id 定位，不再按标题合并；`/api/ask` 校验范围；换节点/分区写回并在 `op_log` 留痕
- 科目分区：一级节点=分区；新增 `/api/rev/{partitions,tree,docs,search,ask,import}`；树/资料/检索/问答按分区过滤；导入可限制在分区内
- 引用真实：去掉"无引用自动补前 3 条"；没有 `[n]` 时标「资料不足」且不伪造来源；会话详情带分区
- 资料导图：`POST /api/rev/mindmap/generate_from_docs`，模型输出 JSON 树（失败回退规则版），节点带 `sources`，导图 `version=2`
- 提示词版本化：提示词迁到 `doclib/ai/prompts/qa_v3.txt`（`PROMPT_VERSION=3`）；`ai_runs.prompt_digest` 记为 `p3:<sha16>`
- 体验/修复：资料导图改为同窗口打开（`?map=`）；MOTW 启动自愈；打包包含提示词目录
- 测试：新增 `test_scope_isolation.py` / `test_partitions.py` / `test_citations.py` / `test_mindmap_gen.py`；冒烟、检索回归 21/21、导出 7 组、审计 60/60
- 仓库修复：`.gitignore` 的 `secrets*` 曾把源码 `doclib/secrets.py` 误排除，已改为 `data/secrets*` 并补回该模块
- 检索修复：补「时域/频域/对应关系」同义词，无语义的打包版也能通过 qa07（关键词版 21/21）

## V1.0.0（2026-11，内部构建 r13）

首个公开版本，包含：

- 多格式导入：Word / PDF / PPTX / Markdown / TXT；扫描 PDF 走 Windows OCR
- 知识树：多级节点、拖拽挂载、多节点、回收站
- 混合检索：FTS5 trigram + 本地向量（可选）RRF 融合；范围可选
- AI 问答：多模型、引用可点、追问、会话历史、成本统计、缓存
- Word 导出：问答笔记 / 复习提纲（速览、分节、公式表、易错、自测、来源）；勾选、摘录、合并、按知识树归章
- 知识导图：树生成、节点/连线/画笔、折叠隐藏、词云、PNG/SVG
- 运维：自动/手动备份、重建索引、密钥加密（DPAPI）
- 安全：仅本机监听；JSON/Origin/Host/跨站校验；路径与类型白名单；请求体上限
- 兼容：启动时自动清除 Windows「来自网络」标记（MOTW），附 解除锁定.bat

## 内部迭代（r7–r13）

- r7：零依赖 OOXML 导出 Word
- r8：勾选问答 + 片段摘录
- r9：复习提纲版式 + 批量合并
- r10：按知识树归章
- r11：跨站/来源/路径安全加固
- r12：路由去重、数据收归、窗口为默认
- r13：MOTW 自愈与解除锁定脚本