# -*- coding: utf-8 -*-
"""A3：引用快照契约。

**核心约定：AI 回答里引用的来源，永远不依赖 chunk_id。**

原因：chunk 是派生数据，将来重新解析 / 重新切块后 id 会全变。
如果历史对话里存了 chunk_id，旧引用就全断了。

所以引用一律保存：
    (doc_id, heading_path, snippet 前 80 字, 引用时正文的 sha1)

chunk_id 只作为调试线索保留，可以随时失效。
"""
import hashlib
from typing import Optional

from .db import now_ms

SNIPPET_LEN = 80


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def snapshot(conn, chunk_id: int) -> Optional[dict]:
    """从 chunk 生成一条「引用快照」（用于写入 message_citations）。"""
    row = conn.execute(
        "SELECT c.id, c.doc_id, c.heading_path, c.text, d.title "
        "FROM doc_chunks c JOIN documents d ON d.id = c.doc_id WHERE c.id=?",
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None
    text = row["text"] or ""
    return {
        "doc_id": row["doc_id"],
        "doc_title": row["title"],
        "heading_path": row["heading_path"] or "",
        "snippet": text[:SNIPPET_LEN].replace("\n", " "),
        "text_hash": text_hash(text),
        "chunk_id": row["id"],
    }


def save_citations(conn, message_id: int, snaps, scores=None) -> int:
    """把一批引用快照写进 message_citations。"""
    n = 0
    scores = scores or []
    for i, s in enumerate(snaps):
        if not s:
            continue
        conn.execute(
            "INSERT INTO message_citations(message_id, doc_id, heading_path, snippet, "
            "text_hash, score, chunk_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (message_id, s["doc_id"], s["heading_path"], s["snippet"],
             s["text_hash"], float(scores[i]) if i < len(scores) else 0.0,
             s.get("chunk_id"), now_ms()),
        )
        n += 1
    return n


def resolve(conn, citation_row) -> dict:
    """按当前索引重新定位一条历史引用。

    返回：
        {"found": bool, "text": str|None, "doc_title": str, "heading_path": str,
         "snippet": str, "drifted": bool}

    - 用 text_hash 精确匹配 → 说明这段内容还在，引用有效
    - 找不到相同 hash，但同一文档同一标题下还有块 → drifted=True（内容被改过/重切过）
    - 文档都不在了 → found=False，只剩快照可显示
    """
    doc_id = citation_row["doc_id"]
    snippet = citation_row["snippet"] or ""
    th = citation_row["text_hash"] or ""
    doc = conn.execute("SELECT id, title FROM documents WHERE id=?", (doc_id,)).fetchone()
    out = {
        "found": False, "text": None,
        "doc_title": doc["title"] if doc else "",
        "heading_path": citation_row["heading_path"] or "",
        "snippet": snippet, "drifted": False,
    }
    if doc is None:
        return out

    row = conn.execute(
        "SELECT id, text FROM doc_chunks WHERE doc_id=? AND heading_path=? "
        "ORDER BY ord", (doc_id, citation_row["heading_path"] or "")
    ).fetchall()
    for r in row:
        if text_hash(r["text"]) == th:
            out.update(found=True, text=r["text"])
            return out
    if row:
        out.update(found=True, text=row[0]["text"], drifted=True)
        return out
    # 标题也变了：退化为「同文档任意块」
    anyrow = conn.execute(
        "SELECT id, text FROM doc_chunks WHERE doc_id=? ORDER BY ord LIMIT 1", (doc_id,)
    ).fetchone()
    if anyrow:
        out.update(found=True, text=anyrow["text"], drifted=True)
    return out


def list_for_message(conn, message_id: int):
    rows = conn.execute(
        "SELECT * FROM message_citations WHERE message_id=? ORDER BY id", (message_id,)
    ).fetchall()
    out = []
    for i, r in enumerate(rows, 1):
        d = resolve(conn, r)
        d["chunk_id"] = r["chunk_id"]
        d["index"] = i
        out.append(d)
    return out
