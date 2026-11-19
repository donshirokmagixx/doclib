# DocLib 2.0 · 后端与数据审计（只读）

> 范围：`DocLib\doclib\` 下 server.py、ai/(rag,gateway,vectors)、tree/search/importer/mindmap(_gen)/notes/citations/chunker/convert/readers/docx_reader/config/db/system/window 与 `migrations/*.sql`。基线 git `157bcbe`（工作区干净）。未运行程序、未迁移数据库。

## 1. Schema、迁移与 meta

分层：真值层 nodes/documents/node_documents、派生层 doc_chunks(+FTS)、审计层 op_log（0001_init.sql:2-3）。

| 表 | 关键列 / 索引 | 证据 |
|---|---|---|
| meta | key/value：library_version、seeded、schema_version | 0001:5-8 |
| nodes | parent_id(FK CASCADE)、path 物化路径、depth、search_scope CHECK(self/subtree/all)、sort_order、is_system、deleted_at；partial 索引 (parent_id)(path) WHERE deleted_at IS NULL | 0001:11-32 |
| documents | path_key 小写规范路径、file_hash、file_mtime、parse_status/parse_version、quality(_note)、cloud_allowed；ux_doc_path UNIQUE(path_key) WHERE deleted_at IS NULL、idx_doc_hash、idx_doc_quality | 0001:34-52, 0002:8-13 |
| node_documents | PK(node_id,document_id)、weight、note（业务代码从未写入，只留默认值） | 0001:54-62 |
| doc_chunks | UNIQUE(doc_id,ord)、heading_path、text、char_len、is_table | 0001:65-75 |
| chunk_fts | fts5 external content + 3 触发器，tokenize=trigram | 0001:78-95 |
| op_log | op/entity/payload/inverse；有 inverse 但无 undo | 0001:98-106 |
| node_associations | node↔doc 预留表（state 0候选/1采纳/2忽略/3钉住），全库无引用 | 0001:109-118 |
| ai_providers | role/is_default/free/price_in/price_out/key_ref（密钥不入库） | 0002:16-28, 0004:4-11 |
| conversations/messages/message_citations | conv.node_id 无外键；msg FK CASCADE；citation.doc_id 故意无 FK，存 snippet+text_hash，chunk_id 仅线索 | 0002:33-64, 0005:2-9 |
| ai_runs/ai_cache | 每次调用留痕；UNIQUE(task_type,cache_key) | 0003:5-31 |

软删除：删除=写 `deleted_at`，唯一索引带 `WHERE deleted_at IS NULL`（0001:51）；节点软删整棵子树，并把只挂在这些节点上的文档回收进「未分类」（tree.py:242-279）；`purge_*` 才物理删（tree.py:478-504, importer.py:329-342）。

迁移：`open_db()` 先建 `schema_migrations(version,name,applied_at)`，`glob("*.sql")` 排序、文件名前缀转 int 去重，逐个 `executescript` 后插版本行（db.py:61-84）；缺 meta 时写 `library_version=1`；**`schema_version` 硬编码 `"0001"`**（db.py:83，不随迁移前进）；`library_version` 递增供缓存失效（db.py:54-58）。

真实用法：documents↔node_documents 多对多，`mount_smart` 挂正式节点会摘掉「未分类」（importer.py:249-257），`set_doc_nodes` 全量替换（274-305）；chunk 只在 import 事务内整体重建，先删向量再删块（166-207）；message_citations 只存回答里实际出现的 `[n]`（rag.py:539-581）。瑕疵：`file_mtime` 单位不一致（relocated 写毫秒，import 写秒，importer.py:126 vs 181/191）；`parse_status` 注释 0/2/3 但从不写 0（0001:43）。

## 2. HTTP API 清单

仅监听 127.0.0.1（config.py:47-48），`APP_BUILD=2026-11-19-r16`（server.py:21）。**无鉴权、无令牌**，本地信任模型 + 三道来源校验：Host 白名单（server.py:60-72）、`Sec-Fetch-Site!=cross-site`（75-77）、POST 的 Origin 与 Host 同源（80-90）；POST 另须 `application/json` 且 ≤32MB（36-57）；GET 只查 Host+跨站（916-918），POST 全查（962-966）。响应统一 nosniff/DENY/no-referrer（890-892），异常回 `str(e)`（953-955,972-974）。

| 分组 | 路由 | 说明/证据 |
|---|---|---|
| 基础 | GET /api/health、/api/stats、/api/tree、/api/backups | health 含 build+prompt_version；stats 含 db_size、backups（111-131,185） |
| 树/检索 | GET /api/docs?node&scope、/api/search?q&node&scope | 文档列表 / 命中列表（133-144） |
| 节点 | POST /api/node/{create,rename,delete,reorder,move,indent,outdent} | 均 `{ok}`,错误在 error（627-686） |
| 文档 | GET /api/doc/<id>、/api/chunk/<id>；POST /api/doc/{mount,move,set_nodes,delete,restore,purge} | set_nodes 支持多挂载（173-183,425-431,698-742） |
| 导入 | POST /api/import {path|mode=folder/files} | 汇总 scanned/imported/updated/unchanged/failed/items/relocated（586-622） |
| 打开 | POST /api/open {doc_id|path} | 见 §4（554-584） |
| 回收站 | GET /api/recycle；POST /api/recycle/{restore,purge,purge_docs} | all=true 清空（188-190,688-768） |
| 会话 | GET /api/conv/list、/api/conv/<id>、/api/conv/detail/<id>、/api/conv/<id>/docx；POST /api/conv/{new,update,delete,export,export_batch} | update 可改 title/pinned/favorite/tags（844-865,803-832,922-947,483-551） |
| 导图 | GET /api/maps、/api/map/<name>；POST /api/map/{new,save,rename,delete,export} | 文件式存储（834-842,436-481） |
| AI | POST /api/ask；/api/ai/{providers,test,providers/default,toggle,delete,embed,runs}；POST /api/ai/embed/{index,clear} | ask 返回 sources/引用状态（217-233,245-264,359-423,793-801） |
| 运维 | GET /api/maintenance、/api/secrets；POST /api/backup、/api/seed、/api/rebuild | rebuild 按 PARSE_VERSION 重建（192-215,624-625,771-791） |
| **v1.1 rev** | GET /api/rev/{partitions,tree,docs,search}；POST /api/rev/{ask,import,mindmap/generate_from_docs} | 只增不改旧路由（146-169,266-356；CHANGELOG:24-26） |

坑：`/api/docs`、`/api/search` 未限定 GET，POST 也会命中（133,139）；`GET /api/conv/<id>` 只在路径恰好 3 段时匹配（852）。静态：非 /api 请求走 `_serve_static`，resolve 后须落在 STATIC 前缀内，否则回落 index.html（904-912）；/favicon.ico 204（919-921）。窗口模式先探测已运行实例，再 `start_server`+pywebview，失败走 MOTW 提示（window.py:57-96）。

## 3. 检索与问答链路

**scope/partition**（tree.py:213-239）：无 partition 时 `scope=all` 或 `node_id=None` 返回 `None`（=全库不限）；否则 `_scope_doc_ids`（self=本节点挂载，subtree=`path LIKE '前缀%'`）。带 partition：`scope=all`=分区全集；self/subtree=节点范围∩分区；节点不在分区 path 前缀内→空集（跨分区默认拒绝，231-232）。分区=一级且 is_system=0 的节点（122-135），`partition_of_node` 沿 parent 上溯（158-172）。search/docs 都靠该集合在内存过滤（search.py:148,220,287）。

**检索**（search.py:134-281）：切最多 8 词（23-33）；≥3 字走 FTS5 trigram bm25 前 300（155-161），<3 字（如「卷积」）退回 LIKE（164-172）；语义可选 bge 本地向量 k=50（174-191）；RRF k=60、kw .7/sem .3（193-201）；按文档聚合 top3×1000 + 标题命中 + 标题稀有度×60 + 语义 +8 + 命中词×5，再乘质量系数 `0.75+0.25q`（242-258）。

**RAG**（rag.py:384-613）：scope 归一（node→self，357-362）；有 conversation_id 时回读 node，显式换 node/分区就写回 conversations 并写 `op_log(scope_update/partition_update)`（398-443）；`scope!=all` 且无 node 直接拒绝（450-452）；追问把上一条 user 消息前 80 字拼进检索（454-464）；主路是**块级**混合检索 `_chunk_candidates`（225-340：同义词扩展、标题词切分、表格块、领域提示、变换名加减分），块级空才退文档级（469-481），再空报「没有检索到相关内容」（482-484）。

**prompt/模型**：系统提示词来自 `doclib/ai/prompts/qa_v3.txt`（要求只用片段、结论带 `[n]`、无片段不给编号），`PROMPT_VERSION="3"`，导入时加载（prompts.py:11-29；rag.py:26）。选型：provider_name→`load_provider`（默认=该 role 的 is_default，其次启用且免费优先，gateway.py:77-94）；OpenAI 兼容走 urllib、Ollama 走 `/api/chat`（256-279）；密钥取自 secrets 并做中文/空白校验（246-274）；每次调用写 ai_runs（216-228,316-324），成本按元/百万 token 折微元（50-52）；缓存键=问题+provider:model+提示词版本+每个 chunk 的 text hash（rag.py:29-36,491-499）。

**引用**：正则抽 `\[(\d+)\]` 并夹到 `1..len(chunks)`，只对被引用编号落库（rag.py:540-544,570-581；REV-102 去掉的正是「补前 3 条」）；快照=(doc_id,heading_path,snippet 前 80 字,全文 sha1)，chunk_id 仅调试（citations.py:26-61）；`resolve()` 同 heading_path 找同 hash→有效，否则首块 drifted=True，文档没了 found=False（64-105）。

**资料不足**：`insufficient=not use_idx`，即「回答里一个 [n] 都没有」，不是相关性阈值；回答照常返回并附 notice/`citation_status="none"`（rag.py:543-545,609-611）。检索错但模型硬编编号时无法识别。

**会话**：只按 id 定位，无 id 新建（旧「按标题合并」已移除，365-381）；首问前 24 字作标题（552-558）；历史只送最近 6 条、每条截 1500 字（503-513）。两套详情接口不一致：`/api/conv/detail/<id>` 自己拼引用并硬编码 `drifted:False`（server.py:817-826），`/api/conv/<id>` 走 `citations.resolve`（864）。

## 4. 导入、解析、打开

- 支持格式：`SUPPORTED_EXT`=docx/doc/txt/md/pptx/pdf/图片（readers.py:219-226）；server 单文件白名单 `{docx,doc,pdf,pptx,ppt,md,txt,markdown}`（server.py:327-331），与解析层不一致：`.ppt` 进 importer 的 OTHER 被跳过（importer.py:100-103）；`.mdown/.log/.csv` 与图片只能靠「选择文件夹」递归扫入（scan 不过滤扩展名，29-42）。
- 导入：ext 判定→stat→sha256→path_key 查重→同 hash 异地算 relocated 并改路径（89-133）→hash+PARSE_VERSION 都同才算 unchanged（135-145）→parse→chunk→quality→事务内重写 documents+doc_chunks（147-207）→规则挂载建议（49-86），`auto_mount` 需第一名≥第二名 1.35 倍且≥8 分（224-237）。`PARSE_VERSION=3`（versioning.py:15），`/api/rebuild` 据此重解析（importer.py:393-444）。
- docx：纯标准库 zipfile+ElementTree，读 styles.xml outlineLvl/样式名认标题、跳 TOC 段、表格行 `" | "` 拼接（docx_reader.py:26-123,126-171）。pdf：pypdf 抽字，单页<12 字符且 OCR 可用时渲染该页 OCR，OCR 上限 50 页、取前 500 页（readers.py:137-194；config.py:59-60）。pptx：直接读 `slideN.xml`，首段短文本当标题，生成「第 N 张幻灯片：标题」（99-133）。md/txt：编码嗅探 utf-8/gb18030/big5（37-51），md 去 front-matter/围栏、`#`→level、清内联（59-95）。
- OCR：Windows winrt OCR 优先、tesseract 兜底、都没有明确报错（ocr.py:26-50,130-146）；PDF 页渲染靠 pypdfium2（149-164）；汉字间空格还原（55-68）。`.doc`：先 LibreOffice headless 再 Word COM，缓存键含 PARSE_VERSION（convert.py:21-50,101-123）。
- 打开：`POST /api/open`，有 doc_id 直接取 `documents.file_path` 给 `system.open_document`（ShellExecuteW，不经 cmd，system.py:13-32）；只给 path 时必须落在 DATA_DIR 内或等于某条未删文档真实路径（server.py:564-583）。路径安全结论：导入接受任意本地绝对路径（本机信任模型），静态靠 resolve 前缀校验（904-912），无「允许根目录」概念。

## 5. 为 2.0 扩展什么、哪里有坑

前置约束：数据目录单点解析（`DOCLIB_DATA` → `dist/DocLib/data` → `APP_DIR/data`，config.py:21-37），一个进程只服务一个 DB，没有「多库/多工作区」概念。

**需新增**：① 图谱——`node_associations` 是 node↔doc 且从未写入（0001:109-118），无 node↔node/doc↔doc；建议 `edges(id,src_kind,src_id,dst_kind,dst_id,rel,weight,origin,state,created_at)`+唯一索引。② 笔记——`notes.py` 只导出 docx、无存储（1-19）；建议 `notes(id,title,markdown,node_id,created/updated/deleted_at)`+FTS+`note_links`。③ 文档级/选中文本——`doc_chunks` 无字符偏移/页号/坐标（0001:65-74），PDF 页号只是 heading「第 N 页」（readers.py:181）；需 `start_char,end_char,page,bbox,chunk_uid`，并让 messages/citations 记 `quote,start,end`。④ 多标签——无 workspace/label 表，分区=一级节点（tree.py:122-155），标签只有 `conversations.tags` 单串且 `/api/conv/update` 截 80 字（server.py:542）；`node_documents.weight/note` 空列可用（0001:57-58），建议 `workspaces`+`workspace_tabs`。

**冲突与坑**：① 范围三义——all 无 partition=全库、有 partition=分区；`scope=node` 被改写成 self（server.py:252-253；rag.py:357-362）；conversations.node_id 既当范围载体又被回写（rag.py:398-443），而 messages 无 scope/node/partition 列，**历史消息当时范围不可重建**。② 分区导入削平多标签：挂在分区外的文档被 `set_doc_nodes(did,[partition])` 收回（server.py:343-354），而它会删掉所有非系统挂载（importer.py:288-298）。③ 同名/同内容：title 只取 stem（importer.py:92）；按 file_hash 判重会把同内容不同路径合并成一条并改路径（118-133），两份同名讲义会丢一个挂载点。④ purge_node/purge_all_deleted 直接删 nodes、不做孤儿回收（tree.py:478-504，对比 delete_node 的 256-274）→ 文档在 scope=all 可见、节点里消失。⑤ 引用快照缺文档标题，doc_id 无外键（0002:55），文档 purge 后详情只能 `文档#id` 兜底（server.py:817-826）。⑥ 缓存键含 chunk hash 能防漂移，但 `[n]→chunk` 映射按本次 chunks 顺序临时重建（rag.py:570-591），「回答+快照」未原子绑定。⑦ 导图按文件名寻址，`safe_name` 去非法字符+截 60 字会撞名（mindmap.py:26-33），`create` 报错但 `save` 静默覆盖（96-102 vs 85-93），无 DB 索引。⑧ 会话 node_id 无外键，节点物理删后回读到悬空 id → 空范围、无提示。

## 6. 测试覆盖与空白

现有 5 个脚本式测试（无 pytest 依赖，均把 `DOCLIB_DATA` 指临时库）：`test_scope_isolation`（只按 id、范围写回+op_log、/api/ask 校验）、`test_partitions`（分区列表/跨分区拒绝/rev 路由/分区导入）、`test_citations`（被引才落库、无引用=资料不足、会话详情带分区、prompt_version）、`test_mindmap_gen`（规则回退/模型 JSON/空范围）、`test_notes`（docx 部件合法、勾选/摘录/提纲/合并/归章）；CI 见 CHANGELOG:13。

空白：① importer/readers/docx_reader/convert/ocr 零测试，docx/pdf/pptx/图片/`.doc` 全链路未验证；② HTTP 层只直调 `api_dispatch`，不真发请求，Host/Origin/CSRF/32MB/静态回落/`/api/open` 白名单全未覆盖；③ 迁移幂等与「半个迁移失败」无测试，`executescript` 无事务包裹（db.py:75）；④ rebuild、library_version 缓存失效、`citations.resolve` 的 drifted 分支无测试；⑤ gateway 错误码翻译/TLS 降级/超时无测试，ai_runs 只被间接使用；⑥ vectors/embedder 无语义检索测试；⑦ 无并发/WAL/长事务测试；⑧ 2.0 的图谱/笔记/多标签/文档级上下文**无任何基线**。

## 关键事实

1. 真值/派生/审计三层清晰，软删除贯彻到索引，引用按「快照+hash」而非 chunk_id 是正确设计（0001:51；citations.py:1-13）。
2. 迁移只靠文件名前缀与 schema_migrations，无事务、无校验和，`meta.schema_version` 永远停在 "0001"（db.py:75-83）。
3. 检索=FTS5 trigram+可选向量+RRF；问答块级优先、文档级兜底；「资料不足」=回答里没有 [n]（rag.py:543-545）。
4. v1.1 只新增 `/api/rev/*` 七个入口，不回改旧路由（CHANGELOG:24-26）。
5. 无鉴权，安全边界=仅本机 Host/Origin/跨站 + JSON + 体积 + 路径白名单（server.py:60-90）。
6. 四件新功能在现有 schema 里都无承载结构；`node_associations`、`node_documents.weight/note`、`documents.cloud_allowed`、`nodes.association_on/derived_version` 全是空预留（0001:23-24,46,57-58,109-118）。

## 未确认

1. 未运行程序/迁移：真实库的 schema_migrations 内容、0005 与 0002 重复创建 `idx_msg_conv`（0002:50 vs 0005:8-9）是否已按预期执行，无法确认。
2. embedder/sqlite-vec 在本机与打包版是否可用，代码里只是「可选」分支（search.py:174-191；vectors.py:13-32）。
3. 前端如何使用这些接口（是否传 scope=all+partition、是否依赖 drifted），不在本次范围。
4. 真实数据中是否已有孤儿文档、file_mtime 混写、同名导图，需查库定论。
5. secrets（DPAPI）、cli、motw 未审；server.py:1085-1093 有一段 `_report_running` 内不可达的重复 `_port_open` 代码（死代码，语义无影响但应清理）。

## 对 2.0 的含义

1. 先定 schema 再动 UI：图谱/笔记/多标签都需新表，必须同时确定「软删除+唯一索引」写法，否则重演 `ux_doc_path` 的恢复冲突。
2. 上下文四层拆开：工作区/会话/消息/范围分离，给 messages 加 `scope_node,partition_id,document_ids,quote,start,end`，否则文档级与选中文本上下文无法在历史里复现。
3. 引用契约升级：`message_citations` 补 doc_title/page/start/end 快照，并统一两套回读逻辑（server.py:817-826 vs 864）。
4. 多标签落在挂载层而非分区层：分区是单亲，标签应进 node_documents/新标签表，同时修掉 `/api/rev/import` 的「收回即清空」（server.py:343-354）。
5. 测试补序：先 importer/readers 冒烟 + HTTP 真请求 + 迁移幂等，再给新表加约束测试；2.0 的破坏面目前全在无测试区。
