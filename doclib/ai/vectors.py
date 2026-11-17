# -*- coding: utf-8 -*-
"""向量索引（sqlite-vec），用于语义检索。

- 表结构：chunk_vec(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[512])
- 向量由本地 bge-small-zh 模型生成（免费、离线）
- chunk 删除/重切后，孤儿向量由 cleanup() 清掉
"""
from typing import List, Optional

DIM = 512


def _load(conn) -> bool:
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


_loaded_flag = {"ok": None}


def available(conn=None) -> bool:
    if _loaded_flag["ok"] is None:
        if conn is None:
            return False
        _loaded_flag["ok"] = _load(conn)
    return bool(_loaded_flag["ok"])


def ensure_table(conn) -> bool:
    if not available(conn):
        return False
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{DIM}])")
        return True
    except Exception:
        return False


def _pack(vec: List[float]) -> bytes:
    import array
    return array.array("f", vec).tobytes()


def count(conn) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM chunk_vec").fetchone()[0]
    except Exception:
        return 0


def missing_chunks(conn, limit: int = 0) -> List[dict]:
    sql = ("SELECT c.id, c.text FROM doc_chunks c "
           "WHERE c.id NOT IN (SELECT chunk_id FROM chunk_vec) ORDER BY c.id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    except Exception:
        return []


def index_missing(conn, limit: int = 0, batch_size: int = 16,
                  progress=None) -> dict:
    """给还没向量化的 chunk 补向量。返回统计。"""
    from . import embedder
    st = embedder.available()
    if not st["ok"]:
        return {"ok": False, "error": st["error"] or "本地向量模型不可用", "added": 0}
    if not ensure_table(conn):
        return {"ok": False, "error": "sqlite-vec 扩展不可用", "added": 0}

    rows = missing_chunks(conn, limit)
    total = len(rows)
    added = 0
    failed = 0
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        texts = [r["text"] or " " for r in batch]
        try:
            vecs = embedder.embed_texts(texts)
        except Exception as e:  # noqa: BLE001
            failed += len(batch)
            if progress:
                progress(f"编码失败：{e}")
            continue
        for r, v in zip(batch, vecs):
            try:
                conn.execute("INSERT OR REPLACE INTO chunk_vec(chunk_id, embedding) "
                             "VALUES(?, ?)", (r["id"], _pack(v)))
                added += 1
            except Exception:
                failed += 1
        if progress:
            progress(f"已生成 {added}/{total}")
    return {"ok": True, "added": added, "failed": failed,
            "total_chunks": conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0]}


def delete_for_doc(conn, doc_id: int) -> None:
    try:
        conn.execute(
            "DELETE FROM chunk_vec WHERE chunk_id IN "
            "(SELECT id FROM doc_chunks WHERE doc_id=?)", (doc_id,))
    except Exception:
        pass


def cleanup(conn) -> int:
    """删掉指向已不存在 chunk 的向量。"""
    if not ensure_table(conn):
        return 0
    try:
        cur = conn.execute(
            "DELETE FROM chunk_vec WHERE chunk_id NOT IN (SELECT id FROM doc_chunks)")
        return cur.rowcount or 0
    except Exception:
        return 0


def clear(conn) -> None:
    try:
        conn.execute("DELETE FROM chunk_vec")
    except Exception:
        pass


def search(conn, query_vec: List[float], k: int = 60) -> List[tuple]:
    """返回 [(chunk_id, distance)]，distance 越小越像。"""
    if not ensure_table(conn):
        return []
    try:
        rows = conn.execute(
            "SELECT chunk_id, distance FROM chunk_vec "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_pack(query_vec), k),
        ).fetchall()
        return [(r[0], float(r[1])) for r in rows]
    except Exception:
        return []


def doc_ids_with_vectors(conn) -> set:
    try:
        rows = conn.execute(
            "SELECT DISTINCT c.doc_id FROM chunk_vec v "
            "JOIN doc_chunks c ON c.id = v.chunk_id").fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


def stats(conn) -> dict:
    from . import embedder
    total = 0
    try:
        total = conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0]
    except Exception:
        pass
    return {
        "model": embedder.status(),
        "sqlite_vec": available(conn),
        "total_chunks": total,
        "indexed_chunks": count(conn),
        "missing": max(0, total - count(conn)),
    }
