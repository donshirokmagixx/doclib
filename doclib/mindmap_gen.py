# -*- coding: utf-8 -*-
"""REV-104：由选定资料生成可编辑知识导图（D2=a：复用检索块 + 模型结构化输出）。

- 先按范围取文档与代表块（有标题优先）；
- 有可用模型：要求输出 JSON 树（节点带 sources: doc_id/heading_path）；
- 模型不可用/输出不合法：回退为规则版（文档 → 章节）；
- 结果存 mindmap 库（version=2，多出 generated_from 与节点 sources，旧画布可忽略）。
"""
import json
import re
import time

from . import mindmap
from .ai import gateway

MAX_DOCS = 8
MAX_CHUNKS_PER_DOC = 3
MAX_NODES = 60

_SYS = (
    "你是复习资料结构化助手。请把给定资料整理成一棵知识导图，只输出 JSON，不要任何解释。\n"
    '格式：{"title":"根节点","children":[{"title":"子节点","sources":[{"doc_id":1,"heading_path":"..."}],"children":[]}]}\n'
    "要求：1) 中文；2) 每个节点尽量给出 sources（doc_id 与 heading_path 取自资料清单）；"
    "3) 层级不超过 4；4) 总节点数不超过 40；5) 不要编造资料里没有的内容。"
)


def _doc_rows(conn, node_id, scope, partition_id, doc_ids):
    if doc_ids:
        ids = [int(x) for x in doc_ids if str(x).isdigit()]
        if not ids:
            return []
        qs = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, title FROM documents WHERE deleted_at IS NULL AND id IN ({qs}) "
            "ORDER BY id", ids).fetchall()
    else:
        from . import tree
        ids = tree.node_doc_ids(conn, node_id, scope, partition_id)
        if ids is None:
            rows = conn.execute(
                "SELECT id, title FROM documents WHERE deleted_at IS NULL ORDER BY title"
            ).fetchall()
        else:
            ids = sorted(ids)
            if not ids:
                return []
            qs = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id, title FROM documents WHERE deleted_at IS NULL AND id IN ({qs}) "
                "ORDER BY id", ids).fetchall()
    return rows


def _collect(conn, node_id, scope, partition_id, doc_ids):
    rows = _doc_rows(conn, node_id, scope, partition_id, doc_ids)[:MAX_DOCS]
    docs = []
    for r in rows:
        chunks = conn.execute(
            "SELECT heading_path, text FROM doc_chunks WHERE doc_id=? ORDER BY ord LIMIT ?",
            (r["id"], MAX_CHUNKS_PER_DOC)).fetchall()
        heads = []
        for c in chunks:
            h = (c["heading_path"] or "").strip()
            if h and h not in heads:
                heads.append(h)
        docs.append({
            "doc_id": r["id"], "title": r["title"],
            "headings": heads[:5],
            "snippets": [(c["heading_path"] or "", (c["text"] or "")[:260]) for c in chunks],
        })
    return docs


def _rule_tree(docs, root_title):
    """规则版：根 → 每篇文档 → 每篇的 3–5 个章节；节点带 sources。"""
    children = []
    for d in docs:
        heads = d["headings"] or [d["title"]]
        kids = []
        for h in heads[:4]:
            kids.append({"title": h, "sources": [{"doc_id": d["doc_id"], "heading_path": h}],
                         "children": []})
        children.append({"title": d["title"],
                         "sources": [{"doc_id": d["doc_id"], "heading_path": ""}],
                         "children": kids})
    return {"title": root_title, "sources": [], "children": children}


