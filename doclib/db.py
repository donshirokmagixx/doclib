# -*- coding: utf-8 -*-
"""数据库连接与迁移。

v2.0 起：
- 有待执行迁移时先备份 doclib.db；
- 每个迁移在单个事务中执行（失败回滚、不写版本）；
- meta.schema_version 写实际最大版本，不再永远 "0001"。
"""
import sqlite3
import time
from pathlib import Path

from . import config


def now_ms() -> int:
    return int(time.time() * 1000)


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(str(config.DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        pass
    return conn


def _get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _set(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def get_meta(conn, key, default=None):
    return _get(conn, key, default)


def set_meta(conn, key, value):
    _set(conn, key, value)


def bump_library_version(conn) -> int:
    cur = int(_get(conn, "library_version", "1") or 1)
    cur += 1
    _set(conn, "library_version", cur)
    return cur


def _backup_before_migration(conn, version: int) -> Path:
    config.ensure_dirs()
    dst = config.BACKUP_DIR / f"pre-migrate-{version:04d}-{now_ms()}.db"
    tmp = dst.with_suffix(".tmp")
    out = None
    try:
        out = sqlite3.connect(str(tmp))
        conn.backup(out)
        out.close()
        out = None
        tmp.replace(dst)
    except Exception:
        if out is not None:
            try:
                out.close()
            except Exception:
                pass
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    # 只保留最近两份迁移前备份
    old = sorted(config.BACKUP_DIR.glob("pre-migrate-*.db"))
    for p in old[:-2]:
        try:
            p.unlink()
        except OSError:
            pass
    return dst


def _apply_one(conn, version: int, name: str, sql: str) -> None:
    """单事务执行一个迁移；版本行与 DDL 同事务。"""
    safe_name = name.replace("'", "''")
    script = (
        "BEGIN IMMEDIATE;\n"
        + sql
        + f"\nINSERT INTO schema_migrations(version,name,applied_at) "
          f"VALUES({version},'{safe_name}',{now_ms()});\n"
          "COMMIT;\n"
    )
    try:
        conn.executescript(script)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


def migrate(conn) -> None:
    """顺序执行 migrations/*.sql；有待执行项时先备份。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL)"
    )
    applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}

    pending = []
    for f in sorted(config.MIGRATIONS_DIR.glob("*.sql")):
        try:
            version = int(f.name.split("_")[0])
        except ValueError:
            continue
        if version not in applied:
            pending.append((version, f))
    if not pending:
        if _get(conn, "schema_version") is None:
            _set(conn, "schema_version", f"{max(applied) if applied else 0:04d}")
        return

    if applied and config.DB_PATH.exists() and config.DB_PATH.stat().st_size > 0:
        _backup_before_migration(conn, pending[0][0])

    for version, f in pending:
        _apply_one(conn, version, f.name, f.read_text(encoding="utf-8"))
        applied.add(version)

    if _get(conn, "library_version") is None:
        _set(conn, "library_version", 1)
    _set(conn, "schema_version", f"{max(applied):04d}")
    # 结构变化让检索/缓存失效
    try:
        bump_library_version(conn)
    except Exception:
        pass
    conn.execute("PRAGMA optimize")


def open_db() -> sqlite3.Connection:
    """连接 + 自动迁移，业务代码都走这个。"""
    conn = connect()
    migrate(conn)
    return conn
