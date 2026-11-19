# -*- coding: utf-8 -*-
"""原生窗口模式（pywebview + WebView2）：不依赖浏览器。

用法：
    python run.py --window
    DocLib.exe --window
"""


def available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def _focus_existing(title: str) -> bool:
    """把已经打开的 DocLib 窗口提到前台（双击快捷方式时更符合直觉）。"""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, title)
        if hwnd:
            u32.ShowWindow(hwnd, 9)          # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def _fail_hint(err: str) -> None:
    """窗口层起不来时：写日志 + 弹原生提示（不能依赖 webview）。"""
    msg = (
        "DocLib 的独立窗口没能启动。\n\n"
        "最常见原因：程序包是从网上下载/解压的，文件带着 Windows 的"
        "“来自网络”阻止标记，.NET 组件因此被拒绝加载。\n\n"
        "解决办法（任选其一）：\n"
        "1) 打开程序文件夹，双击「解除锁定.bat」，然后再启动 DocLib；\n"
        "2) 右键程序文件夹 → 属性 → 勾选「解除锁定」→ 确定；\n"
        "3) 临时改用浏览器模式：命令行运行  DocLib.exe --browser\n\n"
        f"技术信息：{err[:300]}"
    )
    try:
        from . import motw, config
        motw.show_message(msg)
        try:
            (config.DATA_DIR / "window_error.log").write_text(
                f"{err}\n", encoding="utf-8")
        except Exception:
            pass
    except Exception:
        pass


def run_window(port: int = None, title: str = "DocLib 2.0 · 本地知识工作台",
               width: int = 1320, height: int = 880):
    from .web import server

    info = server.live_instance()
    if info:
        print()
        print(f"  [!] DocLib 已经在运行（PID {info['pid']}，端口 {info['port']}）")
        if _focus_existing(title):
            print("      >>> 已把现有窗口切到前台。")
        else:
            print(f"      界面地址：{info['url']}")
            print("      >>> 已有实例在运行，本次不再启动新窗口。")
        return 0

    httpd, actual_port, url = server.start_server(port=port, strict_port=False)
    print(f"[window] 服务已启动：{url}")

    try:
        import webview
    except Exception as e:  # noqa: BLE001
        print("[window] 未安装 pywebview：", e)
        _fail_hint(str(e))
        server.stop_server(httpd)
        return 5

    webview.create_window(title, url, width=width, height=height,
                          min_size=(920, 620), text_select=True)
    try:
        webview.start(debug=False)
    except Exception as e:  # noqa: BLE001
        print("[window] 窗口启动失败：", e)
        _fail_hint(str(e))
        return 5
    finally:
        try:
            server.stop_server(httpd)
        except Exception:
            pass
    return 0
