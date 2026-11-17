# 窗口版无法启动（退出码 5）——「来自网络」阻止标记（MOTW）

## 现象

- 双击 `DocLib.exe` 没有独立窗口，或一闪即退，退出码 **5**
- 但浏览器访问 `http://127.0.0.1:8765/` 正常

日志示例：

```
[window] 服务已启动：http://127.0.0.1:8765/
[window] 窗口启动失败： Failed to resolve Python.Runtime.Loader.Initialize
         from ...\_internal\pythonnet\runtime\Python.Runtime.dll
```

## 原因

从网上下载/解压的文件带 `Zone.Identifier`（ZoneId=3，"来自 Internet"）。
窗口层使用 pywebview + pythonnet(.NET)，.NET 会拒绝加载 Internet 区域的程序集；
而本地 HTTP 服务是纯 Python，不受影响 —— 于是"浏览器能用、窗口不行"。

## 处理

1. 运行包内 `解除锁定.bat`（等价于对整个文件夹 `Unblock-File`）
2. 或：右键程序文件夹 → 属性 → 勾选「解除锁定」→ 确定
3. 程序启动时也会自动清除自身目录的该标记（兜底）
4. 临时替代：`DocLib.exe --browser`

```powershell
Get-ChildItem '<程序目录>' -Recurse -File | Unblock-File
```
