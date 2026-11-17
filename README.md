# DocLib · 个人 Word 资料库

一个**纯本地运行**的个人知识库工具：导入 Word / PDF / PPT / Markdown / TXT，
自动建立知识树与全文索引；按节点范围检索；用大模型做带引用的问答；
把问答导出成 Word 笔记或按知识树归章的复习提纲；附带知识导图与词云。

> 当前版本：**V1.0.0**（内部构建 2026-11-15-r13）
> 学科示例：信号分析与处理（知识树可自行重建）

---

## 功能

- **多格式导入**：`.docx` `.doc` `.pdf` `.pptx` `.md` `.txt`；扫描 PDF 走 Windows OCR
- **知识树**：多级节点、拖拽挂载、一份文档挂多个节点、回收站
- **混合检索**：SQLite FTS5（trigram 中文）+ 本地向量（可选）RRF 融合；范围可选「本文档 / 子树 / 全部」
- **AI 问答**：多模型（DeepSeek / 智谱 GLM-4-Flash 免费 / 硅基流动 / 本地 Ollama）；
  回答带 `[n]` 引用，可点开原文；支持追问、会话历史（置顶/收藏/标签）、成本与耗时统计、答案缓存
- **导出 Word**：问答笔记 / 复习提纲（速览要点、分节提纲、公式速查表、易错清单、自测与提示、来源索引）；
  支持勾选问答、附原文摘录、多会话合并、按知识树归章（零依赖 OOXML 实现）
- **知识导图**：从知识树生成、节点/连线/画笔/文本框、缩放平移、折叠隐藏、词云（点词触发 AI 检索/联想）、PNG/SVG 导出
- **运维**：自动/手动备份、重建索引、回收站、密钥加密保存（Windows DPAPI）
- **安全**：仅监听 `127.0.0.1`；接口校验 JSON / Origin / Host / Sec-Fetch-Site；请求体上限；文件打开与导入白名单

## 快速开始（源码运行）

```bash
# 1) 安装依赖（核心 + 窗口）
pip install -r requirements.txt

# 2) 启动（自动打开浏览器）
python -m doclib serve

# 或原生窗口模式
python run.py --window
```

首次启动会在项目根生成 `data/`（数据库、备份、导出、导图）。
默认知识树是空的，需要自己建节点并导入资料。

### 配置 AI（可选）

程序不带任何密钥。到「设置」：

1. **② 密钥**：保存 API Key（名称随意，例如 `zhipu`）
2. **③ AI 模型**：新增配置，填接口地址 / 模型名 / 密钥名（键名），勾选“免费/启用/设为默认”
   - 免费：智谱 `https://open.bigmodel.cn/api/paas/v4` + `glm-4-flash`
   - 付费：DeepSeek `https://api.deepseek.com/v1` + `deepseek-chat`
   - 本地：Ollama `http://127.0.0.1:11434/v1` + 自选模型

## 打包成 exe（Windows）

```bash
pip install pyinstaller pypdf pypdfium2 chardet pillow pythonnet pywebview
python -m PyInstaller --noconfirm DocLib.spec
```

产物在 `dist/DocLib/`。注意：

- `DocLib.spec` 的 onedir 构建会清空 `dist/DocLib`；请先备份 `dist/DocLib/data`（项目自带 `打包.bat` 已处理）
- 窗口层依赖 pythonnet / WebView2 Runtime
- 从网上下载/解压的包会带 Windows「来自网络」标记（MOTW），可能导致窗口层 .NET 组件加载失败；
  程序启动时会自动清除自身目录的标记，另附 `解除锁定.bat` 手动处理

## 测试

```bash
python tests\smoke.py            # 冒烟
python tests\qa_regress.py       # 检索回归（需要 data/ 中有资料）
python tests\test_notes.py       # 导出 Word 自测
python tests\eval\autoeval.py   # 自动出题评测
```

## 数据与隐私

- 资料索引、问答记录、导图、导出文件全部保存在本机 `data/`，不上传云端
- 只有「问 AI」时，与问题相关的资料片段会发送给你配置的模型服务商
- API 密钥默认用 Windows DPAPI 加密保存（`data/secrets.bin`），换电脑需重填
- 请勿把带个人数据的 `data/` 提交到版本库（`.gitignore` 已忽略）

## 已知限制

- 打包版未内置本地向量模型（语义检索仅源码版可用）
- 复习提纲是规则抽取，质量取决于原答案；暂不含自动目录域与术语表
- 单用户、单实例、无云同步
- 扫描件 OCR 依赖系统语言包，识别率受清晰度影响

## 目录结构

```
doclib/            核心包（导入/解析、检索、问答、导出、导图、Web 服务）
  web/static/      单页前端（index.html / mindmap.html）
  migrations/      SQLite 迁移脚本
tests/             冒烟、回归、导出自测、评测脚本
run.py             入口（窗口 / 浏览器）
DocLib.spec        PyInstaller 配置
start.bat          源码版启动（Windows）
打包.bat           打包脚本（保护 data）
```

## License

MIT（见 [LICENSE](LICENSE)）。
