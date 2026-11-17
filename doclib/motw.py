# -*- coding: utf-8 -*-
"""处理 Windows「来自网络」阻止标记（Mark of the Web / Zone.Identifier ADS）。

背景：从网上下载/解压得到的文件会带 `文件:Zone.Identifier`（ZoneId=3）。
pythonnet 加载 .NET 组件（Python.Runtime.dll）时，.NET 会拒绝加载"来自 Internet"区域
的程序集，表现为窗口模式启动失败（Failed to resolve Python.Runtime.Loader.Initialize），
而纯 Python 的本地服务不受影响 —— 于是"浏览器能用、窗口起不来"。

本模块在程序启动时静默清除自身目录下的该标记；失败不抛异常，只记录统计。
"""
import os
import sys

ZONE_STREAM = ":Zone.Identifier"
_INVALID = 0xFFFFFFFF


def _win32() -> bool:
    return sys.platform == "win32"


def install_dir() -> str:
    """需要处理的目录：打包后是 exe 所在目录（含 _internal）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return ""


def _is_blocked(path: str) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.GetFileAttributesW.restype = ctypes.c_uint32
    attr = k32.GetFileAttributesW(ctypes.c_wchar_p(path + ZONE_STREAM))
    return attr != _INVALID


def _unblock_one(path: str) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.DeleteFileW.argtypes = [ctypes.c_wchar_p]
    k32.DeleteFileW.restype = ctypes.c_int
    return bool(k32.DeleteFileW(ctypes.c_wchar_p(path + ZONE_STREAM)))


def unblock_install(root: str = None) -> dict:
    """递归清除 root（默认 exe 目录）下所有文件的 Zone.Identifier。

    返回 {"blocked": 清除前带标记的文件数, "fixed": 成功清除数, "scanned": 扫描数}
    """
    stats = {"blocked": 0, "fixed": 0, "scanned": 0}
    if not _win32():
        return stats
    root = root or install_dir()
    if not root or not os.path.isdir(root):
        return stats
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            stats["scanned"] += 1
            try:
                if not _is_blocked(p):
                    continue
                stats["blocked"] += 1
                if _unblock_one(p):
                    stats["fixed"] += 1
            except Exception:
                continue
    return stats


def verify_clean(root: str = None) -> int:
    """返回仍带标记的文件数（用于自检/打包校验）。"""
    root = root or install_dir()
    if not _win32() or not root or not os.path.isdir(root):
        return 0
    left = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                if _is_blocked(os.path.join(base, name)):
                    left += 1
            except Exception:
                pass
    return left


def show_message(text: str, title: str = "DocLib") -> None:
    """原生提示框（窗口层加载失败时用，不能依赖 webview）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)  # MB_ICONINFORMATION
    except Exception:
        pass


if __name__ == "__main__":
    import json
    print(json.dumps(unblock_install(), ensure_ascii=False))
    print("剩余带标记文件:", verify_clean())
