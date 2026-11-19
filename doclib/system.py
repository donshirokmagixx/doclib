# -*- coding: utf-8 -*-
"""系统能力：打开文件、备份、健康检查。"""
import ctypes
import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

from . import config


def open_document(path: str) -> dict:
    """用系统默认程序打开文件（不经 cmd.exe，避免路径元字符问题）。"""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"文件不存在：{path}"}
    try:
        if sys.platform == "win32":
            # ShellExecuteW 走 Windows 外壳关联，不经过命令行解析
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "open", str(p), None, str(p.parent), 1
            )
            if rc <= 32:
                os.startfile(str(p))  # 兜底
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "path": str(p)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def backup(conn, keep: int = None) -> dict:
    """用 VACUUM INTO 生成一致性快照（WAL 下也安全），并只保留最近 N 份。"""
    keep = keep or config.BACKUP_KEEP
    config.ensure_dirs()
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = config.BACKUP_DIR / f"doclib-{stamp}.db"
    n = 1
    while out.exists():
        out = config.BACKUP_DIR / f"doclib-{stamp}-{n}.db"
        n += 1
    conn.execute("VACUUM INTO ?", (str(out),))
    removed = []
    files = sorted(config.BACKUP_DIR.glob("doclib-*.db"))
    for old in files[:-keep]:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return {"ok": True, "file": str(out),
            "size_kb": round(out.stat().st_size / 1024, 1),
            "removed": removed, "kept": min(len(files), keep)}


def list_backups() -> list:
    if not config.BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(config.BACKUP_DIR.glob("doclib-*.db"), reverse=True):
        st = f.stat()
        out.append({
            "name": f.name,
            "size_kb": round(st.st_size / 1024, 1),
            "mtime": _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return out


def health(conn) -> dict:
    import sqlite3
    checks = {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version}
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _t USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE IF EXISTS _t")
        checks["trigram"] = True
    except Exception:
        checks["trigram"] = False
    checks["db"] = str(config.DB_PATH)
    checks["data_dir"] = str(config.DATA_DIR)
    checks["db_exists"] = config.DB_PATH.exists()

    # 多格式能力（缺了也能用，只是对应格式不可导）
    try:
        from . import ocr
        checks.update({
            "ocr": ocr.available(),
            "pdf": _has("pypdf"),
            "pptx": True,
            "md_txt": True,
        })
    except Exception:
        pass
    try:
        from . import convert
        checks["doc_convert"] = convert.available()
    except Exception:
        pass
    return checks


def _has(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False
