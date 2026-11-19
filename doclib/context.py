# -*- coding: utf-8 -*-
"""AI 上下文归一化：partition / node / document / selection / note。

原则：
- 前端显示的“范围”必须对应真实请求体；这里做服务端校验。
- document/selection 只在该文档内检索；不静默扩大到全库。
- 选文/笔记进入 chunks 时带 source_kind，引用可区分。
"""
from __future__ import annotations

from typing import Optional

from . import tree


class ContextError(ValueError):
    pass


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _partition_of_doc(conn, doc_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT nd.node_id FROM node_documents nd "
        "JOIN nodes n ON n.id=nd.node_id AND n.deleted_at IS NULL "
        "WHERE nd.document_id=? ORDER BY nd.node_id LIMIT 1", (doc_id,)
    ).fetchone()
    if row is None:
        return None
    return tree.partition_of_node(conn, row["node_id"])


def _validate_partition(conn, pid: Optional[int]) -> Optional[int]:
    if pid is None:
        return None
    node = tree.get_node(conn, pid)
    if node is None or node["deleted_at"] is not None:
        raise ContextError("分区不存在")
    if node["parent_id"] is not None or node["is_system"]:
        raise ContextError("分区必须是一级非系统节点")
    return pid


def normalize(conn, raw) -> Optional[dict]:
    """返回安全 context；raw 为空返回 None（旧行为）。"""
    if not isinstance(raw, dict) or not raw:
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    if not kind:
        if raw.get("doc_id"):
            kind = "selection" if str(raw.get("quote") or "").strip() else "document"
        elif raw.get("note_id"):
            kind = "note"
        elif raw.get("node_id"):
            kind = "node"
        elif raw.get("partition_id"):
            kind = "partition"
    if kind not in ("partition", "node", "document", "selection", "note"):
        raise ContextError("context.kind 不合法")

    partition_id = _validate_partition(conn, _int(raw.get("partition_id")))
    node_id = _int(raw.get("node_id"))
    doc_id = _int(raw.get("doc_id"))
    note_id = _int(raw.get("note_id"))
    chunk_id = _int(raw.get("chunk_id"))
    quote = str(raw.get("quote") or "")[:8000]
    heading_path = str(raw.get("heading_path") or "")[:500]

    if kind == "partition":
        if partition_id is None:
            raise ContextError("缺少分区")
        if doc_id or note_id:
            raise ContextError("分区上下文不能同时带文档/笔记")
        node_id = None

    elif kind == "node":
        if node_id is None:
            raise ContextError("缺少节点")
        node = tree.get_node(conn, node_id)
        if node is None or node["deleted_at"] is not None:
            raise ContextError("节点不存在")
        part = tree.partition_of_node(conn, node_id)
        if partition_id is not None and part is not None and partition_id != part:
            raise ContextError("节点不属于该分区")
        partition_id = part

    elif kind in ("document", "selection"):
        if doc_id is None:
            raise ContextError("缺少文档")
        doc = conn.execute(
            "SELECT id, title FROM documents WHERE id=? AND deleted_at IS NULL",
            (doc_id,)).fetchone()
        if doc is None:
            raise ContextError("文档不存在")
        part = _partition_of_doc(conn, doc_id)
        if partition_id is not None and part is not None and partition_id != part:
            raise ContextError("文档不属于该分区")
        partition_id = part
        if kind == "selection":
            if not quote.strip():
                raise ContextError("选文为空")
            if chunk_id is not None:
                ch = conn.execute(
                    "SELECT id FROM doc_chunks WHERE id=? AND doc_id=?",
                    (chunk_id, doc_id)).fetchone()
                if ch is None:
                    raise ContextError("选文片段不属于该文档")
        else:
            chunk_id = None
            quote = ""
        node_id = None

    elif kind == "note":
        if note_id is None:
            raise ContextError("缺少笔记")
        note = conn.execute(
            "SELECT id, title, partition_id FROM notes WHERE id=? AND deleted_at IS NULL",
            (note_id,)).fetchone()
        if note is None:
            raise ContextError("笔记不存在")
        if partition_id is not None and note["partition_id"] is not None \
                and int(partition_id) != int(note["partition_id"]):
            raise ContextError("笔记不属于该分区")
        partition_id = note["partition_id"] if note["partition_id"] is not None else partition_id
        node_id = None
        doc_id = None
        quote = ""

    label = {
        "partition": "当前分区",
        "node": "当前节点",
        "document": "当前文档",
        "selection": "选中文字",
        "note": "当前笔记",
    }[kind]
    target = ""
    if kind == "partition" and partition_id:
        row = conn.execute("SELECT name FROM nodes WHERE id=?", (partition_id,)).fetchone()
        target = row["name"] if row else ""
    elif kind == "node" and node_id:
        row = conn.execute("SELECT name FROM nodes WHERE id=?", (node_id,)).fetchone()
        target = row["name"] if row else ""
    elif kind in ("document", "selection") and doc_id:
        row = conn.execute("SELECT title FROM documents WHERE id=?", (doc_id,)).fetchone()
        target = row["title"] if row else ""
    elif kind == "note" and note_id:
        row = conn.execute("SELECT title FROM notes WHERE id=?", (note_id,)).fetchone()
        target = row["title"] if row else ""

    return {
        "kind": kind,
        "partition_id": partition_id,
        "node_id": node_id,
        "doc_id": doc_id,
        "note_id": note_id,
        "chunk_id": chunk_id,
        "quote": quote,
        "heading_path": heading_path,
        "label": f"{label} · {target}" if target else label,
    }
