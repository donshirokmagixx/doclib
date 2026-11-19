# -*- coding: utf-8 -*-
"""双链（wikilink）解析、解析落库、反向链接与人工关系。

设计要点
--------
- ``parse_wikilinks`` 是纯函数：不查库，输出 offsets/raw，供编辑器高亮与保存落库共用；
  fenced code block（``` / ~~~）与行内 code span（`...`）里的 ``[[...]]`` 不解析。
- ``sync_links`` 在事务内先删后插：稳定 ID 链接校验实体存在且未软删；
  标题式链接按「唯一笔记标题 → 唯一文档标题 → 唯一节点名」解析，歧义/未找到保留为未解析
  （``resolved=0`` 且 ``target_kind/target_id=NULL``）。
- ``backlinks`` 合并 ``note_links``（wikilink）与 ``relations``（人工/AI 关系）；
  被查询实体或其另一端已删除时 ``deleted=True``。
- 关系写入前校验两端实体；唯一键 (src,dst,rel,origin) 命中时更新，不产生重复行。

字段口径
--------
- 稳定 ID 写法 ``[[note:12|标题]]``：``target_kind/target_id`` 直接给出，``|`` 后文本先记在
  ``target_title``（同时作为 ``alias`` 输出）；落库时 ``target_title`` 会换成目标实体真实标题。
- 标题式写法 ``[[标题]]`` / ``[[标题#章节]]`` / ``[[标题|别名]]``：``target_title`` 是待解析标题，
  ``alias`` 是显示别名；``heading`` 是 ``#`` 后的章节。
"""
from __future__ import annotations

import math
import re
import sqlite3
from contextlib import contextmanager

from .db import now_ms

KINDS = ("node", "document", "note")
_KIND_ALIASES = {"note": "note", "doc": "document", "document": "document", "node": "node"}
_KIND_TABLE = {
    "note": ("notes", "title"),
    "document": ("documents", "title"),
    "node": ("nodes", "name"),
}

# [[...]]：不允许跨行、不允许内部再出现方括号（Obsidian 也基本如此）
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
# 稳定 ID：note:12 / doc:34 / document:34 / node:7（大小写不敏感）
_STABLE_RE = re.compile(r"^\s*(note|doc|document|node)\s*:\s*(\d+)\s*$", re.I)
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")


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


