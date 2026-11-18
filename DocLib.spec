# -*- mode: python ; coding: utf-8 -*-
"""DocLib 打包配置（PyInstaller）。

用法（在 DocLib 目录下）：
    python -m PyInstaller --noconfirm DocLib.spec

产物：dist/DocLib/DocLib.exe（整个 dist/DocLib 文件夹可整体拷贝）
数据放在 exe 同级的 data/ 目录。
"""
from PyInstaller.utils.hooks import (collect_data_files, collect_dynamic_libs,
                                     collect_submodules, collect_all)

datas = [
    ("doclib/migrations", "migrations"),
    ("doclib/web/static", "web/static"),
    ("doclib/ai/prompts", "ai/prompts"),
]
datas += collect_data_files("pypdfium2")
datas += collect_data_files("winrt")

hiddenimports = [
    "pypdf",
    "chardet",
    "PIL",
    "PIL.Image",
    "pypdfium2",
    "pypdfium2_raw",
    "pypdfium2_cfg",
    "winrt",
    "winrt.system",
    "winrt.runtime",
    "winrt.windows",
]
hiddenimports += collect_submodules("winrt")
hiddenimports += ["webview", "webview.platforms.winforms", "clr_loader",
                  "doclib.motw",
                  "pythonnet", "bottle", "proxy_tools", "cffi"]
hiddenimports += globals().get("_extra_hidden", [])

binaries = collect_dynamic_libs("pypdfium2_raw")
binaries += collect_dynamic_libs("winrt")

# 原生窗口（pywebview + WebView2 + pythonnet）
for _pkg in ("webview", "pythonnet", "clr_loader", "bottle", "proxy_tools"):
    try:
        datas += collect_data_files(_pkg)
    except Exception:
        pass
    try:
        binaries += collect_dynamic_libs(_pkg)
    except Exception:
        pass

# 本地向量/语义检索：sqlite-vec 扩展、onnxruntime、numpy
# 精简打包：不内置本地向量推理（onnxruntime/numpy 会让包体从 75MB 涨到 800MB）
# 语义检索请在源码版使用；打包版保留关键词检索与全部文档功能。

excludes = [
    "tkinter", "matplotlib", "pandas", "scipy", "sympy",
    "torch", "torchvision", "transformers", "sklearn", "scikit-learn",
    "IPython", "jupyter", "pytest", "onnxruntime.tools",
    # 本地向量推理不进打包版（否则拖进 Anaconda 的 MKL，包体 750MB+）
    "numpy", "onnxruntime", "tokenizers", "sqlite_vec",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "notebook", "IPython",
    "jupyter", "sqlite_vec", "httpx", "keyring", "rapidfuzz",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="DocLib", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, disable_windowed_traceback=False,
)

# 第二个入口：无控制台窗口（原生窗口模式，双击直接开窗）
exe_w = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="DocLibW", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, exe_w,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DocLib",
)
