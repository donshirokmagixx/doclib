# -*- coding: utf-8 -*-
"""DocLib 2.0 API（/api/v2/*）。

只做参数校验与装配；业务在 graph/notebook/links/reader/workspace。
旧 /api/* 与 /api/rev/* 保持不变。
"""
from __future__ import annotations

import json
import urllib.parse

from .. import config, db, mindmap, search, system, tree, workspace


def _first(query: dict, key: str, default=None):
    v = query.get(key)
    if isinstance(v, list) and v:
        return v[0]
    return v if v is not None else default


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _bool(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def _ok(**kw):
    out = {"ok": True}
    out.update(kw)
    return out


def _err(msg: str):
    return {"ok": False, "error": msg}


def _graph(conn, query: dict):
    try:
        from .. import graph
    except Exception as e:  # 模块尚未安装/导入失败
        return _err(f"图谱模块不可用：{e}")
    scope = str(_first(query, "scope", "global") or "global").lower()
    if scope not in ("global", "partition", "local"):
        return _err("scope 必须是 global / partition / local")
    types = str(_first(query, "types", "node,document,note") or "").strip()
    rels = str(_first(query, "rels", "hierarchy,mount,manual,wikilink") or "").strip()
    return graph.build_graph(
        conn,
        scope=scope,
        partition_id=_int(_first(query, "partition")),
        center=_first(query, "center"),
        depth=_int(_first(query, "depth"), 1) or 1,
        types=types,
        rels=rels,
        q=str(_first(query, "q", "") or ""),
        limit=_int(_first(query, "limit"), 1500) or 1500,
    )


def _bootstrap(conn, query: dict):
    part = _int(_first(query, "partition"))
    parts = tree.list_partitions(conn)
    if part is None:
        with_docs = [p for p in parts if p.get("doc_count")]
        part = with_docs[0]["id"] if with_docs else (parts[0]["id"] if parts else None)
    from ..ai import gateway
    try:
        prov = gateway.load_provider(conn)
        current = prov.name if prov else ""
    except Exception:
        current = ""
    try:
        providers = gateway.provider_summary(conn)
    except Exception:
        providers = []
    return _ok(
        build=system.health(conn).get("build") or "",
        partitions=parts,
        partition=part,
        tree=tree.tree_json(conn, part),
        stats=search.stats(conn),
        workspace=workspace.load(),
        maps=mindmap.list_maps(),
        providers=providers,
        current_provider=current,
        health=system.health(conn),
    )


def _reader(conn, path: str, query: dict):
    try:
        from .. import reader
    except Exception as e:
        return _err(f"阅读器模块不可用：{e}")
    doc_id = _int(path.rsplit("/", 1)[-1])
    if not doc_id:
        return _err("文档 id 不合法")
    around = _int(_first(query, "around"))
    limit = _int(_first(query, "limit"), 200) or 200
    try:
        if path.startswith("/api/v2/reader/"):
            return reader.reader_payload(conn, doc_id, around=around, limit=limit)
        if path.startswith("/api/v2/raw/"):
            return reader.raw_text(conn, doc_id)
    except Exception as e:
        return _err(str(e))
    return _err("未知阅读路由")


def _notes(conn, method: str, path: str, query: dict, body: dict):
    try:
        from .. import notebook
    except Exception as e:
        return _err(f"笔记模块不可用：{e}")
    try:
        if method == "GET" and path == "/api/v2/notes":
            return _ok(items=notebook.list_notes(
                conn,
                partition_id=_int(_first(query, "partition")),
                node_id=_int(_first(query, "node")),
                q=str(_first(query, "q", "") or ""),
                limit=_int(_first(query, "limit"), 200) or 200,
            ))
        if method == "GET" and path == "/api/v2/notes/search":
            q = str(_first(query, "q", "") or "").strip()
            if not q:
                return _err("请输入搜索词")
            return _ok(q=q, items=notebook.search_notes(
                conn, q, partition_id=_int(_first(query, "partition")),
                limit=_int(_first(query, "limit"), 20) or 20))
        if method == "GET" and path.startswith("/api/v2/notes/"):
            nid = _int(path.rsplit("/", 1)[-1])
            if not nid:
                return _err("笔记 id 不合法")
            data = notebook.get_note(conn, nid)
            return _ok(note=data) if data else _err("笔记不存在")
        if method == "POST" and path == "/api/v2/notes/save":
            return _ok(note=notebook.save_note(
                conn,
                note_id=_int(body.get("note_id")),
                title=str(body.get("title") or ""),
                body_md=str(body.get("body_md") or ""),
                node_id=_int(body.get("node_id")),
                partition_id=_int(body.get("partition_id")),
                expected_updated_at=_int(body.get("expected_updated_at")),
            ))
        if method == "POST" and path == "/api/v2/notes/delete":
            nid = _int(body.get("id"))
            if not nid:
                return _err("笔记 id 不合法")
            notebook.delete_note(conn, nid)
            return _ok()
        if method == "POST" and path == "/api/v2/notes/import":
            raw_path = str(body.get("path") or "").strip()
            if not raw_path:
                return _err("缺少 Markdown 路径")
            from pathlib import Path as _Path
            p = _Path(raw_path)
            if p.suffix.lower() not in (".md", ".markdown", ".txt"):
                return _err("只支持导入 .md / .markdown / .txt")
            if not p.exists() or not p.is_file():
                return _err("文件不存在")
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = p.read_text(encoding="gb18030")
            return _ok(note=notebook.save_note(
                conn, title=p.stem, body_md=text,
                node_id=_int(body.get("node_id")),
                partition_id=_int(body.get("partition_id")),
            ))
        if method == "POST" and path == "/api/v2/notes/restore":
            nid = _int(body.get("id"))
            if not nid:
                return _err("笔记 id 不合法")
            notebook.restore_note(conn, nid)
            return _ok()
    except Exception as e:
        return _err(str(e))
    return _err("未知笔记路由")


def _relations(conn, method: str, path: str, query: dict, body: dict):
    try:
        from .. import links
    except Exception as e:
        return _err(f"关系模块不可用：{e}")
    try:
        if method == "GET" and path == "/api/v2/backlinks":
            kind = str(_first(query, "kind", "") or "")
            eid = _int(_first(query, "id"))
            if kind not in ("node", "document", "note") or not eid:
                return _err("kind/id 不合法")
            return _ok(kind=kind, id=eid, items=links.backlinks(conn, kind, eid))
        if method == "GET" and path == "/api/v2/relations":
            kind = str(_first(query, "kind", "") or "")
            eid = _int(_first(query, "id"))
            if kind not in ("node", "document", "note") or not eid:
                return _err("kind/id 不合法")
            return _ok(items=links.list_relations(conn, kind, eid))
        if method == "POST" and path == "/api/v2/relations/save":
            return _ok(relation=links.save_relation(
                conn,
                src_kind=str(body.get("src_kind") or ""),
                src_id=_int(body.get("src_id")),
                dst_kind=str(body.get("dst_kind") or ""),
                dst_id=_int(body.get("dst_id")),
                rel=str(body.get("rel") or "related")[:20],
                label=str(body.get("label") or "")[:40],
                origin=str(body.get("origin") or "manual"),
                confidence=float(body.get("confidence") or 1.0),
            ))
        if method == "POST" and path == "/api/v2/relations/delete":
            rid = _int(body.get("id"))
            if not rid:
                return _err("关系 id 不合法")
            links.delete_relation(conn, rid)
            return _ok()
    except Exception as e:
        return _err(str(e))
    return _err("未知关系路由")


def _entity(conn, query: dict):
    kind = str(_first(query, "kind", "") or "")
    eid = _int(_first(query, "id"))
    if kind not in ("node", "document", "note") or not eid:
        return _err("kind/id 不合法")
    if kind == "node":
        row = tree.get_node(conn, eid)
        if row is None:
            return _err("节点不存在")
        return _ok(kind=kind, entity=dict(row), docs=search.docs_in_scope(conn, eid, "subtree"))
    if kind == "document":
        d = search.doc_detail(conn, eid)
        return _ok(kind=kind, entity=d) if d else _err("文档不存在")
    try:
        from .. import notebook
        n = notebook.get_note(conn, eid)
        return _ok(kind=kind, entity=n) if n else _err("笔记不存在")
    except Exception as e:
        return _err(str(e))


def dispatch(conn, method: str, path: str, query: dict, body: dict):
    q = query or {}
    body = body or {}
    if method == "GET" and path == "/api/v2/workspace":
        return _ok(workspace=workspace.load())
    if method == "GET" and path == "/api/v2/bootstrap":
        return _bootstrap(conn, q)
    if method == "GET" and path == "/api/v2/graph":
        return _graph(conn, q)
    if method == "GET" and path == "/api/v2/entity":
        return _entity(conn, q)
    if method == "GET" and (path.startswith("/api/v2/reader/") or path.startswith("/api/v2/raw/")):
        return _reader(conn, path, q)
    if path.startswith("/api/v2/notes"):
        return _notes(conn, method, path, q, body)
    if path == "/api/v2/backlinks" or path.startswith("/api/v2/relations"):
        return _relations(conn, method, path, q, body)
    if method == "POST" and path == "/api/v2/workspace":
        data = body.get("workspace") if "workspace" in body else body
        return workspace.save(data)
    if method == "POST" and path == "/api/v2/workspace/reset":
        return workspace.reset()
    return _err(f"unknown route {method} {path}")
