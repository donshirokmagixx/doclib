# DocLib 运行时与交付审计（v1.1.2 / build 2026-11-19-r16）

审计基线：git 干净 `main` @157bcbe（`git status --short` 为空）；全程只读 + 临时库实跑，未打包、未装依赖、未迁移/写真实 data。本机 `python`=3.11.9，`dist`、`data` 均不存在。

## 1 启动链路

- 分流在 `run.py:62-70`：exe 名为 `doclib.exe/doclibw.exe` 且无参数 → 窗口；`--browser` 强制浏览器；源码 `python run.py` 默认浏览器，`--window` 才开窗（`run.py:1-14`）。注意带任何参数（如 `--port`）即回浏览器模式。
- 窗口：`run.py:69-81` 先 `_hide_console()`，再 `motw.unblock_install()`，最后 `doclib/window.py:57`。`window.py:61-70` 用 `live_instance()` 判重，有实例则 `FindWindowW(title)` 置前（依赖窗口标题，被页面改写会失配，只剩打印 URL）；否则 `start_server(strict_port=False)`（`window.py:72`）→ `webview.create_window`+`start`（83-86），关窗 `finally` 停服务（91-95）。
- 服务：`server.py:1125-1160` 清理死进程 runtime.json → 选端口 → `db.open_db()+seed.seed()` → `system.backup()` → 写 runtime.json → 后台线程 `serve_forever`。浏览器 `run()`（1175-1244）同构，另加 `DOCLIB_ALLOW_MULTI` 开关与 0.8s 后自动开浏览器（1189-1194、1236）。
- 单实例：`runtime.json` 在 DATA_DIR（`server.py:977/994-1003`：pid/port/host/url/build/started_at）；`live_instance`（1035-1055）校验 PID 存活 + `/api/health` 的 db 路径一致；`clear_runtime` 只删自己 PID（1006-1013）。无文件锁 → 先查后建存在同时双击双实例的竞态；window 路径不认 `DOCLIB_ALLOW_MULTI`。
- 端口：HOST=127.0.0.1（`config.py:47`）；默认 8765，`DOCLIB_PORT` 可覆盖（48）；`--port`；非 strict 时 `pick_free_port` 试 8765..8774，全占则交系统分配（`server.py:1058-1073、1203`）。`--strict-port` 只在浏览器/CLI 生效，window 永远传 `strict_port=False`（`window.py:72`），故 `--window --strict-port` 无效。
- 数据目录：`config.py:21-37` 优先级 `DOCLIB_DATA` → 冻结版 `exe同级\data` → 源码版若 `dist\DocLib\data\doclib.db` 存在则用它 → 否则 `DocLib\data`。runtime.json、backups、converted、exports、mindmaps、secrets 全在 DATA_DIR（40-45）。本机实测 `DATA_DIR=...\DocLib\data`。打包 exe 在别处运行时不读 dist 数据，只认同级 data。
- MOTW：仅窗口路径、导入 webview 前调用（`run.py:71-79`）；`motw.py:45-68` 递归删除 exe 目录下各文件 `:Zone.Identifier` ADS，失败只计数不报错，`verify_clean` 复核（71-84）。带 ZoneId=3 时 .NET 拒绝加载 Python.Runtime.dll，正是“浏览器能开、窗口不行”的根因；浏览器模式不做。
- 辅助脚本：`start.bat:14-33` 依次找 Anaconda/Python313..310/PATH（排除 WindowsApps），`start.bat:50` 跑 `-m doclib serve`（浏览器模式），处理退出码 3/4（53-67）；`诊断.bat:47` 检查的是 `data\doclib.db`，与 README:61 的 dist 正本不一致，会误报“不存在”；`诊断.bat:57/61` 的 doctor/tree 会打开并可能创建真实库。

## 2 PyInstaller 打包

