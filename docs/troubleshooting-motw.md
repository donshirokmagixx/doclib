# 故障排查：窗口版无法启动（退出码 5）——「来自网络」阻止标记（MOTW）

## 一、现象

- 双击 `DocLib.exe` 后**没有独立窗口**，或窗口一闪即退，进程退出码 **5**
- 但同时访问 `http://127.0.0.1:8765/` **完全正常**（浏览器模式可用）
- 程序日志（GBK）：
  ```
  [window] 服务已启动：http://127.0.0.1:8765/
  [window] 窗口启动失败： Failed to resolve Python.Runtime.Loader.Initialize
           from ...\_internal\pythonnet\runtime\Python.Runtime.dll
  进程退出码 5
  ```

## 二、根因

1. 程序包从网上下载（rar/zip）后解压，Windows 会给**每个文件**写入
   `文件:Zone.Identifier` 备用数据流（内容含 `ZoneId=3`，即"来自 Internet"）。
2. 窗口层是 pywebview + **pythonnet（.NET）**：需要加载
   `_internal\pythonnet\runtime\Python.Runtime.dll`。
3. .NET 的安全策略会拒绝加载落在 Internet 区域的程序集 → `clr_loader` 初始化失败
   → pywebview 起不来 → 程序按设计返回 5。
4. 本地 HTTP 服务是**纯 Python**（标准库），不依赖 .NET，因此不受影响
   → 造成"浏览器能用、窗口起不来"的典型分裂现象。
5. 主 `DocLib.exe` 之前被单独"解除锁定"过（无标记），所以 exe 能运行、服务能起；
   内部 242 个 DLL 仍带标记，因此只有窗口失败。

> 判定口诀：**浏览器能开、窗口不行 → 先怀疑 MOTW（来自网络标记）**。

## 三、验证（本次实测）

| 实验 | 结果 |
|---|---|
| 给副本的 283 个非 exe 文件打 `ZoneId=3` 标记 | 标记数 283 |
| 直接启动 `DocLib.exe`（exe 未标记） | 窗口正常打开；启动后标记数 **0**（程序自愈）；health=r13 |
| 只标记 `_internal`（236 个）再启动 | 同上：窗口正常、标记清零 |
| 运行 `解除锁定.bat` | 283 → **0**，输出"仍有阻止标记的文件: 0" |
| 对照（不做任何处理） | 命中日志中的 `Python.Runtime.Loader.Initialize` 失败、退出码 5 |

## 四、已实施的修复（r13）

1. **启动自愈（核心）**：`doclib/motw.py` + `run.py`
   - 在导入 pywebview / pythonnet **之前**，递归清除自身目录下所有文件的
     `Zone.Identifier`（用 Win32 `DeleteFileW` 直接删 ADS，不依赖 PowerShell）。
   - 只删元数据流，不改文件内容、不动 data。
2. **显式脚本**：包内新增 `解除锁定.bat`
   - 一键递归 `Unblock-File`，并显示剩余带标记文件数（0 为成功）。
3. **启动器兜底**：`启动 DocLib.bat` 先静默解除标记，再启动 exe。
4. **失败可诊断**：窗口失败时弹原生提示框（说明原因 + 三种解决方式），
   并写 `data\window_error.log`，不再只给一个退出码。
5. **文档**：`使用说明.txt`、`UserNotesV1.0.0.docx` 增加「解压后先解除锁定」章节与 FAQ。

## 五、分发与长期优化建议

| 优先级 | 措施 | 理由 |
|---|---|---|
| P0 | 分发时附 `解除锁定.bat`，并在说明第一行写"解压后先运行它" | 覆盖 99% 的此类故障 |
| P0 | 不要把"解压即可双击 exe"当作默认指引；先解除锁定 | 减少首批使用者踩坑 |
| P1 | 用 **zip** 而不是 rar（或提供自解压 exe） | Windows 自带的"解除锁定"更易操作；rar 解压同样会带标记 |
| P1 | 保留 `DocLib.exe --browser` 作为排障入口 | 窗口层故障时仍可工作 |
| P2 | 数字签名（代码签名证书） | 降低 SmartScreen 拦截；但**不能**替代 MOTW 处理 |
| P2 | 评估"不依赖 .NET 的窗口方案"（如 Edge `--app` 包装）作为兜底 | 从根上消除 pythonnet 依赖 |
| P3 | 打包时做一次"标记自检"（`motw.verify_clean`） | 发版前拦住带标记的构建产物 |

## 六、复现与修复命令（给使用者）

```powershell
# 查看哪些文件带标记（可选）
Get-ChildItem 'D:\DocLib\MySoftWare_Vision1_0_0' -Recurse -File |
  Where-Object { (Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue) } |
  Measure-Object

# 一键解除（只删元数据，不改内容）
Get-ChildItem 'D:\DocLib\MySoftWare_Vision1_0_0' -Recurse -File | Unblock-File

# 或者：右键文件夹 → 属性 → 勾选「解除锁定」
```

版本：r13（2026-11-15）已内置启动自愈；旧包请重新分发或运行 `解除锁定.bat`。

---

## 七、后续修复（2026-11-15，r13 补丁）：`解除锁定.bat` 自身两个 bug

有使用者运行 `解除锁定.bat` 时看到 PowerShell 报错：
```
$n=0 : The term '$n=0' is not recognized ...
```
以及中文乱码。原因有两个：

1. **路径引号被"吃掉"**：脚本里写 `-LiteralPath '%~dp0'`，而 `%~dp0` 以反斜杠结尾，
   展开成 `'D:\path\'` —— 结尾的 `\` 把单引号"转义"，PowerShell 把后面的 `; $n=0; ...`
   当成新命令，于是报 `CommandNotFound`。
2. **编码不匹配**：`.bat` 以 GBK 保存，却执行了 `chcp 65001`，中文全部变乱码。

修复方式：
- `.bat` 统一用 **GBK(cp936)** 保存，`chcp 936`；
- 用 `cd /d "%~dp0"` 进入目录（不用 `pushd`，避免结尾反斜杠问题），
  PowerShell 改用相对路径 `.`；
- `启动 DocLib.bat` 不再内嵌 PowerShell（减少失败面），依赖 exe 自身在导入窗口组件前
  自动清除标记；`解除锁定.bat` 仍保留为手动工具。

实测（带标记的副本）：
- `解除锁定.bat`：284 个标记文件 → **0**，输出「仍有阻止标记的文件: 0」，无 PowerShell 报错；
- `启动 DocLib.bat`：仅标记 `_internal`（236 个）时启动 → 窗口正常、health=r13、标记清零。