def _like_escape(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _coerce_id(value, field: str = "id") -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 必须是整数")
    if v <= 0:
        raise ValueError(f"{field} 必须是正整数")
    return v


def _norm_kind(kind) -> str:
    k = str(kind or "").strip().lower()
    k = _KIND_ALIASES.get(k, k)
    if k not in KINDS:
        raise ValueError("实体类型必须是 node / document / note")
    return k


def _in_ranges(pos: int, ranges) -> bool:
    for a, b in ranges:
        if a <= pos < b:
            return True
    return False


def _code_ranges(text: str):
    """返回 fenced code block 与行内 code span 的 [(start, end), ...]。"""
    ranges = []
    pos = 0
    fence = None          # (char, length, start)
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = _FENCE_RE.match(body)
        if fence is None:
            if m:
                fence = (m.group(1)[0], len(m.group(1)), pos)
        else:
            if (m and m.group(1)[0] == fence[0]
                    and len(m.group(1)) >= fence[1]
                    and not m.group(2).strip()):
                ranges.append((fence[2], pos + len(line)))
                fence = None
        pos += len(line)
    if fence is not None:                     # 未闭合的围栏：一直吃到文末
        ranges.append((fence[2], len(text)))

    # 行内代码逐行扫描（围栏行整体跳过）
    pos = 0
    for line in text.splitlines(keepends=True):
        if not _in_ranges(pos, ranges):
            for m in _INLINE_CODE_RE.finditer(line):
                ranges.append((pos + m.start(), pos + m.end()))
        pos += len(line)
    return ranges


def _snippet(body: str, start, end, width: int = 36) -> str:
    body = body or ""
    if not body:
        return ""
    try:
        s = max(0, min(int(start or 0), len(body)))
        e = max(s, min(int(end if end is not None else s), len(body)))
    except (TypeError, ValueError):
        s, e = 0, 0
    a = max(0, s - width)
    b = min(len(body), e + width)
    frag = body[a:b].replace("\r", " ").replace("\n", " ").strip()
    return ("…" if a > 0 else "") + frag + ("…" if b < len(body) else "")


# ---------------------------------------------------------------- 纯函数：解析
def parse_wikilinks(text: str):
    """解析 Markdown 里的 wikilink，返回带 offsets 的列表（不查库）。

    每项字段：``start_off`` / ``end_off``（半开区间，``text[start:end] == raw``）、
    ``raw``、``target_kind``、``target_id``、``target_title``、``heading``、``alias``、
    ``embed``（``![[...]]`` 时为 True）。
    """
    text = "" if text is None else str(text)
    if "[[" not in text:
        return []
    skip = _code_ranges(text)
    out = []
    for m in _WIKILINK_RE.finditer(text):
        if _in_ranges(m.start(), skip):
            continue
        inner = m.group(1).strip()
        if not inner:
            continue
        target_part, has_alias, alias = inner.partition("|")
        title_part, has_heading, heading = target_part.partition("#")
        target_title = title_part.strip()
        alias = alias.strip() if has_alias else ""
        heading = heading.strip() if has_heading else ""
        stable = _STABLE_RE.match(target_title)
        if stable:
            target_kind = _KIND_ALIASES[stable.group(1).lower()]
            target_id = int(stable.group(2))
            # 稳定 ID 写法里 "|" 后是显示标题；解析落库时会替换成真实标题
            target_title = alias or ""
        else:
            target_kind, target_id = None, None
        start, end = m.start(), m.end()
        out.append({
            "start_off": start,
            "end_off": end,
            "raw": text[start:end],
            "target_kind": target_kind,
            "target_id": target_id,
            "target_title": target_title,
            "heading": heading,
            "alias": alias,
            "embed": start > 0 and text[start - 1] == "!",
        })
    return out


# ---------------------------------------------------------------- 解析目标
def _entity_row(conn, kind: str, entity_id: int):
    table, col = _KIND_TABLE[kind]
    return conn.execute(
        f"SELECT id, {col} AS title, deleted_at FROM {table} WHERE id=?",
        (int(entity_id),),
    ).fetchone()


def _entity_state(conn, kind: str, entity_id: int):
    """返回 (alive, title)。实体不存在或已软删时 alive=False。"""
    if kind not in KINDS or not entity_id:
        return False, ""
    row = _entity_row(conn, kind, int(entity_id))
    if row is None:
        return False, ""
    return row["deleted_at"] is None, (row["title"] or "")


def _title_rows(conn, kind: str, title: str):
    table, col = _KIND_TABLE[kind]
    return conn.execute(
        f"SELECT id, {col} AS title FROM {table} "
        f"WHERE {col}=? COLLATE NOCASE AND deleted_at IS NULL",
        (title,),
    ).fetchall()


def _resolve_title(conn, title: str) -> dict:
    """标题式解析：唯一笔记标题 → 唯一文档标题 → 唯一节点名。

    某一级出现多个同名候选时停止并把链接标为未解析（不自动选一个）。
    """
    title = (title or "").strip()
    if not title:
        return {"resolved": False, "target_kind": None, "target_id": None,
                "target_title": "", "ambiguous": False}
    for kind in ("note", "document", "node"):
        rows = _title_rows(conn, kind, title)
        if len(rows) == 1:
            return {"resolved": True, "target_kind": kind, "target_id": rows[0]["id"],
                    "target_title": rows[0]["title"] or title, "ambiguous": False}
        if len(rows) > 1:
            return {"resolved": False, "target_kind": None, "target_id": None,
                    "target_title": title, "ambiguous": True}
    return {"resolved": False, "target_kind": None, "target_id": None,
            "target_title": title, "ambiguous": False}


def _resolve_link(conn, link: dict) -> dict:
    kind = link.get("target_kind")
    if kind in KINDS and link.get("target_id"):
        row = _entity_row(conn, kind, int(link["target_id"]))
        if row is not None and row["deleted_at"] is None:
            return {"resolved": True, "target_kind": kind, "target_id": row["id"],
                    "target_title": row["title"] or "", "ambiguous": False}
        return {"resolved": False, "target_kind": None, "target_id": None,
                "target_title": link.get("target_title") or link.get("alias") or "",
                "ambiguous": False}
    return _resolve_title(conn, link.get("target_title") or "")


def resolve_target(conn, link: dict) -> dict:
    """公开的单条解析入口（编辑器补全/未解析提示可复用）。"""
    return _resolve_link(conn, link)


# ---------------------------------------------------------------- 落库
def sync_links(conn, note_id: int, body: str):
    """重建某条笔记的 note_links（先删旧行，再解析并插入）。

    不手写 note_fts；本函数只维护 note_links。返回写入后的链接 dict 列表。
    """
    note_id = _coerce_id(note_id, "笔记 id")
    body = "" if body is None else str(body)
    parsed = parse_wikilinks(body)
    ts = now_ms()
    rows = []
    with _tx(conn):
        conn.execute("DELETE FROM note_links WHERE note_id=?", (note_id,))
        for link in parsed:
            res = _resolve_link(conn, link)
            cur = conn.execute(
                "INSERT INTO note_links(note_id,target_kind,target_id,target_title,"
                "heading,alias,start_off,end_off,resolved,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (note_id, res["target_kind"], res["target_id"],
                 res["target_title"] or "", link["heading"], link["alias"],
                 link["start_off"], link["end_off"], 1 if res["resolved"] else 0, ts),
            )
            rows.append({
                "id": cur.lastrowid,
                "note_id": note_id,
                "target_kind": res["target_kind"],
                "target_id": res["target_id"],
                "target_title": res["target_title"] or "",
                "heading": link["heading"],
                "alias": link["alias"],
                "start_off": link["start_off"],
                "end_off": link["end_off"],
                "resolved": 1 if res["resolved"] else 0,
                "raw": link["raw"],
            })
    return rows


