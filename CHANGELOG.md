# 更新记录

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