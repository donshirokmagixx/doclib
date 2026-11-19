# -*- coding: utf-8 -*-
"""v2.0 迁移：旧库升级、备份、schema_version、失败回滚、幂等。"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
TMP = tempfile.mkdtemp(prefix="doclib_migrate_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import config, db  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {extra}"))
    if not cond:
        FAIL.append(name)


def build_old_db():
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    for i in range(1, 6):
        f = sorted(config.MIGRATIONS_DIR.glob(f"000{i}_*.sql"))[0]
        conn.executescript(f.read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at INTEGER NOT NULL)")
    for i in range(1, 6):
        conn.execute("INSERT INTO schema_migrations VALUES(?,?,?)", (i, f"000{i}.sql", 1))
    conn.execute("INSERT INTO meta(key,value) VALUES('library_version','7')")
    conn.execute("INSERT INTO nodes(id,parent_id,name,path,depth,created_at,updated_at) VALUES(1,NULL,'旧节点','/1/',0,1,1)")
    conn.execute("INSERT INTO documents(id,title,file_path,path_key,file_type,parse_status,char_count,created_at,updated_at) "
                 "VALUES(1,'旧文档','/tmp/old.md','/tmp/old.md','md',2,10,1,1)")
    conn.execute("INSERT INTO doc_chunks(doc_id,ord,heading_path,text,char_len) VALUES(1,0,'旧章节','旧内容',3)")
    conn.commit()
    conn.close()


def main():
    config.ensure_dirs()
    build_old_db()
    check("旧库已建", config.DB_PATH.exists())

    conn = db.open_db()
    try:
        print("1) 旧库升级")
        rows = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        check("迁移版本 1..7", rows == [1, 2, 3, 4, 5, 6, 7], rows)
        check("schema_version=0007", db.get_meta(conn, "schema_version") == "0007",
              db.get_meta(conn, "schema_version"))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        check("messages.context_json", "context_json" in cols)
        ccols = {r[1] for r in conn.execute("PRAGMA table_info(message_citations)")}
        check("citations.source_kind", "source_kind" in ccols and "note_id" in ccols)
        dcols = {r[1] for r in conn.execute("PRAGMA table_info(doc_chunks)")}
        check("doc_chunks.page", "page" in dcols and "start_off" in dcols)
        check("relations 表", bool(conn.execute("SELECT name FROM sqlite_master WHERE name='relations'").fetchone()))
        check("notes/note_links 表", bool(conn.execute("SELECT name FROM sqlite_master WHERE name='notes'").fetchone())
              and bool(conn.execute("SELECT name FROM sqlite_master WHERE name='note_links'").fetchone()))
        check("旧节点/文档保留",
              conn.execute("SELECT name FROM nodes WHERE id=1").fetchone()[0] == "旧节点"
              and conn.execute("SELECT title FROM documents WHERE id=1").fetchone()[0] == "旧文档")
        backups = list(config.BACKUP_DIR.glob("pre-migrate-*.db"))
        check("迁移前备份存在", len(backups) >= 1, backups)
    finally:
        conn.close()

    print("2) 幂等：再次 open_db 不重复迁移、不产生新备份")
    before = len(list(config.BACKUP_DIR.glob("pre-migrate-*.db")))
    conn = db.open_db()
    try:
        after = len(list(config.BACKUP_DIR.glob("pre-migrate-*.db")))
        check("版本仍 7", [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")][-1] == 7)
        check("无新备份", after == before, (before, after))
    finally:
        conn.close()

    print("3) 失败迁移回滚")
    conn = db.open_db()
    try:
        try:
            db._apply_one(conn, 999, "bad.sql",
                          "CREATE TABLE bad_tmp(id INTEGER);\nINSERT INTO no_such_table VALUES(1);")
            check("应抛错", False)
        except Exception:
            check("抛错", True)
        check("失败 DDL 回滚", conn.execute("SELECT name FROM sqlite_master WHERE name='bad_tmp'").fetchone() is None)
        check("失败版本未写入", conn.execute("SELECT version FROM schema_migrations WHERE version=999").fetchone() is None)
    finally:
        conn.close()

    print("\n全部通过 ✅（临时库：%s）" % TMP)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