def list_note_links(conn, note_id: int):
    """读取某条笔记当前的 note_links（不含 raw，按 offset 排序）。"""
    note_id = _coerce_id(note_id, "笔记 id")
    rows = conn.execute(
        "SELECT * FROM note_links WHERE note_id=? ORDER BY start_off, id", (note_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 弱解析：反链
def _relation_dict(row) -> dict:
    return {
        "id": row["id"],
        "relation_id": row["id"],
        "src_kind": row["src_kind"], "src_id": row["src_id"],
        "dst_kind": row["dst_kind"], "dst_id": row["dst_id"],
        "rel": row["rel"], "label": row["label"], "origin": row["origin"],
        "confidence": float(row["confidence"] or 0.0),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def backlinks(conn, kind: str, entity_id: int):
    """反向链接：incoming/outgoing × wikilink/relation，返回扁平列表。

    - incoming wikilink：其他笔记指向本实体的 note_links（含来源笔记标题、heading、
      alias 与链接附近 snippet）。
    - outgoing wikilink：仅 ``kind="note"`` 时给出该笔记指向的目标。
    - relations：两端任一命中即返回（manual / ai / import 都带 origin）。
    - 被查询实体本身已删除，或条目另一端已删除时 ``deleted=True``。
    """
    kind = _norm_kind(kind)
    entity_id = _coerce_id(entity_id, "实体 id")
    target_alive, _target_title = _entity_state(conn, kind, entity_id)
    target_deleted = not target_alive
    out = []

    # 1) incoming wikilinks（来源笔记必须未删除）
    rows = conn.execute(
        "SELECT nl.*, n.title AS note_title, n.body_md AS note_body, "
        "       n.updated_at AS note_updated_at "
        "FROM note_links nl JOIN notes n ON n.id=nl.note_id "
        "WHERE nl.target_kind=? AND nl.target_id=? AND n.deleted_at IS NULL "
        "ORDER BY n.updated_at DESC, nl.id",
        (kind, entity_id),
    ).fetchall()
    for r in rows:
        out.append({
            "direction": "incoming",
            "via": "wikilink",
            "kind": "note", "id": r["note_id"], "title": r["note_title"] or "",
            "note_id": r["note_id"], "note_title": r["note_title"] or "",
            "heading": r["heading"] or "", "alias": r["alias"] or "",
            "target_kind": kind, "target_id": entity_id,
            "target_title": r["target_title"] or "",
            "snippet": _snippet(r["note_body"], r["start_off"], r["end_off"]),
            "resolved": bool(r["resolved"]) and not target_deleted,
            "deleted": target_deleted,
            "updated_at": r["note_updated_at"],
        })

    # 2) incoming relations（另一方是 src）
    rows = conn.execute(
        "SELECT * FROM relations WHERE deleted_at IS NULL AND dst_kind=? AND dst_id=? "
        "ORDER BY created_at DESC, id DESC",
        (kind, entity_id),
    ).fetchall()
    for r in rows:
        other_kind, other_id = r["src_kind"], r["src_id"]
        alive, title = _entity_state(conn, other_kind, other_id)
        item = _relation_dict(r)
        item.update({
            "direction": "incoming", "via": "relation",
            "kind": other_kind, "id": other_id, "title": title,
            "other_kind": other_kind, "other_id": other_id, "other_title": title,
            "deleted": target_deleted or not alive,
            "resolved": alive,
        })
        out.append(item)

    # 3) outgoing wikilinks（仅笔记）
    if kind == "note":
        note = conn.execute(
            "SELECT id, title, body_md, updated_at FROM notes "
            "WHERE id=? AND deleted_at IS NULL", (entity_id,)
        ).fetchone()
        if note is not None:
            rows = conn.execute(
                "SELECT * FROM note_links WHERE note_id=? ORDER BY start_off, id",
                (entity_id,),
            ).fetchall()
            for r in rows:
                tk, tid = r["target_kind"], r["target_id"]
                if tk in KINDS and tid:
                    alive, title = _entity_state(conn, tk, tid)
                else:
                    alive, title = False, ""
                out.append({
                    "direction": "outgoing",
                    "via": "wikilink",
                    "kind": tk if tk in KINDS else None,
                    "id": tid if tk in KINDS else None,
                    "title": title or r["target_title"] or r["alias"] or "未解析",
                    "target_kind": tk, "target_id": tid,
                    "target_title": r["target_title"] or "",
                    "heading": r["heading"] or "", "alias": r["alias"] or "",
                    "snippet": _snippet(note["body_md"], r["start_off"], r["end_off"]),
                    "resolved": bool(r["resolved"]) and alive,
                    "deleted": (not alive) if (tk in KINDS and tid) else False,
                    "updated_at": note["updated_at"],
                })

    # 4) outgoing relations（本实体是 src）
    rows = conn.execute(
        "SELECT * FROM relations WHERE deleted_at IS NULL AND src_kind=? AND src_id=? "
        "ORDER BY created_at DESC, id DESC",
        (kind, entity_id),
    ).fetchall()
    for r in rows:
        # 自反关系只在 incoming 出现一次，避免重复
        if r["src_kind"] == kind and r["src_id"] == entity_id \
                and r["dst_kind"] == kind and r["dst_id"] == entity_id:
            continue
        other_kind, other_id = r["dst_kind"], r["dst_id"]
        alive, title = _entity_state(conn, other_kind, other_id)
        item = _relation_dict(r)
        item.update({
            "direction": "outgoing", "via": "relation",
            "kind": other_kind, "id": other_id, "title": title,
            "other_kind": other_kind, "other_id": other_id, "other_title": title,
            "deleted": target_deleted or not alive,
            "resolved": alive,
        })
        out.append(item)

    return out


# ---------------------------------------------------------------- 关系 CRUD
def get_relation(conn, relation_id: int):
    relation_id = _coerce_id(relation_id, "关系 id")
    row = conn.execute(
        "SELECT * FROM relations WHERE id=? AND deleted_at IS NULL", (relation_id,)
    ).fetchone()
    return _relation_dict(row) if row else None


def save_relation(conn, src_kind: str, src_id: int, dst_kind: str, dst_id: int,
                  rel: str = "related", label: str = "", origin: str = "manual",
                  confidence: float = 1.0):
    """新建/更新一条人工（或 AI/导入）关系，返回关系 dict。

    唯一键 (src_kind,src_id,dst_kind,dst_id,rel,origin) 已存在时更新 label/confidence；
    软删过的同一关系会被复活而不是重复插入。
    """
    src_kind = _norm_kind(src_kind)
    dst_kind = _norm_kind(dst_kind)
    src_id = _coerce_id(src_id, "源实体 id")
    dst_id = _coerce_id(dst_id, "目标实体 id")
    rel = str(rel or "").strip()[:20] or "related"
    label = str(label or "").strip()[:200]
    origin = str(origin or "manual").strip().lower()
    if origin not in ("manual", "ai", "import"):
        raise ValueError("origin 必须是 manual / ai / import")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise ValueError("confidence 必须是 0~1 的数字")
    if not math.isfinite(confidence):
        raise ValueError("confidence 必须是 0~1 的数字")
    confidence = min(1.0, max(0.0, confidence))

    for k, i, name in ((src_kind, src_id, "源实体"), (dst_kind, dst_id, "目标实体")):
        alive, _ = _entity_state(conn, k, i)
        if not alive:
            raise ValueError(f"{name}不存在或已删除")

    ts = now_ms()
    with _tx(conn):
        row = conn.execute(
            "SELECT * FROM relations WHERE src_kind=? AND src_id=? AND dst_kind=? "
            "AND dst_id=? AND rel=? AND origin=? AND deleted_at IS NULL",
            (src_kind, src_id, dst_kind, dst_id, rel, origin),
        ).fetchone()
        if row is not None:
            relation_id = row["id"]
            conn.execute(
                "UPDATE relations SET label=?, confidence=?, updated_at=? WHERE id=?",
                (label, confidence, ts, relation_id),
            )
        else:
            dead = conn.execute(
                "SELECT id FROM relations WHERE src_kind=? AND src_id=? AND dst_kind=? "
                "AND dst_id=? AND rel=? AND origin=? AND deleted_at IS NOT NULL "
                "ORDER BY id DESC LIMIT 1",
                (src_kind, src_id, dst_kind, dst_id, rel, origin),
            ).fetchone()
            if dead is not None:
                relation_id = dead["id"]
                conn.execute(
                    "UPDATE relations SET label=?, confidence=?, deleted_at=NULL, "
                    "updated_at=? WHERE id=?",
                    (label, confidence, ts, relation_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO relations(src_kind,src_id,dst_kind,dst_id,rel,label,"
                    "origin,confidence,evidence_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'{}',?,?)",
                    (src_kind, src_id, dst_kind, dst_id, rel, label,
                     origin, confidence, ts, ts),
                )
                relation_id = cur.lastrowid
    return get_relation(conn, relation_id)


def delete_relation(conn, relation_id: int) -> bool:
    """软删除一条关系；不存在抛 ValueError，已删返回 False。"""
    relation_id = _coerce_id(relation_id, "关系 id")
    row = conn.execute(
        "SELECT * FROM relations WHERE id=?", (relation_id,)
    ).fetchone()
    if row is None:
        raise ValueError("关系不存在")
    if row["deleted_at"] is not None:
        return False
    ts = max(now_ms(), int(row["updated_at"] or 0) + 1)
    with _tx(conn):
        conn.execute(
            "UPDATE relations SET deleted_at=?, updated_at=? WHERE id=?",
            (ts, ts, relation_id),
        )
    return True


def list_relations(conn, kind: str, entity_id: int):
    """列出与某实体相关的全部关系（含方向与另一端状态）。"""
    kind = _norm_kind(kind)
    entity_id = _coerce_id(entity_id, "实体 id")
    rows = conn.execute(
        "SELECT * FROM relations WHERE deleted_at IS NULL AND "
        "((src_kind=? AND src_id=?) OR (dst_kind=? AND dst_id=?)) "
        "ORDER BY updated_at DESC, id DESC",
        (kind, entity_id, kind, entity_id),
    ).fetchall()
    out = []
    for r in rows:
        if r["src_kind"] == kind and r["src_id"] == entity_id:
            direction = "outgoing"
            other_kind, other_id = r["dst_kind"], r["dst_id"]
        else:
            direction = "incoming"
            other_kind, other_id = r["src_kind"], r["src_id"]
        alive, title = _entity_state(conn, other_kind, other_id)
        item = _relation_dict(r)
        item.update({
            "direction": direction,
            "other_kind": other_kind, "other_id": other_id,
            "other_title": title, "deleted": not alive,
        })
        out.append(item)
    return out