- `DocLib.spec:13-19` datas：migrations、web/static、ai/prompts 三项 + pypdfium2/winrt 数据；`21-37` hiddenimports：pypdf、chardet、PIL、pypdfium2、winrt 全子模块、webview.winforms、clr_loader、pythonnet、bottle、proxy_tools、cffi；`40-52` binaries 收 pypdfium2_raw/winrt 及 webview/pythonnet/clr_loader/bottle/proxy_tools；`58-66` excludes 去 tkinter/科学栈/numpy/onnxruntime/sqlite_vec/httpx/keyring/rapidfuzz → 打包版无语义检索，与 README:139 一致。
- 资源路径成立：冻结时 `RES_DIR=_MEIPASS`（`config.py:14-16`），与 spec dest、`MIGRATIONS_DIR/STATIC_DIR`（44-45）、提示词候选（`prompts.py:14-18`）一致；data 放在 exe 同级便于整目录搬走（`config.py:4-7`）。
- spec 瑕疵：`38` 的 `_extra_hidden` 无来源，恒空；两个 EXE 都 `console=True`（87、94）与注释“无控制台窗口”（90）不符，靠 `run.py:34-46` 运行时隐藏控制台；winrt 依赖是拆分的 `winrt-Windows.*`，`collect_submodules("winrt")` 是否收全、WebView2 的 .NET DLL 是否被 `collect_data_files("webview")` 收到，均需打包后实测（本机无 PyInstaller）。
- `打包.bat`（UTF-8 但多处中文被替换为 `?`，严格 UTF-8 解码失败，命令行本身仍可执行）：`12-37` 找 Python 并**自动装最新 PyInstaller**（未锁版本）；`39-47` 把 `dist\DocLib\data` move 到 `_pkgdata_tmp`（不检查 move 成败）；`50` `--noconfirm` 打包（会清空 dist\DocLib）；`51-61` 失败还原；`63-74` 成功还原，或从源码 `data` robocopy（`/XD models`）。
- **可能破坏用户 data**：①程序未关、doclib.db 被锁时 move 失败但脚本继续，`--noconfirm` 直接删掉 dist\DocLib，个人库丢失；②还原时先 `rd /s /q dist\DocLib\data` 再 move，move 失败则数据只剩 `_pkgdata_tmp`；③上次中断残留的 `_pkgdata_tmp` 会在下次 `42` 被静默删除；④从源码 `data` 复制会把 secrets.bin/个人库带进“发布包”；⑤`_pkgdata_tmp` 不在 .gitignore（`git check-ignore` 验证：NOT ignored），中断后个人数据裸露在仓库根，易被误提交。
- 分发注意：仓库缺 `解除锁定.bat`、`使用说明.txt`（实测 MISSING），但 `README:134`、`window.py:40`、`同步到U盘.bat:30-32` 都依赖；`docs/UserNotesV1.1.1.docx` 在 docs/ 而脚本从 dist 根复制（32），不会进包；`同步到U盘.bat:8-34` 目标目录名仍是 `MySoftWare_Vision1_1_1`（当前 v1.1.2），只同步 exe/_internal/*.bat/说明书而保留 U 盘 data（设计正确）。另需：整目录分发、干净包去 secrets、WebView2 Runtime 前置、未签名 exe 的 SmartScreen。

## 3 测试/审计脚本

- `tests/smoke.py:15-16` 自建 TMP，无第三方依赖；实测 **exit=0**，全部通过。
- `test_scope_isolation.py:25-26`、`test_partitions.py:17-18`、`test_citations.py:12-13`、`test_mindmap_gen.py:13-14` 均先设 `DOCLIB_DATA=TMP` 并删库，假模型（monkeypatch `gateway.chat`）；实测**四个全部 exit=0**，且跑后 `data/dist` 仍不存在。
- `test_notes.py:56` 未设 DOCLIB_DATA，直接打开真实库；②③⑤⑥ 组依赖真实会话，空库/CI 下跳过。`ci.yml:22` 用空 `.ci-data`，所以 CI 实际只跑 ①⑧，README:83“7 组”在 CI 不成立。
- `qa_regress.py:62` 读真实库，21 条用例（yaml 实测 21），无资料全 FAIL；未跑。
- `tests/eval/autoeval.py:94` 读真实库，`--md` 才写文件；`llm_questions.py:21、125-127` 读真实库+联网模型并**覆盖已入库的** `tests/eval/llm_questions.jsonl`（未被 .gitignore 覆盖）；均未跑。
- `scripts/audit_doclib.py:71-80` 从 `dist\DocLib\data` 复制库、`22/83-85` 起 8795 端口、`320-325` 向仓库根写 `审计报告_接口与安全.json`（已在 .gitignore:45）。`rec()` 调用点实测 62 处（另有 1 个定义），与 README/规划“60/60”不符；dist 缺失时空库开跑，stats/providers/search 等必 FAIL，基线不可复现。
- 依赖：pypdf/chardet/pypdfium2/winrt 全是函数内懒导入（`readers.py:45`、`ocr.py:151`、`db.py:24`、`embedder.py:74`），故上述 5 个可跑脚本**无需第三方包**；代价是 PDF/OCR/语义检索不可用（`system.health` 会如实报 false）。

## 4 WebView2 兼容

现状前端为单文件经典脚本（`index.html:350`、`mindmap.html:175` 内联 `<script>`），无 module/importmap/WebSocket/EventSource/WebGL；用 async/await、fetch（`index.html:353`）、localStorage（`index.html:1618-1637/1716`，`mindmap.html:710/730/1624/1831-1878`）、Canvas 2D 仅做 SVG→PNG（`mindmap.html:1554-1557`）、Blob 下载（1521-1524）；无 CDN/远程字体。

本机 WebView2 Runtime **157.0.4341.60**（注册表），Win11 26200；pywebview/pythonnet 未装（`pip show` 全 NOT INSTALLED），`window.available()`=False，窗口模式本机不可跑。按 pywebview 官方安装文档：Windows 需 pythonnet，.NET 6 Desktop（否则 4.6.2）+ WebView2 Runtime。

| 能力 | 判断（按 Chromium 基线，未在本机 WebView2 实测） | 最低内核 |
|---|---|---|
| ES modules | 支持；但 `.mjs` 本机 MIME=text/plain（服务端只拼 charset 不改 MIME）会被拒 | 61 |
| fetch | 支持（`index.html:353`） | 42 |
| WebSocket | 浏览器支持，**服务端不支持**：BaseHTTPRequestHandler 无升级，`_send` 一次写全+Content-Length（`server.py:880-902`），SSE/流式也做不了 | — |
| PDF | 未内嵌，`/api/open` 交 ShellExecuteW（`server.py:554-563`）；WebView2 自带阅读器未启用 | — |
| Canvas/WebGL | 2D 在用，WebGL 未用，WebView2 两代均支持 | 1/10 |
| localStorage | 支持，但 origin 含端口：8765→8766 即丢 UI 偏好，且不在 data/、不随包迁移 | 4 |
| ES2022 | 支持（top-level await 89、`.at` 92、`Object.hasOwn`/static block 93-94） | 94 |
| CSS 容器查询 | 支持（`@container`/`:has()` 105、`dvh` 108、`color-mix` 111、subgrid 117） | 105-117 |

结论：当前 UI 的真实门槛只是“有 Evergreen WebView2”（Chromium 88+）；若 2.0 用满上表现代特性，建议声明 **Chromium ≥117**，本机 157 富余。Win10 无 WebView2 的机器窗口必失败，而 `window.py:33-44` 的提示只讲 MOTW，未提示缺 Runtime。

## 5 2.0 前端工程化

- 无构建（现状/原生 ESM）：一条 spec datas 覆盖整个 static 目录，源码与冻结路径都成立，离线天然成立；代价是 87KB/84KB 单文件、无打包压缩、多面板与图谱状态难维护。
- Vite/框架：build 输出到 `doclib/web/static/`（或 spec 加一条 datas 指向 frontend/dist）即可，PyInstaller 不分析 JS；多页需把 index.html 与 mindmap.html 都列入 `rollupOptions.input`；base 用 `/`；离线前提是不引 CDN/远程字体（现状无外链）。
- 硬约束：①`server.py:912` 一次性 `read_bytes`，不支持 Range → 内嵌 PDF.js/大文件预览要改服务端；②`X-Frame-Options: DENY`（891）会拒绝同源 iframe/内嵌标签；③MIME 依赖 Windows 注册表，`.mjs`/`.woff2` 实测 text/plain/None，必须显式 MIME 表；④缺失路径回退 index.html（907-908），SPA 可路由但 hashed 资源 404 也返回 200 HTML；⑤每条响应 `Cache-Control: no-store`（889），配合 hashed 资源等于每次全量重取；⑥`打包.bat`/CI 都不跑 npm build，忘构建就打包旧页面；CI 无 Node 步骤。
- 建议：先加固静态层（MIME 表、真 404、Range、按路径 XFO、可选缓存与 gzip），再决定是否引入 Vite；若 2.0 只做交互升级，可先“原生 ESM + 模块拆分”过渡，避免 Node 进入发布链。

## 6 基线命令与可执行性

```bat
python tests\smoke.py                      :: 可跑，实测通过
python tests\test_scope_isolation.py       :: 可跑，实测通过
python tests\test_partitions.py            :: 可跑，实测通过
python tests\test_citations.py             :: 可跑，实测通过
python tests\test_mindmap_gen.py           :: 可跑，实测通过
python tests\test_notes.py                 :: 会建真实库，未跑；CI 中多数用例跳过
python tests\qa_regress.py                 :: 需正本资料，未跑；21 条
python scripts\audit_doclib.py             :: 需 dist 数据+写报告，未跑
python tests\eval\autoeval.py              :: 需正本资料，未跑
python tests\eval\llm_questions.py --reuse :: 需正本+API，未跑
python -m doclib serve / run.py --window   :: 前者会建库；后者缺 pywebview，不可跑
python -m PyInstaller DocLib.spec          :: 缺 PyInstaller，不可跑
```

环境：Python 3.11.9（另注册 3.12.15/3.13/3.14），无 Anaconda；103 个包中相关仅 pillow 12.0.0、numpy 1.26.4、onnxruntime 1.23.2、tokenizers 0.22.1、pytest 8.3.5；pypdf、pypdfium2、chardet、pywebview、pythonnet、PyInstaller、winrt-*、sqlite-vec 全部缺失。`dist`、`data` 不存在，`DocLib\data` 若被创建即会与将来的正本目录混淆。

## 关键事实

1. 窗口是 exe 无参数默认，浏览器是 `--browser`/源码默认；`--port` 等参数会把 exe 拉回浏览器模式（`run.py:62-70`）。
2. 单实例靠 DATA_DIR 的 runtime.json + PID + `/api/health` db 比对，无锁；端口会自动避让，但 window 忽略 `--strict-port`。
3. 冻结版数据只认 exe 同级 `data`；源码版优先 `dist\DocLib\data`（存在 doclib.db 时）；`DOCLIB_DATA` 优先级最高且会把 runtime.json 一起搬走。
4. MOTW 自愈只在窗口启动、webview 导入前执行，失败静默；浏览器模式不处理。
5. 打包脚本的 data 备份是“move + 不校验”，程序未关时可能被 `--noconfirm` 清空；`_pkgdata_tmp` 未纳入 .gitignore。
6. 5 个测试可在本机无第三方依赖跑通；qa_regress/audit/test_notes/eval 依赖正本或 dist 数据，当前不可复现 21/21、60/60。
7. 服务端无 WebSocket/SSE/Range，MIME 依赖系统注册表，且全局 `X-Frame-Options: DENY`、`no-store`。
8. 本机 WebView2 为 157，pywebview/pythonnet/PyInstaller 均未安装，窗口与打包均不可验证。

## 未确认

- 打包产物大小、winrt OCR 与 WebView2 .NET DLL 是否收全、DocLibW 无控制台的实际观感：本机无 PyInstaller/dist，全部未实测。
- WebView2 用户数据目录（localStorage/缓存）落在何处、pywebview 是否设置 `storage_path`：未装依赖、未运行，无法确认；只能确认 origin 含端口。
- 双实例竞态、move 失败的具体报错与数据残留形态：仅由代码推断，未做破坏性复现（任务禁止）。
- `qa_regress` 21/21、audit 60/60 的可复现性：缺少正本库与 dist 数据，未跑；脚本内 rec() 62 个调用点与 60 的差值未逐项核对。
- WebView2 各版本对 PDF 内嵌与 GPU/WebGL 的实际表现：未运行，按 Chromium 文档推断。

## 对 2.0 的含义

1. 前端选型前先修服务端静态层（MIME 表、404、Range、按路径 XFO、缓存策略），否则 Vite/PDF 预览会踩 MIME 与 iframe 两个硬坑。
2. localStorage 不能承载工作区状态：端口漂移、换浏览器/WebView2、换机器都会丢；2.0 的工作区/标签/面板布局必须落 `data/`（如 `data/ui_state.json`）并纳入备份。
3. 若要实时（导入进度、AI 流式），必须给 server.py 加 SSE/WebSocket 与流式响应；当前 `_send` 一次性写死 Content-Length。
4. 打包链先解决 data 安全：move 前检查进程/失败即中止、`_pkgdata_tmp` 加 .gitignore、干净包禁止复制 secrets；再把 PyInstaller 与前端构建纳入 CI（当前 CI 只跑 6 个 Python 测试）。
5. 交付缺件补齐：`解除锁定.bat`、`使用说明.txt` 应入库并由打包脚本复制；U 盘同步脚本的目录名与版本号需参数化。
6. 测试基线要分层：无第三方依赖的 5 个测试可作“随时可跑”门槛；qa_regress/audit 需固定一份脱敏样例库随仓库/CI 提供，否则 21/21、60/60 只是历史数字。
