# -*- coding: utf-8 -*-
"""数据库连接与迁移。"""
import sqlite3
import time

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
    # 向量检索扩展（可选）：装了 sqlite-vec 才有语义检索能力
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


def migrate(conn) -> None:
    """顺序执行 migrations/*.sql，幂等。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL)"
    )
    applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    for f in sorted(config.MIGRATIONS_DIR.glob("*.sql")):
        try:
            version = int(f.name.split("_")[0])
        except ValueError:
            continue
        if version in applied:
            continue
        conn.executescript(f.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
            (version, f.name, now_ms()),
        )

    if _get(conn, "library_version") is None:
        _set(conn, "library_version", 1)
    _set(conn, "schema_version", f"0001")
    conn.execute("PRAGMA optimize")


def open_db() -> sqlite3.Connection:
    """连接 + 自动迁移，业务代码都走这个。"""
    conn = connect()
    migrate(conn)
    return conn
