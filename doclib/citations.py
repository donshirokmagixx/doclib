# -*- coding: utf-8 -*-
"""A3：引用快照契约。

**核心约定：AI 回答里引用的来源，永远不依赖 chunk_id。**

引用一律保存：
    (source_kind, doc_id/note_id, heading_path, snippet 前 80 字, 引用时正文的 sha1,
     page/start_off/end_off/quote)
chunk_id 只作为调试线索保留，可以随时失效。

v2.0 扩展：source_kind = document | selection | note；笔记引用按 note_chunks 重新定位。
"""
import hashlib
from typing import Optional

from .db import now_ms

SNIPPET_LEN = 80


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def snapshot(conn, chunk_id: int) -> Optional[dict]:
    """从 doc chunk 生成一条引用快照。"""
    row = conn.execute(
        "SELECT c.id, c.doc_id, c.heading_path, c.text, d.title "
        "FROM doc_chunks c JOIN documents d ON d.id = c.doc_id WHERE c.id=?",
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None
    text = row["text"] or ""
    return {
        "source_kind": "document",
        "doc_id": row["doc_id"],
        "note_id": None,
        "doc_title": row["title"],
        "heading_path": row["heading_path"] or "",
        "snippet": text[:SNIPPET_LEN].replace("\n", " "),
        "text_hash": text_hash(text),
        "chunk_id": row["id"],
        "quote": "",
    }


def save_citations(conn, message_id: int, snaps, scores=None) -> int:
    """把一批引用快照写进 message_citations。"""
    n = 0
    scores = scores or []
    for i, s in enumerate(snaps):
        if not s:
            continue
        source_kind = s.get("source_kind") or "document"
        doc_id = int(s.get("doc_id") or 0)
        note_id = s.get("note_id")
        conn.execute(
            "INSERT INTO message_citations(message_id, doc_id, heading_path, snippet, "
            "text_hash, score, chunk_id, created_at, source_kind, note_id, doc_title, "
            "page, start_off, end_off, quote) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (message_id, doc_id, s.get("heading_path") or "",
             s.get("snippet") or "", s.get("text_hash") or "",
             float(scores[i]) if i < len(scores) else 0.0,
             s.get("chunk_id"), now_ms(), source_kind, note_id,
             s.get("doc_title") or "", s.get("page"),
             s.get("start_off"), s.get("end_off"), s.get("quote") or ""),
        )
        n += 1
    return n


def _resolve_note(conn, citation_row, out: dict) -> dict:
    note_id = _get(citation_row, "note_id")
    if not note_id:
        return out
    note = conn.execute(
        "SELECT id, title FROM notes WHERE id=? AND deleted_at IS NULL", (note_id,)
    ).fetchone()
    if note is None:
        return out
    out["doc_title"] = out["doc_title"] or note["title"]
    th = _get(citation_row, "text_hash") or ""
    hp = _get(citation_row, "heading_path") or ""
    rows = conn.execute(
        "SELECT id, text FROM note_chunks WHERE note_id=? AND heading_path=? ORDER BY ord",
        (note_id, hp)).fetchall()
    for r in rows:
        if text_hash(r["text"]) == th:
            out.update(found=True, text=r["text"])
            return out
    anyrow = conn.execute(
        "SELECT id, text FROM note_chunks WHERE note_id=? ORDER BY ord LIMIT 1",
        (note_id,)).fetchone()
    if anyrow:
        out.update(found=True, text=anyrow["text"], drifted=bool(rows))
    return out


def resolve(conn, citation_row) -> dict:
    """按当前索引重新定位一条历史引用。"""
    source_kind = _get(citation_row, "source_kind") or "document"
    doc_id = _get(citation_row, "doc_id") or 0
    snippet = _get(citation_row, "snippet") or ""
    th = _get(citation_row, "text_hash") or ""
    quote = _get(citation_row, "quote") or ""
    out = {
        "found": False, "text": None,
        "source_kind": source_kind,
        "doc_id": doc_id,
        "note_id": _get(citation_row, "note_id"),
        "doc_title": _get(citation_row, "doc_title") or "",
        "heading_path": _get(citation_row, "heading_path") or "",
        "snippet": snippet,
        "quote": quote,
        "page": _get(citation_row, "page"),
        "start_off": _get(citation_row, "start_off"),
        "end_off": _get(citation_row, "end_off"),
        "drifted": False,
    }
    if source_kind == "note":
        return _resolve_note(conn, citation_row, out)
    if source_kind == "selection" and quote:
        # 选文是用户当时看到的原文；文档还在就认为可显示
        doc = conn.execute(
            "SELECT id, title FROM documents WHERE id=?", (doc_id,)).fetchone()
        if doc:
            out.update(found=True, text=quote, doc_title=out["doc_title"] or doc["title"])
        return out
    doc = conn.execute("SELECT id, title FROM documents WHERE id=?", (doc_id,)).fetchone()
    if doc is None:
        return out
    out["doc_title"] = out["doc_title"] or doc["title"]
    row = conn.execute(
        "SELECT id, text FROM doc_chunks WHERE doc_id=? AND heading_path=? "
        "ORDER BY ord", (doc_id, out["heading_path"])).fetchall()
    for r in row:
        if text_hash(r["text"]) == th:
            out.update(found=True, text=r["text"])
            return out
    if row:
        out.update(found=True, text=row[0]["text"], drifted=True)
        return out
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
