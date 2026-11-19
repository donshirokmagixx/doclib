# -*- coding: utf-8 -*-
"""笔记的存储、Markdown 分块、FTS 检索与保存冲突处理。

与 ``doclib/notes.py``（Word 导出）无关：本模块是 v2.0 的 Markdown 笔记真值层。

数据流
------
``save_note`` 在一个事务里完成：校验 → upsert ``notes`` → 重建 ``note_chunks``
（触发器同步 ``note_fts``，不手写 FTS 内容）→ ``links.sync_links`` 重建 ``note_links``。

分区与节点
----------
分区 = ``parent_id`` 为空且 ``is_system=0`` 的一级节点；``node_id`` 必须属于该分区
（未显式给分区时由节点反推）。笔记标题全局唯一且不区分大小写（迁移 0007 的部分唯一索引）。
"""
from __future__ import annotations

import re
import sqlite3
import time
from contextlib import contextmanager

from . import links, tree
from .db import now_ms

TITLE_MAX = 80          # 笔记标题上限（字符）
CHUNK_MAX = 900         # 单块硬上限（任务要求 ≤900 字）
CHUNK_TARGET = 450      # 无标题段落的目标块长（仅影响打包观感，不是硬限制）

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_TERM_SPLIT_RE = re.compile(r"[\s,，、;；/|]+")


class NoteConflict(Exception):
    """乐观锁冲突：``expected_updated_at`` 与当前 updated_at 不一致。"""

    def __init__(self, current, expected_updated_at=None):
        self.current = current
        self.note = current
        self.expected_updated_at = expected_updated_at
        super().__init__("笔记已被其他窗口修改，请刷新后重试")


# ---------------------------------------------------------------- 基础工具
@contextmanager
def _tx(conn):
    """事务包装：外层已开启事务时复用，否则自己 BEGIN/COMMIT。"""
    if getattr(conn, "in_transaction", False):
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        conn.execute("COMMIT")


def _coerce_id(value, field: str = "id") -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 必须是整数")
    if v <= 0:
        raise ValueError(f"{field} 必须是正整数")
    return v


def _opt_id(value, field: str = "id"):
    if value is None or value == "":
        return None
    return _coerce_id(value, field)


