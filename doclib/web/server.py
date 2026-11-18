# -*- coding: utf-8 -*-
"""本地网页界面（标准库 http.server，无第三方依赖）。

只监听 127.0.0.1，数据不出本机。
"""
import json
import os
import mimetypes
import sys
import time
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import citations, config, db, importer, mindmap, picker, search, seed, system, tree

STATIC = config.STATIC_DIR
APP_BUILD = "2026-11-18-r15"


MAX_BODY_BYTES = 32 * 1024 * 1024          # 32MB，足够大文档导入请求


class HttpError(Exception):
    """带状态码的请求错误，由 do_POST 统一转成 JSON 响应。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json_body(handler) -> dict:
    """解析 JSON 请求体。

    安全要求（防 CSRF / 防误用）：
      · 必须是 application/json（普通表单/纯文本请求直接拒绝）
      · 体积不超过 MAX_BODY_BYTES
      · 非法 JSON 返回 400，而不是静默当空对象
    """
    ctype = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype and ctype != "application/json":
        raise HttpError(415, "请求必须是 application/json")
    length = int(handler.headers.get("Content-Length") or 0)
    if length > MAX_BODY_BYTES:
        raise HttpError(413, "请求体过大")
    if not length:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HttpError(400, "请求体不是合法 JSON")
    return data if isinstance(data, dict) else {}


_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_ok(handler) -> bool:
    """只接受本机 Host（防 DNS rebinding：攻击者域名解析到 127.0.0.1 也无法通过）。"""
    host = (handler.headers.get("Host") or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        name = host.split("]")[0].lstrip("[")
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in _ALLOWED_HOSTS


def _cross_site(handler) -> bool:
    """浏览器标记的跨站请求（含跨站 GET，如 <img src=...> 触发导出）。"""
    return (handler.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site"


def _same_origin(handler) -> bool:
    """同源校验：带 Origin 的请求必须与 Host 一致（防跨站页面调用本地接口）。"""
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    host = handler.headers.get("Host") or ""
    try:
        u = urllib.parse.urlparse(origin)
    except Exception:
        return False
    return bool(u.netloc) and u.netloc == host


def _conn():
    return db.open_db()


def confirm_safe_delete(name: str) -> bool:
    return bool(name) and len(name) <= 64


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def api_dispatch(method: str, path: str, query: dict, body: dict):
    conn = _conn()
    try:
        if method == "GET" and path == "/api/health":
            h = system.health(conn)
            h["build"] = APP_BUILD
            try:
                from ..ai import prompts as _prompts
                h["prompt_version"] = _prompts.PROMPT_VERSION
            except Exception:
                pass
            return h

        if method == "GET" and path == "/api/tree":
            return {"tree": tree.tree_json(conn), "stats": search.stats(conn)}

        if method == "GET" and path == "/api/stats":
            s = search.stats(conn)
            try:
                s["db_size"] = config.DB_PATH.stat().st_size
            except OSError:
                pass
            s["backups"] = system.list_backups()
            return s

        if path == "/api/docs":
            node = query.get("node", [None])[0]
            node_id = int(node) if node not in (None, "", "null") else None
            scope = (query.get("scope", ["subtree"])[0]) or "subtree"
            return search.docs_in_scope(conn, node_id, scope)

        if path == "/api/search":
            q = (query.get("q", [""])[0] or "").strip()
            node = query.get("node", [None])[0]
            node_id = int(node) if node not in (None, "", "null") else None
            scope = (query.get("scope", ["subtree"])[0]) or "subtree"
            return search.search(conn, q, node_id, scope)

        # ---------- REV-101：科目分区（新路由，不动旧路由） ----------
        if method == "GET" and path == "/api/rev/partitions":
            parts = tree.list_partitions(conn)
            default = next((p["id"] for p in parts if p.get("doc_count")),
                           parts[0]["id"] if parts else None)
            return {"ok": True, "items": parts, "default": default}

        if method == "GET" and path == "/api/rev/tree":
            part = _as_int(query.get("partition", [None])[0])
            return {"tree": tree.tree_json(conn, part), "stats": search.stats(conn),
                    "partition": part}

        if method == "GET" and path == "/api/rev/docs":
            node_id = _as_int(query.get("node", [None])[0])
            scope = (query.get("scope", ["subtree"])[0]) or "subtree"
            part = _as_int(query.get("partition", [None])[0])
            return search.docs_in_scope(conn, node_id, scope, partition_id=part)

        if method == "GET" and path == "/api/rev/search":
            q = (query.get("q", [""])[0] or "").strip()
            node_id = _as_int(query.get("node", [None])[0])
            scope = (query.get("scope", ["subtree"])[0]) or "subtree"
            part = _as_int(query.get("partition", [None])[0])
            return search.search(conn, q, node_id, scope, partition_id=part)

        # 注意：必须限定 GET，否则 POST /api/doc/mount 会被这里抢走（曾导致
        # 「挂载失败：invalid literal for int() with base 10: 'mount'」）
        if method == "GET" and path.startswith("/api/doc/"):
            did = _as_int(path.rsplit("/", 1)[1])
            if did is None:
                return {"error": "bad doc id"}
            return search.doc_detail(conn, did) or {"error": "not found"}

        if method == "GET" and path.startswith("/api/chunk/"):
            cid = _as_int(path.rsplit("/", 1)[1])
            if cid is None:
                return {"error": "bad chunk id"}
            return search.chunk_text(conn, cid) or {"error": "not found"}

        if method == "GET" and path == "/api/backups":
            return {"backups": system.list_backups()}

        if method == "GET" and path == "/api/recycle":
            return {"nodes": tree.list_deleted(conn),
                    "documents": importer.list_deleted_documents(conn)}

        if method == "GET" and path == "/api/maintenance":
            from .. import citations, secrets, versioning
            outdated = importer.outdated_documents(conn)
            low = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL AND quality < 0.6"
            ).fetchone()[0]
            return {
                "parse_version": versioning.PARSE_VERSION,
                "outdated_documents": len(outdated),
                "outdated_items": [{"id": r["id"], "title": r["title"],
                                    "parse_version": r["parse_version"]} for r in outdated[:50]],
                "low_quality_documents": low,
                "secrets": secrets.status(),
                "citations_contract": {
                    "fields": ["doc_id", "heading_path", "snippet", "text_hash"],
                    "note": "引用不依赖 chunk_id，重新切块后依然有效",
                },
                "citation_helpers": bool(citations),
            }

        if method == "GET" and path == "/api/secrets":
            from .. import secrets
            return {"names": secrets.list_secrets(), "status": secrets.status(),
                    "masked": {n: secrets.masked(n) for n in secrets.list_secrets()}}

        if method == "GET" and path == "/api/ai/providers":
            from ..ai import gateway
            items = gateway.provider_summary(conn)
            cur = gateway.load_provider(conn)
            return {"items": items,
                    "current": cur.name if cur else "",
                    "summary": gateway.cost_summary(conn)}

        if method == "GET" and path == "/api/ai/embed":
            from ..ai import vectors
            return vectors.stats(conn)

        if method == "GET" and path == "/api/ai/runs":
            from ..ai import gateway
            return {"items": gateway.recent_runs(conn, 20),
                    "summary": gateway.cost_summary(conn)}

        if method == "POST":
            if path == "/api/conv/delete":
                cid = _as_int(body.get("id"))
                if not cid:
                    return {"ok": False, "error": "id 不合法"}
                conn.execute("DELETE FROM message_citations WHERE message_id IN "
                             "(SELECT id FROM messages WHERE conversation_id=?)", (cid,))
                conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
                conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
                return {"ok": True}

            if path == "/api/ask":
                from ..ai import rag
                q = str(body.get("question") or "").strip()
                if not q:
                    return {"ok": False, "error": "问题不能为空"}
                node = _as_int(body.get("node"))
                scope = str(body.get("scope") or "subtree").strip().lower()
                if scope == "node":          # 兼容任务书写法
                    scope = "self"
                if scope not in ("self", "subtree", "all"):
                    return {"ok": False, "error": "检索范围不合法（self / subtree / all）"}
                cid = _as_int(body.get("conversation_id"))
                if scope != "all" and node is None and not cid:
                    return {"ok": False,
                            "error": "缺少检索范围：请先选择节点；确实要全库请显式传 scope=all"}
                rep = rag.ask(conn, q, node, scope,
                              provider_name=body.get("provider") or None,
                              top_k=_as_int(body.get("top_k")) or rag.DEFAULT_TOP_K,
                              conversation_id=cid)
                return rep

            if path == "/api/rev/mindmap/generate_from_docs":
                from .. import mindmap_gen
                node = _as_int(body.get("node"))
                scope = str(body.get("scope") or "subtree").strip().lower()
                if scope == "node":
                    scope = "self"
                if scope not in ("self", "subtree", "all"):
                    return {"ok": False, "error": "检索范围不合法（self / subtree / all）"}
                part = _as_int(body.get("partition"))
                doc_ids = body.get("doc_ids")
                if doc_ids is not None and not isinstance(doc_ids, list):
                    return {"ok": False, "error": "doc_ids 需要是数组"}
                if not node and not part and not doc_ids:
                    return {"ok": False, "error": "请先选择分区/节点，或指定 doc_ids"}
                return mindmap_gen.generate(
                    conn, node_id=node, scope=scope, partition_id=part,
                    doc_ids=doc_ids, title=str(body.get("title") or ""),
                    provider_name=body.get("provider") or None,
                    timeout=_as_int(body.get("timeout")) or 90)

            if path == "/api/rev/ask":
                from ..ai import rag
                q = str(body.get("question") or "").strip()
                if not q:
                    return {"ok": False, "error": "问题不能为空"}
                node = _as_int(body.get("node"))
                scope = str(body.get("scope") or "subtree").strip().lower()
                if scope == "node":
                    scope = "self"
                if scope not in ("self", "subtree", "all"):
                    return {"ok": False, "error": "检索范围不合法（self / subtree / all）"}
                part = _as_int(body.get("partition"))
                cid = _as_int(body.get("conversation_id"))
                if part is None and scope != "all" and node is None and not cid:
                    return {"ok": False,
                            "error": "缺少检索范围：请选择分区/节点，或显式使用 scope=all"}
                rep = rag.ask(conn, q, node, scope,
                              provider_name=body.get("provider") or None,
                              top_k=_as_int(body.get("top_k")) or rag.DEFAULT_TOP_K,
                              conversation_id=cid, partition_id=part)
                return rep

            if path == "/api/rev/import":
                part = _as_int(body.get("partition"))
                mode = str(body.get("mode") or "").strip()
                paths = []
                if mode in ("folder", "files"):
                    got = picker.pick("folder" if mode == "folder" else "files")
                    if not got.get("ok"):
                        return {"ok": False, "error": got.get("error") or "无法打开选择窗口"}
                    paths = got.get("paths") or []
                    if not paths:
                        return {"ok": False, "cancelled": True, "error": "已取消选择"}
                else:
                    p = str(body.get("path") or "").strip().strip('"')
                    if not p:
                        return {"ok": False, "error": "请填写路径，或点「浏览」选择"}
                    import pathlib as _pl
                    if not _pl.Path(p).exists():
                        return {"ok": False, "error": f"路径不存在：{p}"}
                    ext = _pl.Path(p).suffix.lower()
                    allowed = {".docx", ".doc", ".pdf", ".pptx", ".ppt",
                               ".md", ".txt", ".markdown"}
                    if _pl.Path(p).is_file() and ext not in allowed:
                        return {"ok": False,
                                "error": f"不支持的文件类型：{ext or '未知'}（仅 Word/PDF/PPT/Markdown/TXT）"}
                    paths = [p]
                merged = {"scanned": 0, "imported": 0, "updated": 0,
                          "unchanged": 0, "failed": 0, "items": []}
                for p in paths:
                    rep = importer.import_path(conn, p, mount_mode="auto")
                    for k in ("scanned", "imported", "updated", "unchanged", "failed"):
                        merged[k] += rep[k]
                    merged["items"].extend(rep["items"])
                merged["relocated"] = sum(
                    1 for it in merged["items"] if it.get("status") == "relocated")
                # 分区约束：挂在分区外的文档，收回到该分区根
                confined = 0
                if part is not None:
                    for it in merged["items"]:
                        did = it.get("doc_id")
                        if not did:
                            continue
                        rows = conn.execute(
                            "SELECT node_id FROM node_documents WHERE document_id=?",
                            (did,)).fetchall()
                        if any(tree.partition_of_node(conn, r["node_id"]) != part for r in rows):
                            importer.set_doc_nodes(conn, int(did), [part])
                            confined += 1
                merged["partition"] = part
                merged["confined"] = confined
                return {"ok": True, **merged}

            if path == "/api/ai/test":
                from ..ai import gateway
                rep = gateway.test_connection(conn, body.get("name") or None)
                return rep

            if path == "/api/ai/providers":
                from ..ai import gateway as _gw
                from ..db import now_ms as _now
                name = str(body.get("name") or "").strip()
                if not name:
                    return {"ok": False, "error": "请填写配置名称"}
                try:
                    price_in = float(body.get("price_in") or 0)
                    price_out = float(body.get("price_out") or 0)
                except (TypeError, ValueError):
                    price_in = price_out = 0.0
                ts = _now()
                conn.execute(
                    "INSERT INTO ai_providers(name,kind,base_url,model,key_ref,role,"
                    "enabled,extra_json,created_at,updated_at,is_default,free,"
                    "price_in,price_out,note) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, "
                    "base_url=excluded.base_url, model=excluded.model, "
                    "key_ref=excluded.key_ref, role=excluded.role, "
                    "enabled=excluded.enabled, extra_json=excluded.extra_json, "
                    "free=excluded.free, price_in=excluded.price_in, "
                    "price_out=excluded.price_out, note=excluded.note, "
                    "updated_at=excluded.updated_at",
                    (name, str(body.get("kind") or "openai_compatible"),
                     str(body.get("base_url") or ""), str(body.get("model") or ""),
                     str(body.get("key_ref") or ""), str(body.get("role") or "chat"),
                     1 if body.get("enabled", True) else 0,
                     str(body.get("extra_json") or "{}"), ts, ts,
                     1 if body.get("is_default") else 0,
                     1 if body.get("free") else 0, price_in, price_out,
                     str(body.get("note") or "")),
                )
                if body.get("is_default"):
                    _gw.set_default(conn, name)
                return {"ok": True, "current": (_gw.load_provider(conn) or None) and _gw.load_provider(conn).name}

            if path == "/api/ai/providers/default":
                from ..ai import gateway as _gw
                name = str(body.get("name") or "").strip()
                if not _gw.set_default(conn, name):
                    return {"ok": False, "error": "配置不存在"}
                cur = _gw.load_provider(conn)
                _cname = cur.name if cur else name
                sys.stderr.write(f"[model] 切换默认模型 -> {name} (实际生效: {_cname})\n")
                return {"ok": True, "current": _cname, "build": APP_BUILD}

            if path == "/api/ai/providers/toggle":
                from ..ai import gateway as _gw
                name = str(body.get("name") or "").strip()
                ok = _gw.set_enabled(conn, name, bool(body.get("enabled", True)))
                return {"ok": ok, "error": "" if ok else "配置不存在"}

            if path == "/api/ai/providers/delete":
                from ..ai import gateway as _gw
                name = str(body.get("name") or "").strip()
                if not confirm_safe_delete(name):
                    return {"ok": False, "error": "参数错误"}
                ok = _gw.delete_provider(conn, name)
                return {"ok": ok}

            if path == "/api/doc/mount":
                did = _as_int(body.get("doc_id"))
                nid = _as_int(body.get("node_id"))
                if not did or not nid:
                    return {"ok": False, "error": "缺少 doc_id 或 node_id"}
                importer.mount_smart(conn, did, nid)
                return {"ok": True}

            if path == "/api/seed":
                return {"ok": True, **seed.seed(conn)}

            if path == "/api/map/save":
                name = str(body.get("name") or "").strip()
                if not name:
                    return {"ok": False, "error": "缺少导图名"}
                data = body.get("data") or {}
                if not isinstance(data, dict):
                    return {"ok": False, "error": "数据格式不对"}
                return mindmap.save(name, data)

            if path == "/api/map/new":
                name = str(body.get("name") or "").strip() or "未命名导图"
                return mindmap.create(name)

            if path == "/api/map/rename":
                return mindmap.rename(str(body.get("name") or ""),
                                      str(body.get("new_name") or ""))

            if path == "/api/map/delete":
                return mindmap.delete(str(body.get("name") or ""))

            if path == "/api/conv/new":
                cur = conn.execute(
                    "INSERT INTO conversations(title, node_id, created_at, updated_at)"
                    " VALUES(?,?,?,?)",
                    (str(body.get("title") or "新对话")[:40], _as_int(body.get("node")),
                     db.now_ms(), db.now_ms()))
                return {"ok": True, "id": cur.lastrowid}

            if path == "/api/conv/export_batch":
                from .. import notes as _notes_b
                _cids = body.get("ids") or []
                if isinstance(_cids, (str, int)):
                    _cids = [x for x in str(_cids).replace("，", ",").split(",") if x.strip()]
                _cids = [_as_int(x) for x in _cids if _as_int(x)]
                res = _notes_b.export_batch(
                    conn, _cids, include_snippet=bool(body.get("snippet")),
                    mode=str(body.get("mode") or "outline"),
                    title=str(body.get("title") or "合并复习提纲")[:40],
                    group=str(body.get("group") or "node"))
                if res.get("ok") and body.get("open"):
                    try:
                        system.open_document(res["path"])
                    except Exception:
                        pass
                return res

            if path == "/api/conv/export":
                from .. import notes as _notes
                cid = _as_int(body.get("id"))
                if not cid:
                    return {"ok": False, "error": "会话 id 不合法"}
                _ids = body.get("ids") or None
                if isinstance(_ids, (str, int)):
                    _ids = [x for x in str(_ids).replace("，", ",").split(",") if x.strip()]
                res = _notes.export_conversation(
                    conn, cid, msg_ids=_ids, include_snippet=bool(body.get("snippet")),
                    mode=str(body.get("mode") or "qa"),
                    group=str(body.get("group") or "node"))
                if res.get("ok") and body.get("open"):
                    try:
                        system.open_document(res["path"])
                    except Exception:
                        pass
                return res



            if path == "/api/conv/update":
                cid = _as_int(body.get("id"))
                if not cid:
                    return {"ok": False, "error": "id 不合法"}
                fields, vals = [], []
                for k in ("title", "pinned", "favorite", "tags"):
                    if k in body:
                        fields.append(f"{k}=?")
                        v = body[k]
                        if k == "title":
                            v = str(v)[:40]
                        elif k == "tags":
                            v = str(v)[:80]
                        else:
                            v = 1 if v else 0
                        vals.append(v)
                if not fields:
                    return {"ok": False, "error": "没有要修改的字段"}
                fields.append("updated_at=?")
                vals.extend([db.now_ms(), cid])
                conn.execute(f"UPDATE conversations SET {', '.join(fields)} WHERE id=?", vals)
                return {"ok": True}


            if path == "/api/open":
                did = _as_int(body.get("doc_id"))
                if did:
                    row = conn.execute(
                        "SELECT file_path FROM documents WHERE id=? AND deleted_at IS NULL",
                        (did,),
                    ).fetchone()
                    if row is None:
                        return {"ok": False, "error": "文档不存在"}
                    return system.open_document(row["file_path"])
                if body.get("path"):
                    import pathlib as _pl
                    target = _pl.Path(str(body["path"])).expanduser()
                    try:
                        real = target.resolve()
                    except Exception:
                        return {"ok": False, "error": "路径不合法"}
                    data_root = config.DATA_DIR.resolve()
                    known = set()
                    for r in conn.execute("SELECT file_path FROM documents"
                                          " WHERE deleted_at IS NULL"):
                        try:
                            known.add(str(_pl.Path(r["file_path"]).resolve()))
                        except Exception:
                            pass
                    inside_data = data_root == real or data_root in real.parents
                    if not (inside_data or str(real) in known):
                        return {"ok": False,
                                "error": "只允许打开资料库内文件（导出的 Word/图片或已入库文档）"}
                    return system.open_document(str(real))
                return {"ok": False, "error": "缺少 doc_id 或 path"}

            if path == "/api/import":
                mode = str(body.get("mode") or "").strip()
                paths = []
                if mode in ("folder", "files"):
                    # 打开系统原生的选择对话框
                    got = picker.pick("folder" if mode == "folder" else "files")
                    if not got.get("ok"):
                        return {"ok": False,
                                "error": got.get("error") or "无法打开选择窗口"}
                    paths = got.get("paths") or []
                    if not paths:
                        return {"ok": False, "cancelled": True, "error": "已取消选择"}
                else:
                    p = str(body.get("path") or "").strip().strip('"')
                    if not p:
                        return {"ok": False, "error": "请填写路径，或点「浏览」选择"}
                    import pathlib as _pl
                    if not _pl.Path(p).exists():
                        return {"ok": False, "error": f"路径不存在：{p}"}
                    ext = _pl.Path(p).suffix.lower()
                    allowed = {".docx", ".doc", ".pdf", ".pptx", ".ppt",
                               ".md", ".txt", ".markdown"}
                    if _pl.Path(p).is_file() and ext not in allowed:
                        return {"ok": False,
                                "error": f"不支持的文件类型：{ext or '未知'}（仅 Word/PDF/PPT/Markdown/TXT）"}
                    paths = [p]

                merged = {"scanned": 0, "imported": 0, "updated": 0,
                          "unchanged": 0, "failed": 0, "items": []}
                for p in paths:
                    rep = importer.import_path(conn, p, mount_mode="auto")
                    for k in ("scanned", "imported", "updated", "unchanged", "failed"):
                        merged[k] += rep[k]
                    merged["items"].extend(rep["items"])
                merged["relocated"] = sum(
                    1 for it in merged["items"] if it.get("status") == "relocated")
                return {"ok": True, **merged}

            if path == "/api/backup":
                return system.backup(conn)

            if path == "/api/node/create":
                name = str(body.get("name") or "").strip()
                if not name:
                    return {"ok": False, "error": "节点名不能为空"}
                if len(name) > 40:
                    return {"ok": False, "error": "节点名过长（≤40 字）"}
                parent = body.get("parent_id")
                nid = tree.create_node(conn, name, int(parent) if parent else None,
                                       str(body.get("description") or ""))
                return {"ok": True, "node_id": nid}

            if path == "/api/node/rename":
                nid = _as_int(body.get("node_id"))
                name = str(body.get("name") or "").strip()
                if not nid or not name:
                    return {"ok": False, "error": "缺少 node_id 或名称"}
                tree.rename_node(conn, nid, name)
                return {"ok": True}

            if path == "/api/node/delete":
                nid = _as_int(body.get("node_id"))
                if not nid:
                    return {"ok": False, "error": "缺少 node_id"}
                n = tree.delete_node(conn, nid)
                return {"ok": True, "deleted": n}

            if path == "/api/node/reorder":
                nid = _as_int(body.get("node_id"))
                delta = _as_int(body.get("delta"))
                if nid is None or delta not in (-1, 1):
                    return {"ok": False, "error": "参数错误"}
                ok = tree.reorder(conn, nid, delta)
                return {"ok": ok, "moved": ok,
                        "error": "" if ok else "已经到最前/最后了"}

            if path == "/api/node/move":
                nid = _as_int(body.get("node_id"))
                pid = body.get("parent_id")
                pid = _as_int(pid) if pid not in (None, "", "null") else None
                before = _as_int(body.get("before_id")) if body.get("before_id") else None
                if nid is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    tree.move_node(conn, nid, pid, before)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True}

            if path in ("/api/node/indent", "/api/node/outdent"):
                nid = _as_int(body.get("node_id"))
                if nid is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    if path == "/api/node/indent":
                        tree.indent_node(conn, nid)
                    else:
                        tree.outdent_node(conn, nid)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True}

            if path == "/api/recycle/restore":
                nid = _as_int(body.get("node_id"))
                if nid is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    n = tree.restore_node(conn, nid)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True, "restored": n}

            if path == "/api/doc/move":
                did = _as_int(body.get("doc_id"))
                nid = _as_int(body.get("node_id"))
                if did is None or nid is None:
                    return {"ok": False, "error": "参数错误"}
                importer.unmount_all_user_nodes(conn, did)
                importer.mount_smart(conn, did, nid)
                return {"ok": True}

            if path == "/api/doc/set_nodes":
                did = _as_int(body.get("doc_id"))
                if did is None:
                    return {"ok": False, "error": "参数错误"}
                got = importer.set_doc_nodes(conn, did, body.get("node_ids") or [])
                return {"ok": True, "node_ids": got}

            if path == "/api/doc/delete":
                did = _as_int(body.get("doc_id"))
                if did is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    importer.delete_document(conn, did)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True}

            if path == "/api/doc/restore":
                did = _as_int(body.get("doc_id"))
                if did is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    importer.restore_document(conn, did)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True}

            if path == "/api/doc/purge":
                did = _as_int(body.get("doc_id"))
                if did is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    importer.purge_document(conn, did)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True}

            if path == "/api/recycle/purge":
                if body.get("all"):
                    n = tree.purge_all_deleted(conn)
                    return {"ok": True, "purged": n}
                nid = _as_int(body.get("node_id"))
                if nid is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    n = tree.purge_node(conn, nid)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True, "purged": n}

            if path == "/api/recycle/purge_docs":
                if body.get("all"):
                    n = importer.purge_all_deleted_documents(conn)
                    return {"ok": True, "purged": n}
                did = _as_int(body.get("doc_id"))
                if did is None:
                    return {"ok": False, "error": "参数错误"}
                try:
                    importer.purge_document(conn, did)
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                return {"ok": True, "purged": 1}

            # ---------- A1：按解析版本重建索引 ----------
            if path == "/api/rebuild":
                rep = importer.rebuild(conn,
                                       limit=_as_int(body.get("limit")) or 0,
                                       dry_run=bool(body.get("dry_run")))
                return {"ok": True, **rep}

            # ---------- A4：密钥与供应商配置 ----------
            if path == "/api/secrets":
                from .. import secrets
                if body.get("delete"):
                    ok = secrets.delete_secret(str(body["delete"]))
                    return {"ok": ok}
                name = str(body.get("name") or "").strip()
                value = str(body.get("value") or "")
                if not name or not value:
                    return {"ok": False, "error": "请填写键名和密钥"}
                try:
                    secrets.set_secret(name, value)
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "error": str(e)}
                return {"ok": True, "names": secrets.list_secrets()}

            if path == "/api/ai/embed/index":
                from ..ai import vectors
                rep = vectors.index_missing(conn, limit=_as_int(body.get("limit")) or 0)
                return rep

            if path == "/api/ai/embed/clear":
                from ..ai import vectors
                vectors.clear(conn)
                return {"ok": True}

        if method == "GET" and path.startswith("/api/conv/detail"):
            try:
                cid = int(path.rsplit("/", 1)[1])
            except (ValueError, IndexError):
                return {"ok": False, "error": "会话 id 不合法"}
            c = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            if c is None:
                return {"ok": False, "error": "会话不存在"}
            msgs = []
            for row in conn.execute(
                    "SELECT id, role, content, model, created_at FROM messages "
                    "WHERE conversation_id=? ORDER BY id", (cid,)):
                d = dict(row)
                cites = []
                for i, cr in enumerate(conn.execute(
                        "SELECT mc.chunk_id, mc.heading_path, mc.snippet, mc.doc_id,"
                        " COALESCE(dc.title, '文档#' || mc.doc_id) AS title"
                        " FROM message_citations mc"
                        " LEFT JOIN (SELECT id, title FROM documents) dc ON dc.id = mc.doc_id"
                        " WHERE mc.message_id=? ORDER BY mc.id", (d["id"],)), 1):
                    cites.append({"index": i, "chunk_id": cr["chunk_id"],
                                  "doc_title": cr["title"],
                                  "heading_path": cr["heading_path"],
                                  "snippet": cr["snippet"], "drifted": False})
                d["citations"] = cites
                msgs.append(d)
            conv = dict(c)
            conv["partition_id"] = (tree.partition_of_node(conn, conv.get("node_id"))
                                    if conv.get("node_id") else None)
            return {"ok": True, "conversation": conv, "messages": msgs}

        if method == "GET" and path == "/api/maps":
            return {"items": mindmap.list_maps(), "dir": str(mindmap.root_dir())}

        if method == "GET" and path.startswith("/api/map/"):
            name = urllib.parse.unquote(path[len("/api/map/"):])
            data = mindmap.load(name)
            if data is None:
                return {"ok": False, "error": "导图不存在"}
            return {"ok": True, **data}

        if method == "GET" and path == "/api/conv/list":
            rows = conn.execute(
                "SELECT c.id, c.title, c.pinned, c.favorite, c.tags, c.created_at,"
                " c.updated_at, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id)"
                " AS turns FROM conversations c ORDER BY c.pinned DESC, c.favorite DESC,"
                " c.updated_at DESC, c.id DESC LIMIT 200").fetchall()
            return {"items": [dict(r) for r in rows]}

        if method == "GET" and path.startswith("/api/conv/") and path.count("/") == 3:
            try:
                cid = int(path.rsplit("/", 1)[1])
            except ValueError:
                return {"ok": False, "error": "会话 id 不合法"}
            c = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            if c is None:
                return {"ok": False, "error": "会话不存在"}
            msgs = [dict(r) for r in conn.execute(
                "SELECT id, role, content, model, created_at FROM messages "
                "WHERE conversation_id=? ORDER BY id", (cid,))]
            for m in msgs:
                m["citations"] = citations.list_for_message(conn, m["id"])
            return {"ok": True, "conversation": dict(c), "messages": msgs}

        return {"error": f"unknown route {method} {path}"}
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "DocLib/0.1"

    def log_message(self, fmt, *args):  # noqa: A003
        line = str(args[0]) if args else ""
        if "/api/" in line or " 500 " in line or " 404 " in line:
            sys.stderr.write("[web] " + fmt % args + "\n")

    def _send(self, code: int, payload, ctype="application/json; charset=utf-8",
              filename: str = ""):
        if isinstance(payload, (dict, list)):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if filename:
            import urllib.parse as _up
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + _up.quote(filename))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, rel: str):
        rel = rel.lstrip("/") or "index.html"
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.exists():
            target = STATIC / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/") and (not _host_ok(self) or _cross_site(self)):
            self._send(403, {"ok": False, "error": "请求来源被拒绝"})
            return
        if parsed.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if parsed.path.startswith("/api/conv/") and parsed.path.endswith("/docx"):
            try:
                cid = int(parsed.path.strip("/").split("/")[2])
            except Exception:
                self._send(400, {"ok": False, "error": "会话 id 不合法"})
                return
            try:
                from .. import notes as notes_mod
                _conn = db.open_db()
                try:
                    res = notes_mod.export_conversation(_conn, cid)
                finally:
                    _conn.close()
                if not res.get("ok"):
                    self._send(200, res)
                    return
                import pathlib as _pl
                data = _pl.Path(res["path"]).read_bytes()
                self._send(200, data,
                           "application/vnd.openxmlformats-officedocument"
                           ".wordprocessingml.document",
                           filename=res.get("name") or "notes.docx")
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._send(500, {"ok": False, "error": str(e)})
            return
        if parsed.path.startswith("/api/"):
            try:
                result = api_dispatch("GET", parsed.path,
                                      urllib.parse.parse_qs(parsed.query), {})
                self._send(200, result)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._send(500, {"error": str(e)})
            return
        self._serve_static(parsed.path)

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if not _host_ok(self) or _cross_site(self):
                raise HttpError(403, "请求来源被拒绝（仅允许本机）")
            if not _same_origin(self):
                raise HttpError(403, "跨站请求被拒绝")
            body = _json_body(self)
            result = api_dispatch("POST", parsed.path,
                                  urllib.parse.parse_qs(parsed.query), body)
            self._send(200, result)
        except HttpError as e:
            self._send(e.code, {"ok": False, "error": e.message})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {"error": str(e)})


RUNTIME_FILE = config.DATA_DIR / "runtime.json"


def runtime_path():
    return RUNTIME_FILE


def read_runtime():
    try:
        import json as _json
        if RUNTIME_FILE.exists():
            return _json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def write_runtime(port: int, url: str):
    try:
        import json as _json
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_FILE.write_text(_json.dumps({
            "pid": os.getpid(), "port": port, "host": config.HOST, "url": url,
            "build": APP_BUILD, "started_at": int(time.time() * 1000),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print("[warn] 写入 runtime.json 失败:", e)


def clear_runtime():
    """只有自己是那个实例时才清理，避免误删别人的档案。"""
    try:
        info = read_runtime()
        if info and int(info.get("pid") or 0) == os.getpid() and RUNTIME_FILE.exists():
            RUNTIME_FILE.unlink()
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            k32.CloseHandle(h)
            return True
        return False
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False


def live_instance():
    """若已有本程序实例在跑，返回它的信息；否则 None。"""
    info = read_runtime()
    if not info:
        return None
    pid = int(info.get("pid") or 0)
    port = int(info.get("port") or 0)
    if not pid or not port or not _pid_alive(pid):
        return None
    url = f"http://{config.HOST}:{port}/"
    try:
        import json as _json
        import urllib.request
        raw = urllib.request.urlopen(url + "api/health", timeout=2).read()
        health = _json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        return None
    if str(health.get("db") or "") != str(config.DB_PATH):
        return None                      # 不是同一个资料库，视为不同实例
    return {"pid": pid, "port": port, "url": url,
            "build": health.get("build") or info.get("build") or ""}


def _port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    """端口是否已被监听。"""
    import socket
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def pick_free_port(preferred: int, span: int = 10) -> int:
    """优先用 preferred，被占则往后找，实在不行让系统分配（返回 0）。"""
    for p in range(preferred, preferred + span):
        if not _port_open(config.HOST, p):
            return p
    return 0


def _report_running(info):
    print()
    print(f"  [!] DocLib 已经在运行（PID {info['pid']}，端口 {info['port']}，build {info.get('build') or '未知'}）")
    print(f"      界面地址：{info['url']}")
    print()
    print("      >>> 本窗口只是提示，可以直接关闭（不会再启动第二个实例）。")
    return 3



    """Windows 下 SO_REUSEADDR 允许重复绑定同一端口，必须自己先探测。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _already_running(port: int, url: str, open_browser: bool) -> int:
    """端口被占用时的处理：如果占用者就是 DocLib，直接打开浏览器。"""
    print()
    print(f"  [!] 端口 {port} 已被占用 —— 大概率是 DocLib 已经在运行了。")
    try:
        import json as _json
        import urllib.request
        raw = urllib.request.urlopen(url + "api/health", timeout=3).read()
        info = _json.loads(raw.decode("utf-8")) if raw else {}
        running_build = info.get("build") or ""
        print(f"      检测到运行中的 DocLib（build: {running_build or '未知（旧版本）'}）")
        if running_build and running_build == APP_BUILD:
            print("      版本一致，正在为你打开浏览器…")
        else:
            print("      [重要] 它的版本与本程序不一致（可能是旧版本在运行）")
            print("             旧版本可能缺少新功能（例如模型切换）")
            print("             请先关掉旧窗口/旧进程，再重新启动本程序。")
        if open_browser:
            webbrowser.open(url)
        print("      如果浏览器没反应，请手动访问：", url)
        print()
        print("      >>> 已有实例在运行，本窗口只是提示，可以直接关闭（不会再启动第二个）。")
        return 3
    except Exception:
        print(f"      但 {url} 没有响应，可能是别的程序占用了这个端口。")
        print(f"      请关掉占用 {port} 端口的程序后重试。")
        return 4


