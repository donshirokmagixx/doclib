# -*- coding: utf-8 -*-
"""DocLib 打包入口。

启动形态（2026-11-14 起）：

    DocLib.exe                      → 原生窗口（推荐，默认）
    DocLib.exe --browser            → 浏览器模式（退路）
    DocLibW.exe                     → 原生窗口（别名，行为同上）
    DocLib.exe --port/--strict-port → 带参数时按浏览器/服务模式处理（供脚本调用）

源码运行：
    python run.py                   # 浏览器模式（开发用）
    python run.py --window          # 原生窗口
"""
import argparse
import os
import sys


def _safe_streams():
    """无控制台（windowed exe）模式下 stdout/stderr 为 None，print 会抛异常。"""
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
    try:
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass


def _hide_console():
    """窗口模式下隐藏黑色控制台窗口。

    仍用 console=True 构建（pywebview/WinForms 在此形态下初始化最稳），
    启动后立即把自己的控制台窗口隐藏掉。
    """
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


_safe_streams()


def main(argv=None, force_window: bool = False):
    raw = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="DocLib", description="个人资料库（本地窗口版）")
    p.add_argument("--port", type=int, default=None, help="端口（默认 8765）")
    p.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    p.add_argument("--strict-port", action="store_true", help="只用指定端口，不自动避让")
    p.add_argument("--window", action="store_true", help="用原生窗口打开（默认行为）")
    p.add_argument("--browser", action="store_true", help="改用浏览器模式（退路）")
    args = p.parse_args(raw)

    exe = os.path.basename(sys.executable).lower() if not force_window else ""
    # 打包版的 exe：默认窗口；只有显式 --browser 才回浏览器模式
    if exe in ("doclib.exe", "doclibw.exe") and not raw:
        force_window = True
    if args.browser:
        force_window = False

    if force_window or args.window:
        _hide_console()
        # 关键：从网络下载/解压的包会带 Zone.Identifier 标记，.NET（pythonnet）会
        # 拒绝加载被标记的程序集 → 窗口起不来。必须在导入 webview 之前清掉。
        try:
            from doclib import motw
            st = motw.unblock_install()
            if st.get("fixed"):
                print(f"[motw] 已解除 {st['fixed']} 个文件的网络阻止标记")
        except Exception as e:  # noqa: BLE001
            print("[motw] 解除标记失败（不影响继续尝试）：", e)
        from doclib.window import run_window
        return run_window(port=args.port) or 0

    from doclib.web.server import run
    try:
        return run(port=args.port, open_browser=not args.no_browser,
                   strict_port=args.strict_port) or 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
