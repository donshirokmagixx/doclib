# DocLib · 个人 Word 资料库

> 当前版本 **v1.1.0（build 2026-11-18-r15）**
> 学科示例：信号分析与处理
> 定位：纯本地、单机、零外网依赖（除调用你自己配置的 AI 模型外），数据全部留在本机。

---

## 一、它能做什么

| 能力 | 说明 |
|---|---|
| 多格式导入 | `.docx/.doc/.pdf/.pptx/.md/.txt` + 图片；PDF 无文字层自动走 Windows OCR |
| 知识树 / 科目分区 | 一级节点 = 科目分区；按分区过滤树、文档、检索与问答 |
| 混合检索 | SQLite FTS5 trigram + LIKE +（源码版）本地向量，RRF 融合；标题/同义词/表格/领域词加权重排 |
| AI 问答 | 引用必须来自原文片段（无引用会标"资料不足"，不伪造出处）；支持追问、会话历史、成本/缓存显示 |
| 会话隔离 | 会话只按 id 定位；范围/分区随会话保存；切会话恢复历史与分区 |
| 知识导图 | 手工编辑/画笔/词云/PNG·SVG；**按选定资料生成**（模型结构化，失败回退规则版），节点带来源 |
| Word 导出 | 问答笔记 / 复习提纲；勾选、附摘录、合并导出、按知识树归章 |
| 运维 | 自动/手动备份、重建索引、回收站、密钥管理（DPAPI）、运行时自检 |
| 安全 | 仅监听 127.0.0.1；JSON+Origin+Host+Sec-Fetch-Site 校验；路径/类型白名单；请求体上限；安全响应头 |
| 打包 | PyInstaller onedir；启动时自动清除「来自网络」标记（MOTW），并附 `解除锁定.bat` |

## 二、快速开始

### 1. 直接运行（推荐，无需 Python）

```
双击 dist\DocLib\DocLib.exe
```

- 默认打开**独立窗口**（pywebview + WebView2）；关窗即退出
- 需要浏览器模式时：`DocLib.exe --browser`
- 数据目录：`dist\DocLib\data\`（数据库、备份、导出、导图、密钥都在这里，可整体拷走）

> 从网上下载/解压后如果窗口打不开：先双击 `解除锁定.bat`（或右键文件夹 → 属性 → 解除锁定）。
> 现象是"浏览器能开、窗口不行"，原因是文件带 Zone.Identifier，.NET 组件拒绝加载。

### 2. 源码运行（开发用）

```bat
start.bat
:: 或
python -m doclib serve --no-browser --port 8765
```

打开 `http://127.0.0.1:8765/`。数据默认读 `dist\DocLib\data`（唯一正本）；测试请用 `DOCLIB_DATA=<临时目录>`。

## 三、首次配置 AI

1. 顶部「设置」→「② 密钥」：填服务商 API Key（键名如 `deepseek`），保存后只显示掩码
2. 「③ AI 模型配置」：填名称 / base_url / model / key_ref，勾选启用并设为默认
3. 顶部下拉可随时切换模型

常用配置：

| 服务 | base_url | model |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 智谱（免费） | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | 按控制台填写 |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` 等 |

## 四、测试与质量基线

```bat
python tests\smoke.py
python tests\qa_regress.py          :: 21/21
python tests\test_notes.py          :: 7 组
python tests\test_scope_isolation.py
python tests\test_partitions.py
python tests\test_citations.py
python tests\test_mindmap_gen.py
python scripts\audit_doclib.py      :: 60/60（接口 + 安全）
```

测试必须用临时库，避免污染正本：

```bat
set DOCLIB_DATA=D:\tmp\doclib-test
copy dist\DocLib\data\doclib.db %DOCLIB_DATA%\doclib.db
```

## 五、目录结构

```
doclib/
  web/server.py        本地 HTTP 服务（路由/安全校验）
  web/static/          index.html（主界面）、mindmap.html（导图画布）
  ai/rag.py            检索 + 问答 + 引用
  ai/gateway.py        OpenAI 兼容网关（统一错误、ai_runs 记录）
  ai/prompts/          提示词文件（qa_v3.txt，版本化）
  search.py            混合检索
  tree.py              知识树 / 科目分区 / 范围求解
  mindmap.py           导图库（data/mindmaps/*.json）
  mindmap_gen.py       资料 → 导图生成
  notes.py             Word 导出（零依赖 OOXML）
  importer.py          多格式导入 / 挂载
  config.py            数据目录与端口（DOCLIB_DATA / DOCLIB_PORT）
tests/                 冒烟、检索回归、导出、隔离、分区、引用、导图
scripts/audit_doclib.py 接口与安全审计
```

## 六、数据与隐私

- 全部数据存本地 `data\doclib.db` + `data\mindmaps\*.json` + `data\exports\*.docx`
- 密钥用 Windows DPAPI 加密（`data\secrets.bin`），换电脑需重新填一次
- 只有点击「提问」时，才把检索到的相关片段发给你配置的模型服务商；不调用时完全离线
- 服务只监听 `127.0.0.1`，局域网其他设备默认无法访问
- **本仓库不包含**任何 `data/`、`dist/`、备份、密钥或导出的个人资料（见 `.gitignore`）

## 七、打包与分发

```bat
打包.bat
```

- 产物 `dist\DocLib\`（onedir，约 80 MB）可整体拷贝到 U 盘/别的电脑
- 打包会清空 `dist\DocLib`，脚本会自动备份并还原 `data`
- 分发建议用 zip，并保留 `解除锁定.bat`
- 干净分发包：空白库、无 `secrets.bin`，不要让个人包外发

## 八、已知限制

- 打包版不含本地语义检索（无 onnxruntime/numpy/sqlite-vec），走关键词 + 标题加权
- 提纲为规则抽取（无 TOC 域 / OMML 公式），术语表/对照表待补
- 单用户、单实例；无登录体系（本机信任模型）
- 真实问句召回约 82%（66 条评测集），仍在校准

## 九、许可

个人学习/自用项目，暂未声明开源许可；如需引用请先联系作者。
