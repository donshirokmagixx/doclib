# -*- coding: utf-8 -*-
"""调用系统原生的「选择文件夹 / 选择文件」对话框。

用 PowerShell + .NET WinForms 实现：
- 打包成 exe 后同样可用（不依赖 tkinter / 不会再调用 python -c）
- 由独立子进程弹窗，不会卡住 HTTP 线程
- 失败时返回错误，界面自动回退到「手动输入路径」
"""
import os
import subprocess
import sys

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($env:DOCLIB_PICKER_SELFTEST -eq '1') { Write-Output 'SELFTEST_OK'; exit 0 }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# 一个隐形置顶窗口，保证对话框出现在最前面
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.Width = 1
$owner.Height = 1
$owner.StartPosition = 'Manual'
$owner.Location = New-Object System.Drawing.Point(-3000, -3000)
$owner.Show()
try {
  if ($env:DOCLIB_PICK_KIND -eq 'folder') {
    $d = New-Object System.Windows.Forms.FolderBrowserDialog
    $d.Description = '选择要导入的文件夹（会递归导入其中的资料文件）'
    $d.ShowNewFolderButton = $false
    $r = $d.ShowDialog($owner)
    if ($r -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.SelectedPath }
  } else {
    $d = New-Object System.Windows.Forms.OpenFileDialog
    $d.Multiselect = $true
    $d.CheckFileExists = $true
    $d.Title = '选择要导入的文件'
    $d.Filter = '所有文件|*.*|Word 文档|*.docx;*.doc|PDF|*.pdf|PowerPoint|*.pptx|图片|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff|文本|*.md;*.txt'
    $r = $d.ShowDialog($owner)
    if ($r -eq [System.Windows.Forms.DialogResult]::OK) {
      foreach ($f in $d.FileNames) { Write-Output $f }
    }
  }
} finally {
  try { $owner.Close() } catch {}
}
"""


def _run(script: str, timeout: int = 900) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
        capture_output=True, timeout=timeout, creationflags=flags,
    )


def pick(kind: str = "folder", timeout: int = 900) -> dict:
    if sys.platform != "win32":
        return {"ok": False, "error": "当前系统不支持原生选择对话框，请手动粘贴路径"}
    env = dict(os.environ)
    env["DOCLIB_PICK_KIND"] = "folder" if kind == "folder" else "files"
    env.pop("DOCLIB_PICKER_SELFTEST", None)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", _SCRIPT],
            capture_output=True, timeout=timeout, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "选择窗口超时未操作"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"无法打开选择窗口：{e}"}

    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        return {"ok": False, "error": err[:400] or f"选择窗口退出码 {proc.returncode}"}
    paths = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return {"ok": True, "paths": paths}


def selftest() -> dict:
    """不弹窗，只验证 PowerShell 通道可用（诊断用）。"""
    env = dict(os.environ)
    env["DOCLIB_PICKER_SELFTEST"] = "1"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", _SCRIPT],
            capture_output=True, timeout=60, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    out = (proc.stdout or b"").decode("utf-8", "replace")
    return {"ok": "SELFTEST_OK" in out,
            "rc": proc.returncode,
            "err": (proc.stderr or b"").decode("utf-8", "replace")[:200]}