def _like_escape(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _excerpt(body: str, n: int = 120) -> str:
    text = re.sub(r"\s+", " ", body or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------- 笔记 dict
_NOTE_SQL = (
    "SELECT n.*, "
    " (SELECT COUNT(*) FROM note_chunks c WHERE c.note_id=n.id) AS chunk_count, "
    " (SELECT COUNT(*) FROM note_links l WHERE l.note_id=n.id) AS link_count "
    "FROM notes n"
)


def _note_dict(row) -> dict:
    body = row["body_md"] or ""
    keys = row.keys() if hasattr(row, "keys") else ()
    return {
        "id": row["id"],
        "title": row["title"] or "",
        "body_md": body,
        "node_id": row["node_id"],
        "partition_id": row["partition_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
        "char_count": len(body),
        "chunk_count": row["chunk_count"] if "chunk_count" in keys else 0,
        "link_count": row["link_count"] if "link_count" in keys else 0,
        "excerpt": _excerpt(body),
    }


def _fetch_note(conn, note_id: int, include_deleted: bool = False):
    row = conn.execute(_NOTE_SQL + " WHERE n.id=?", (int(note_id),)).fetchone()
    if row is None:
        return None
    if row["deleted_at"] is not None and not include_deleted:
        return None
    return _note_dict(row)


# ---------------------------------------------------------------- 校验
def _validate_title(title) -> str:
    title = str("" if title is None else title).strip()
    if not title:
        raise ValueError("笔记标题不能为空")
    if len(title) > TITLE_MAX:
        raise ValueError(f"笔记标题不能超过 {TITLE_MAX} 个字符")
    return title


def _normalize_body(body_md) -> str:
    body = "" if body_md is None else str(body_md)
    return body.replace("\r\n", "\n").replace("\r", "\n")


def _validate_partition(conn, partition_id: int) -> int:
    partition_id = _coerce_id(partition_id, "分区 id")
    row = conn.execute(
        "SELECT id, parent_id, is_system, deleted_at FROM nodes WHERE id=?",
        (partition_id,),
    ).fetchone()
    if (row is None or row["deleted_at"] is not None
            or row["parent_id"] is not None or row["is_system"]):
        raise ValueError("分区不存在或不是有效分区（分区 = 一级非系统节点）")
    return partition_id


def _node_partition(conn, node_id: int):
    """返回 (node_row, partition_id)，节点必须存在且未删。"""
    node_id = _coerce_id(node_id, "节点 id")
    row = tree.get_node(conn, node_id)
    if row is None:
        raise ValueError("节点不存在或已删除")
    return row, tree.partition_of_node(conn, node_id)


# ---------------------------------------------------------------- Markdown 分块
def _pack(text: str, limit: int = CHUNK_MAX):
    """按段落打包成 ≤limit 的块；超长段落再按句读/硬边界切。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts = []
    for para in re.split(r"\n[ \t]*\n", text):
        para = para.strip("\n").strip()
        if para:
            parts.extend(_hard_split(para, limit))
    out, buf = [], ""
    for part in parts:
        if not buf:
            buf = part
        elif len(buf) + 2 + len(part) <= limit:
            buf = buf + "\n\n" + part
        else:
            out.append(buf)
            buf = part
    if buf:
        out.append(buf)
    # 兜底：任何一块都不超过硬上限
    final = []
    for block in out:
        final.extend(_hard_split(block, limit) if len(block) > limit else [block])
    return [b for b in final if b]


def _hard_split(text: str, limit: int = CHUNK_MAX):
    """超长文本按「换行 → 中文句读 → 硬切」拆分，保证每段 ≤limit。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    out, rest = [], text
    marks = ("\n", "。", "！", "？", "；", "…", ".", ";", "!", "?", "，", ",")
    while len(rest) > limit:
        window = rest[:limit]
        cut = limit
        for mark in marks:
            pos = window.rfind(mark)
            if pos >= int(limit * 0.6):
                cut = pos + 1
                break
        piece = rest[:cut].strip()
        if not piece:                      # 极端空白，退化为硬切
            piece = rest[:limit].strip()
            cut = limit
        out.append(piece)
        rest = rest[cut:].lstrip("\n").strip()
    if rest:
        out.append(rest)
    return [p for p in out if p]


def _sections(body: str):
    """按 ATX 标题切段，返回 [(heading_path, 内容), ...]；围栏代码里的 # 不算标题。"""
    lines = (body or "").split("\n")
    stack = []                              # [(level, title), ...]
    sections = []
    heading_path = ""
    buf = []
    in_fence = False
    fence_char, fence_len = "", 0

    def flush():
        if buf or heading_path:
            sections.append((heading_path, "\n".join(buf)))

    for line in lines:
        m = _FENCE_RE.match(line)
        if in_fence:
            buf.append(line)
            if (m and m.group(1)[0] == fence_char
                    and len(m.group(1)) >= fence_len and not m.group(2).strip()):
                in_fence = False
            continue
        if m:
            in_fence = True
            fence_char, fence_len = m.group(1)[0], len(m.group(1))
            buf.append(line)
            continue
        hm = _HEADING_RE.match(line)
        if hm:
            flush()
            level = len(hm.group(1))
            title = hm.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            heading_path = " > ".join(t for _, t in stack)
            buf = []
        else:
            buf.append(line)
    flush()
    return sections


def split_markdown(body: str, limit: int = CHUNK_MAX):
    """把 Markdown 正文拆成 [(heading_path, text), ...]，每段 text ≤limit。"""
    body = _normalize_body(body)
    out = []
    for heading_path, content in _sections(body):
        text = content.strip()
        if not text:
            if heading_path:
                # 只有标题没有正文的章节也保留一块，标题本身可被检索到
                text = heading_path.split(" > ")[-1].strip()[:limit]
            if not text:
                continue
        elif len(text) <= limit:
            out.append((heading_path, text))
            continue
        if len(text) > limit:
            for piece in _pack(text, limit):
                out.append((heading_path, piece))
        else:
            out.append((heading_path, text))
    return out


def _rebuild_chunks(conn, note_id: int, body: str) -> int:
    """重建 note_chunks；FTS 由 0007 的触发器维护（不手写 note_fts）。"""
    chunks = split_markdown(body)
    conn.execute("DELETE FROM note_chunks WHERE note_id=?", (note_id,))
    for i, (heading_path, text) in enumerate(chunks):
        conn.execute(
            "INSERT INTO note_chunks(note_id,ord,heading_path,text,char_len) "
            "VALUES(?,?,?,?,?)",
            (note_id, i, heading_path, text, len(text)),
        )
    return len(chunks)


# ---------------------------------------------------------------- CRUD
def get_note(conn, note_id: int, include_deleted: bool = False):
    """读取单条笔记；不存在（或已软删且未要求包含）返回 None。"""
    try:
        nid = int(note_id)
    except (TypeError, ValueError):
        return None
    if nid <= 0:
        return None
    return _fetch_note(conn, nid, include_deleted=include_deleted)


def list_notes(conn, partition_id=None, node_id=None, q: str = "", limit: int = 200):
    """笔记列表：按分区/节点过滤，``q`` 为标题或正文子串；最近更新在前。"""
    part = _opt_id(partition_id, "分区 id")
    node = _opt_id(node_id, "节点 id")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 500))
    where = ["n.deleted_at IS NULL"]
    args = []
    if part is not None:
        where.append("n.partition_id=?")
        args.append(part)
    if node is not None:
        where.append("n.node_id=?")
        args.append(node)
    q = str(q or "").strip()
    if q:
        pat = f"%{_like_escape(q)}%"
        where.append("(n.title LIKE ? ESCAPE '\\' OR n.body_md LIKE ? ESCAPE '\\')")
        args.extend([pat, pat])
    sql = (_NOTE_SQL + " WHERE " + " AND ".join(where)
           + " ORDER BY n.updated_at DESC, n.id DESC LIMIT ?")
    args.append(limit)
    return [_note_dict(r) for r in conn.execute(sql, args).fetchall()]


def save_note(conn, note_id=None, title="", body_md="", node_id=None,
              partition_id=None, expected_updated_at=None):
    """新建或更新笔记，事务内同步 note_chunks 与 note_links。

    - 标题 1~80 字符，全局唯一（不区分大小写）。
    - ``partition_id`` 必须是有效分区；``node_id`` 必须属于该分区。
    - 更新时若给了 ``expected_updated_at`` 且与当前不一致，抛 :class:`NoteConflict`。
    - 返回笔记 dict（含 chunk_count / link_count）。
    """
    title = _validate_title(title)
    body = _normalize_body(body_md)
    nid = None
    if note_id is not None:
        nid = _coerce_id(note_id, "笔记 id")
    existing = None
    if nid is not None:
        existing = conn.execute(
            "SELECT * FROM notes WHERE id=?", (nid,)
        ).fetchone()
        if existing is None:
            raise ValueError("笔记不存在")
        if existing["deleted_at"] is not None:
            raise ValueError("笔记已删除，请先恢复后再保存")

    if existing is not None and expected_updated_at is not None:
        try:
            expected = int(expected_updated_at)
        except (TypeError, ValueError):
            raise ValueError("expected_updated_at 不合法")
        if expected != int(existing["updated_at"]):
            raise NoteConflict(_note_dict(existing), expected)

    # ---- 分区 / 节点 ----
    eff_node = existing["node_id"] if existing is not None else None
    eff_part = existing["partition_id"] if existing is not None else None
    if partition_id is not None:
        eff_part = _validate_partition(conn, partition_id)
    node_given = node_id is not None
    if node_given:
        _, node_part = _node_partition(conn, node_id)
        if partition_id is not None and eff_part is not None and node_part != eff_part:
            raise ValueError("节点不属于该分区")
        if partition_id is None:
            eff_part = node_part
        eff_node = _coerce_id(node_id, "节点 id")
    elif existing is not None and partition_id is not None and eff_node is not None:
        # 只改分区：原节点若已不在新分区，则清空节点，避免跨分区挂载
        try:
            _, node_part = _node_partition(conn, eff_node)
        except ValueError:
            eff_node = None
        else:
            if node_part != eff_part:
                eff_node = None

    # ---- 标题唯一 ----
    dup = conn.execute(
        "SELECT id FROM notes WHERE title=? COLLATE NOCASE "
        "AND deleted_at IS NULL AND id<>?",
        (title, nid or 0),
    ).fetchone()
    if dup is not None:
        raise ValueError(f"笔记标题已存在：{title}")

    ts = now_ms()
    if existing is None:
        created_at = updated_at = ts
    else:
        created_at = int(existing["created_at"])
        # 强制单调递增：同一毫秒内的连续保存也能被乐观锁识别
        updated_at = max(ts, int(existing["updated_at"]) + 1)

    try:
        with _tx(conn):
            if existing is None:
                cur = conn.execute(
                    "INSERT INTO notes(title,body_md,node_id,partition_id,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (title, body, eff_node, eff_part, created_at, updated_at),
                )
                nid = cur.lastrowid
            else:
                conn.execute(
                    "UPDATE notes SET title=?, body_md=?, node_id=?, partition_id=?, "
                    "updated_at=? WHERE id=?",
                    (title, body, eff_node, eff_part, updated_at, nid),
                )
            _rebuild_chunks(conn, nid, body)
            links.sync_links(conn, nid, body)
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if "ux_note_title" in msg or ("notes" in msg and "title" in msg and "UNIQUE" in msg):
            raise ValueError(f"笔记标题已存在：{title}") from e
        raise
    return _fetch_note(conn, nid)


def delete_note(conn, note_id: int):
    """软删除笔记：清空派生 note_chunks/FTS，指向它的链接标为未解析。"""
    nid = _coerce_id(note_id, "笔记 id")
    row = conn.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if row is None:
        raise ValueError("笔记不存在")
    current = _fetch_note(conn, nid, include_deleted=True)
    if row["deleted_at"] is not None:
        return current
    ts = max(now_ms(), int(row["updated_at"] or 0) + 1)
    with _tx(conn):
        conn.execute(
            "UPDATE notes SET deleted_at=?, updated_at=? WHERE id=?", (ts, ts, nid)
        )
        conn.execute("DELETE FROM note_chunks WHERE note_id=?", (nid,))
        # 保留目标信息，但把指向本文的链接标为未解析；恢复时再回填
        conn.execute(
            "UPDATE note_links SET resolved=0 "
            "WHERE target_kind='note' AND target_id=?",
            (nid,),
        )
    return _fetch_note(conn, nid, include_deleted=True)


def restore_note(conn, note_id: int):
    """恢复软删笔记：校验标题不冲突，重建 chunks 与 links，回填入边 resolved。"""
    nid = _coerce_id(note_id, "笔记 id")
    row = conn.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    if row is None:
        raise ValueError("笔记不存在")
    if row["deleted_at"] is None:
        return _fetch_note(conn, nid)
    conflict = conn.execute(
        "SELECT id FROM notes WHERE title=? COLLATE NOCASE "
        "AND deleted_at IS NULL AND id<>?",
        (row["title"], nid),
    ).fetchone()
    if conflict is not None:
        raise ValueError(f"标题已被其他笔记占用，无法恢复：{row['title']}")
    ts = max(now_ms(), int(row["updated_at"] or 0) + 1)
    body = row["body_md"] or ""
    with _tx(conn):
        conn.execute(
            "UPDATE notes SET deleted_at=NULL, updated_at=? WHERE id=?", (ts, nid)
        )
        _rebuild_chunks(conn, nid, body)
        links.sync_links(conn, nid, body)
        conn.execute(
            "UPDATE note_links SET resolved=1 "
            "WHERE target_kind='note' AND target_id=?",
            (nid,),
        )
    return _fetch_note(conn, nid)


# ---------------------------------------------------------------- 检索
def _terms(query: str):
    q = str(query or "").strip()
    if not q:
        return []
    seen, out = set(), []
    for part in _TERM_SPLIT_RE.split(q):
        part = part.strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            out.append(part)
    return out[:8]


def _snippet(text: str, terms, width: int = 60) -> str:
    text = (text or "").replace("\r", " ").replace("\n", " ")
    low = text.lower()
    pos, mterm = -1, ""
    for term in sorted(terms, key=len, reverse=True):
        p = low.find(term.lower())
        if p >= 0:
            pos, mterm = p, term
            break
    if pos < 0:
        frag = text[: width * 2].strip()
        return frag + ("…" if len(text) > len(frag) else "")
    start = max(0, pos - width // 2)
    end = min(len(text), pos + len(mterm) + width)
    frag = text[start:end].strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


def search_notes(conn, q: str, partition_id=None, limit: int = 20):
    """笔记全文检索：≥3 字走 FTS5 trigram，<3 字走 LIKE 兜底，结果按笔记聚合。"""
    terms = _terms(q)
    if not terms:
        return []
    part = _opt_id(partition_id, "分区 id")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    part_sql = " AND n.partition_id=?" if part is not None else ""
    part_args = (part,) if part is not None else ()

    hits = {}

    def add_hit(note_id, term, rank=None, chunk=None, title_hit=False):
        e = hits.setdefault(note_id, {"terms": set(), "rank": 0.0,
                                      "chunk": None, "title": False})
        e["terms"].add(term)
        if title_hit:
            e["title"] = True
        if rank is not None and rank < e["rank"]:
            e["rank"] = rank
        if chunk is not None and e["chunk"] is None:
            e["chunk"] = chunk

    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]

    for term in long_terms:
        matched = False
        phrase = '"' + term.replace('"', '""') + '"'
        try:
            rows = conn.execute(
                "SELECT nc.id, nc.note_id, nc.heading_path, nc.text, "
                "       bm25(note_fts) AS rank "
                "FROM note_fts JOIN note_chunks nc ON nc.id=note_fts.rowid "
                "JOIN notes n ON n.id=nc.note_id "
                "WHERE note_fts MATCH ? AND n.deleted_at IS NULL" + part_sql +
                " ORDER BY rank LIMIT 100",
                (phrase,) + part_args,
            ).fetchall()
            matched = bool(rows)
            for r in rows:
                add_hit(r["note_id"], term, rank=float(r["rank"] or 0.0),
                        chunk={"id": r["id"], "heading_path": r["heading_path"] or "",
                               "text": r["text"] or ""})
        except sqlite3.Error:
            matched = False
        if not matched:                       # FTS 不可用/无命中：LIKE 兜底
            short_terms.append(term)

    for term in short_terms:
        pat = f"%{_like_escape(term)}%"
        rows = conn.execute(
            "SELECT nc.id, nc.note_id, nc.heading_path, nc.text "
            "FROM note_chunks nc JOIN notes n ON n.id=nc.note_id "
            "WHERE n.deleted_at IS NULL AND "
            "(nc.text LIKE ? ESCAPE '\\' OR nc.heading_path LIKE ? ESCAPE '\\')"
            + part_sql + " ORDER BY nc.note_id, nc.ord LIMIT 200",
            (pat, pat) + part_args,
        ).fetchall()
        for r in rows:
            add_hit(r["note_id"], term,
                    chunk={"id": r["id"], "heading_path": r["heading_path"] or "",
                           "text": r["text"] or ""})

    # 标题命中（即使正文没有也可返回）
    for term in terms:
        pat = f"%{_like_escape(term)}%"
        rows = conn.execute(
            "SELECT n.id FROM notes n WHERE n.deleted_at IS NULL "
            "AND n.title LIKE ? ESCAPE '\\'" + part_sql,
            (pat,) + part_args,
        ).fetchall()
        for r in rows:
            add_hit(r["id"], term, title_hit=True)

    if not hits:
        return []
    ids = list(hits.keys())
    qs = ",".join("?" * len(ids))
    meta = {r["id"]: r for r in conn.execute(
        "SELECT id, title, node_id, partition_id, updated_at FROM notes "
        f"WHERE id IN ({qs}) AND deleted_at IS NULL", ids)}
    items = []
    for note_id, e in hits.items():
        n = meta.get(note_id)
        if n is None:
            continue
        chunk = e["chunk"] or {}
        heading = chunk.get("heading_path") or ""
        text = chunk.get("text") or ""
        snippet_src = ((heading + " ") if heading else "") + text
        if not snippet_src.strip():
            snippet_src = n["title"] or ""
        score = len(e["terms"]) * 10.0 + (6.0 if e["title"] else 0.0) - e["rank"]
        items.append({
            "id": note_id,
            "title": n["title"] or "",
            "partition_id": n["partition_id"],
            "node_id": n["node_id"],
            "updated_at": n["updated_at"],
            "chunk_id": chunk.get("id"),
            "heading_path": heading,
            "snippet": _snippet(snippet_src, terms),
            "matched_terms": sorted(e["terms"]),
            "title_hit": bool(e["title"]),
            "score": round(score, 4),
        })
    items.sort(key=lambda x: (-int(x["title_hit"]), -len(x["matched_terms"]),
                              -(x["score"]), -int(x["updated_at"] or 0)))
    return items[:limit]