def start_server(port: int = None, strict_port: bool = False,
                 do_backup: bool = True):
    """起一个后台服务（不阻塞），返回 (httpd, port, url)。供原生窗口调用。"""
    config.ensure_dirs()
    preferred = int(port or config.PORT)

    try:
        if RUNTIME_FILE.exists():
            _info = read_runtime()
            if not _info or not _pid_alive(int(_info.get("pid") or 0)):
                RUNTIME_FILE.unlink()
    except Exception:
        pass

    if strict_port:
        if _port_open(config.HOST, preferred):
            raise OSError(f"端口 {preferred} 已被占用")
        port_to_use = preferred
    else:
        port_to_use = pick_free_port(preferred)

    conn = db.open_db()
    seed.seed(conn)
    if do_backup:
        try:
            system.backup(conn)
        except Exception as e:  # noqa: BLE001
            print("[warn] 启动备份失败:", e)
    conn.close()

    httpd = ThreadingHTTPServer((config.HOST, port_to_use), Handler)
    actual = int(httpd.server_address[1])
    url = f"http://{config.HOST}:{actual}/"
    write_runtime(actual, url)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, actual, url


def stop_server(httpd):
    try:
        httpd.shutdown()
    except Exception:
        pass
    try:
        httpd.server_close()
    except Exception:
        pass
    clear_runtime()