def _llm_tree(conn, docs, root_title, provider_name=None, timeout=90):
    ctx = []
    for d in docs:
        heads = "；".join(d["headings"]) or "（无小标题）"
        ctx.append(f"[{d['doc_id']}] 《{d['title']}》 章节：{heads}")
    user = (f"根节点主题：{root_title}\n资料清单：\n" + "\n".join(ctx) +
            "\n请输出 JSON 树。")
    res = gateway.chat(conn, [{"role": "system", "content": _SYS},
                              {"role": "user", "content": user}],
                       provider=(gateway.load_provider(conn, provider_name) if provider_name else None),
                       temperature=0.2, max_tokens=1600, timeout=timeout,
                       task_type="mindmap", prompt_version="mm1")
    if not res.get("ok"):
        return None, res.get("error") or "模型不可用"
    text = res.get("content") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, "模型输出不是 JSON"
    try:
        tree = json.loads(m.group(0))
    except Exception:
        return None, "JSON 解析失败"
    if not isinstance(tree, dict) or not tree.get("title"):
        return None, "JSON 结构不符合要求"
    # 裁剪节点数，避免一张图过大
    cnt = {"n": 0}

    def trim(node, depth=0):
        if cnt["n"] >= MAX_NODES or depth > 4:
            node["children"] = []
            return
        cnt["n"] += 1
        node["sources"] = [s for s in (node.get("sources") or [])
                           if isinstance(s, dict) and s.get("doc_id")][:3]
        node["children"] = [c for c in (node.get("children") or []) if isinstance(c, dict)][:8]
        for c in node["children"]:
            trim(c, depth + 1)

    trim(tree)
    tree["sources"] = []
    return tree, ""


def _layout(tree):
    """把树摆成左→右导图；返回 items/edges。"""
    palette = ["#2e6da4", "#2e7d4f", "#b06a12", "#6a4c93", "#0f7b8a", "#a02a1e", "#8a5a2b", "#4a5568"]
    COL, ROW, GAP = 250, 74, 8
    items, edges = [], []
    uid = {"n": 0}

    def nid():
        uid["n"] += 1
        return f"gen{uid['n']}"

    def make(node, depth, y):
        title = str(node.get("title") or "未命名")[:60]
        it = {
            "id": nid(), "text": title,
            "x": 50 + depth * COL, "y": y,
            "w": max(130, min(240, len(title) * 19 + 46)), "h": 50,
            "shape": "round" if depth == 0 else "ellipse",
            "color": palette[depth % len(palette)], "fontSize": 14,
            "sources": node.get("sources") or [],
        }
        items.append(it)
        return it

    cursor = {"y": 40}

    def walk(node, depth):
        kids = node.get("children") or []
        if not kids:
            it = make(node, depth, cursor["y"])
            cursor["y"] += ROW + GAP
            return it, cursor["y"] - (ROW + GAP) + it["h"] / 2
        results = [walk(k, depth + 1) for k in kids]
        first, last = results[0][1], results[-1][1]
        mid = (first + last) / 2
        it = make(node, depth, mid - 25)
        for child, _ in results:
            edges.append({"id": nid(), "from": it["id"], "to": child["id"],
                          "style": "arrow", "color": "#8894a4"})
        return it, mid

    walk(tree, 0)
    return items, edges


def generate(conn, node_id=None, scope="subtree", partition_id=None,
             doc_ids=None, title="", provider_name=None, timeout=90):
    docs = _collect(conn, node_id, scope, partition_id, doc_ids)
    if not docs:
        return {"ok": False, "error": "选定范围内没有可用的资料（请先导入或换范围）"}
    root_title = (title or "").strip()
    if not root_title:
        root_title = "资料导图"
        from . import tree
        for nid in (node_id, partition_id):
            if not nid:
                continue
            n = tree.get_node(conn, nid)
            if n:
                root_title = n["name"]
                break
    structured, err = _llm_tree(conn, docs, root_title, provider_name, timeout)
    method = "llm"
    warning = ""
    if structured is None:
        structured = _rule_tree(docs, root_title)
        method = "rule"
        warning = f"模型生成不可用（{err}），已用规则版生成"
    items, edges = _layout(structured)
    name = mindmap.safe_name(f"资料导图 {root_title} " +
                             time.strftime("%Y%m%d-%H%M%S"))
    data = {
        "version": 2,
        "title": name,
        "created_at": int(time.time() * 1000),
        "view": {"x": 20, "y": 20, "k": 0.9},
        "items": items, "edges": edges, "strokes": [],
        "generated_from": {
            "method": method,
            "node_id": node_id, "scope": scope, "partition_id": partition_id,
            "doc_ids": [d["doc_id"] for d in docs],
            "prompt_version": "mm1",
        },
    }
    rep = mindmap.save(name, data)
    return {"ok": True, "name": rep["name"], "title": name, "version": 2,
            "method": method, "warning": warning,
            "items": len(items), "edges": len(edges),
            "doc_ids": [d["doc_id"] for d in docs],
            "generated_from": data["generated_from"]}
