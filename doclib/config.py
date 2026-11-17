# -*- coding: utf-8 -*-
"""路径与运行配置。数据目录可用环境变量 DOCLIB_DATA 覆盖。

打包成 exe 后：
- 资源（migrations / 静态页面）随 PyInstaller 解包在 sys._MEIPASS
- 数据（数据库/备份/转换缓存）放在 **exe 同级的 data/ 目录**，方便整个文件夹拷走
"""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent          # exe 所在目录
    RES_DIR = Path(getattr(sys, "_MEIPASS", str(APP_DIR)))    # 打包资源解包目录
else:
    APP_DIR = Path(__file__).resolve().parent.parent         # 项目根目录
    RES_DIR = Path(__file__).resolve().parent                # doclib/

def _default_data_dir() -> Path:
    """数据目录解析顺序：

    1) 环境变量 DOCLIB_DATA（最高优先级，便于测试/多库）
    2) 打包版：exe 同级 data/（便携：整个文件夹拷走）
    3) 源码版：优先用发布版数据 dist/DocLib/data（数据收归一处），
       没有发布版时才退回项目 data/
    """
    env = os.environ.get("DOCLIB_DATA")
    if env:
        return Path(env).resolve()
    if FROZEN:
        return (APP_DIR / "data").resolve()
    release = APP_DIR / "dist" / "DocLib" / "data"
    if (release / "doclib.db").exists():
        return release.resolve()
    return (APP_DIR / "data").resolve()


DATA_DIR = _default_data_dir()
DB_PATH = DATA_DIR / "doclib.db"
BACKUP_DIR = DATA_DIR / "backups"
CONVERT_DIR = DATA_DIR / "converted"     # .doc → .docx 转换缓存
MIGRATIONS_DIR = RES_DIR / "migrations"
STATIC_DIR = RES_DIR / "web" / "static"

HOST = "127.0.0.1"
PORT = int(os.environ.get("DOCLIB_PORT", "8765"))

# 分块参数
CHUNK_TARGET = 450      # 目标字数
CHUNK_MAX = 900         # 单块硬上限
CHUNK_MIN_MERGE = 40    # 小于该长度的尾块尝试并入上一块

# 备份保留份数
BACKUP_KEEP = 7

# OCR / 转换
OCR_MAX_PAGES = 50      # 单个 PDF 最多 OCR 多少页（防止一本书跑几小时）
OCR_MIN_TEXT = 12       # 一页提取到的文字少于这个数就认为需要 OCR


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    CONVERT_DIR.mkdir(parents=True, exist_ok=True)