def run(port: int = None, open_browser: bool = True, strict_port: bool = False):
    preferred = int(port or config.PORT)
    config.ensure_dirs()

    # ⓪ 清理上次异常退出的残留档案（进程已不在）
    try:
        if RUNTIME_FILE.exists():
            _info = read_runtime()
            if not _info or not _pid_alive(int(_info.get("pid") or 0)):
                RUNTIME_FILE.unlink()
    except Exception:
        pass

    # ① 已有实例（单实例锁）：直接打开它
    if os.environ.get("DOCLIB_ALLOW_MULTI") != "1":
        info = live_instance()
        if info:
            if open_browser:
                webbrowser.open(info["url"])
            return _report_running(info)

    # ② 选端口：strict 只用指定端口；否则自动避让
    if strict_port:
        if _port_open(config.HOST, preferred):
            url = f"http://{config.HOST}:{preferred}/"
            return _already_running(preferred, url, open_browser)
        port_to_use = preferred
    else:
        port_to_use = pick_free_port(preferred)

    conn = db.open_db()
    seed.seed(conn)
    try:
        system.backup(conn)
    except Exception as e:  # noqa: BLE001
        print("[warn] 启动备份失败:", e)
    conn.close()

    try:
        httpd = ThreadingHTTPServer((config.HOST, port_to_use), Handler)
    except OSError:
        if not strict_port:
            httpd = ThreadingHTTPServer((config.HOST, 0), Handler)
        else:
            return _already_running(preferred, f"http://{config.HOST}:{preferred}/", open_browser)

    actual_port = httpd.server_address[1]
    url = f"http://{config.HOST}:{actual_port}/"
    write_runtime(actual_port, url)

    print("=" * 56)
    print("  DocLib 个人 Word 资料库")
    print("  界面 :", url)
    if actual_port != preferred:
        print(f"  （{preferred} 被占用，已自动改用 {actual_port}）")
    print("  数据 :", config.DB_PATH)
    print("  版本 :", APP_BUILD)
    print("  退出 : 在这个窗口按 Ctrl+C，或关掉本窗口")
    print("=" * 56)

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
        clear_runtime()
    return 0


