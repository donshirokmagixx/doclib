# -*- coding: utf-8 -*-
"""检索：范围求解 → 多路召回 → 去重排序。

- ≥3 字的中文词走 FTS5 trigram（支持任意子串）
- <3 字的中文词（如「卷积」是 2 字）走 LIKE 兜底
- 结果按「命中词数 → 标题命中 → 词频」排序，并给出命中片段与章节路径
"""
import re
from typing import List, Optional

from . import tree

# 泛化词：单独出现时几乎没有区分度，却会让语义通道把不相关文档顶上来
GENERIC_TERMS = {
    "定义", "证明", "性质", "性质", "例子", "举例", "含义", "概念", "特点", "作用",
    "简介", "概述", "方法", "步骤", "条件", "应用", "分类", "总结", "对比", "区别",
    "比较", "介绍", "说明", "公式", "推导", "计算", "题目", "例题", "要点",
}

_SPLIT_RE = re.compile(r"[\s,，、;；/|]+")


def parse_terms(query: str) -> List[str]:
    q = (query or "").strip()
    if not q:
        return []
    parts = [p.strip() for p in _SPLIT_RE.split(q) if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out[:8]


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(text: str, terms: List[str], width: int = 90) -> str:
    low = text.lower()
    pos, mterm = -1, ""
    for t in sorted(terms, key=len, reverse=True):
        pos = low.find(t.lower())
        if pos >= 0:
            mterm = t
            break
    if pos < 0:
        return text[: width * 2].replace("\n", " ")
    start = max(0, pos - width // 2)
    end = min(len(text), pos + len(mterm) + width)
    frag = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


def _doc_meta(conn, doc_ids: List[int]) -> dict:
    if not doc_ids:
        return {}
    qs = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"SELECT d.*, GROUP_CONCAT(n.name, ' / ') AS node_names, "
        f"       GROUP_CONCAT(n.id) AS node_ids "
        f"FROM documents d "
        f"LEFT JOIN node_documents nd ON nd.document_id = d.id "
        f"LEFT JOIN nodes n ON n.id = nd.node_id AND n.deleted_at IS NULL "
        f"WHERE d.id IN ({qs}) AND d.deleted_at IS NULL "
        f"GROUP BY d.id",
        doc_ids,
    ).fetchall()
    return {r["id"]: r for r in rows}


def node_ids_of(row) -> list:
    raw = row["node_ids"] if "node_ids" in row.keys() else None
    out = []
    for x in (raw or "").split(","):
        x = x.strip()
        if x:
            try:
                out.append(int(x))
            except ValueError:
                pass
    return out


_HDF_CACHE = {"version": None, "map": {}}


def heading_doc_freq(conn, term: str) -> int:
    """term 出现在多少份（未删除）文档的章节标题里。带 library_version 缓存。"""
    try:
        ver = conn.execute(
            "SELECT value FROM meta WHERE key='library_version'").fetchone()
        ver = ver[0] if ver else "0"
    except Exception:
        ver = "0"
    if _HDF_CACHE["version"] != ver:
        _HDF_CACHE["version"] = ver
        _HDF_CACHE["map"] = {}
    key = term.lower()
    if key in _HDF_CACHE["map"]:
        return _HDF_CACHE["map"][key]
    pat = f"%{_like_escape(term)}%"
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT dc.doc_id) FROM doc_chunks dc "
            "JOIN documents d ON d.id = dc.doc_id "
            "WHERE d.deleted_at IS NULL AND dc.heading_path LIKE ? ESCAPE '\\'",
            (pat,)).fetchone()
        n = int(row[0] or 0)
    except Exception:
        n = 0
    _HDF_CACHE["map"][key] = n
    return n


def heading_rarity(conn, terms, heading_path: str) -> float:
    """命中标题的词越稀有，权重越高（1.0 = 只有这份文档有这个标题）。

    只在该 chunk 标题里出现的查询词参与计算；都没命中返回 0。
    """
    import math
    hp = (heading_path or "").lower()
    hit = [t for t in terms if t and t.lower() in hp]
    if not hit:
        return 0.0
    rarity = 0.0
    for t in hit:
        df = heading_doc_freq(conn, t)
        rarity += 1.0 / (1.0 + math.log(max(df, 1)))
    return rarity / len(hit)


def search(conn, query: str, node_id: Optional[int] = None,
           scope: str = "subtree", limit: int = 30,
           kw_weight: float = 0.7, sem_weight: float = 0.3,
           suppress_generic: bool = True, title_boost: float = 1.0,
           sem_k: int = 50, heading_boost: float = 60.0,
           heading_idf: bool = True) -> dict:
    """混合检索：关键词（FTS/LIKE）+ 语义（本地向量），用 RRF 融合。

    后面几个参数用于调参对比（默认值 = 当前线上行为），评测脚本会传不同组合。
    """
    terms = parse_terms(query)
    if not terms:
        return {"query": query, "terms": [], "total": 0, "results": [], "mode": "none"}

    scope_ids = tree.node_doc_ids(conn, node_id, scope)

    # ---------- 通道 1：关键词 ----------
    kw_order: List[int] = []
    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]
    if long_terms:
        fts_q = " OR ".join('"%s"' % t.replace('"', '""') for t in long_terms)
        try:
            rows = conn.execute(
                "SELECT dc.id FROM chunk_fts JOIN doc_chunks dc ON dc.id = chunk_fts.rowid "
                "WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts) LIMIT 300",
                (fts_q,)).fetchall()
            kw_order += [r[0] for r in rows]
        except Exception:
            pass
    for t in short_terms:
        pat = f"%{_like_escape(t)}%"
        try:
            rows = conn.execute(
                "SELECT id FROM doc_chunks WHERE (text LIKE ? ESCAPE '\\' "
                "OR heading_path LIKE ? ESCAPE '\\') LIMIT 200", (pat, pat)).fetchall()
            kw_order += [r[0] for r in rows]
        except Exception:
            pass

    # ---------- 通道 2：语义向量（本地模型，免费离线） ----------
    sem_order: List[int] = []
    sem_ok = False
    try:
        from .ai import embedder, vectors
        if embedder.available()["ok"] and vectors.available(conn) and vectors.count(conn) > 0:
            sem_query = query
            if suppress_generic:
                kept = [t for t in terms if t not in GENERIC_TERMS]
                if kept:
                    sem_query = " ".join(kept)
            qv = embedder.embed_query(sem_query)
            if qv:
                hits = vectors.search(conn, qv, k=sem_k)
                sem_order = [cid for cid, _d in hits]
                sem_ok = bool(sem_order)
    except Exception:
        sem_ok = False

    # ---------- RRF 融合（只看排名，不需要分数可比） ----------
    K = 60
    fused: dict = {}
    if kw_order:
        for rank, cid in enumerate(dict.fromkeys(kw_order)):
            fused[cid] = fused.get(cid, 0.0) + kw_weight / (K + rank + 1)
    if sem_order:
        for rank, cid in enumerate(sem_order):
            fused[cid] = fused.get(cid, 0.0) + sem_weight / (K + rank + 1)
    if not fused:
        return {"query": query, "terms": terms, "total": 0, "results": [],
                "mode": "hybrid" if sem_ok else "keyword"}

    # ---------- 取候选块 ----------
    ordered = sorted(fused.items(), key=lambda x: -x[1])[:400]
    ids = [cid for cid, _ in ordered]
    qs = ",".join("?" * len(ids))
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, doc_id, heading_path, text FROM doc_chunks WHERE id IN ({qs})", ids)}

    # ---------- 按文档聚合 ----------
    docs: dict = {}
    for cid, sc in ordered:
        r = rows.get(cid)
        if r is None:
            continue
        did = r["doc_id"]
        if scope_ids is not None and did not in scope_ids:
            continue
        e = docs.setdefault(did, {"scores": [], "best": None, "best_sc": -1,
                                  "terms": set(), "sem": False})
        e["scores"].append(sc)
        if sc > e["best_sc"]:
            e["best_sc"] = sc
            e["best"] = r
        hay = ((r["heading_path"] or "") + "\n" + (r["text"] or "")).lower()
        e["terms"] |= {t for t in terms if t.lower() in hay}
        if cid in set(sem_order):
            e["sem"] = True

    metad = _doc_meta(conn, list(docs.keys()))
    results = []
    for did, e in docs.items():
        d = metad.get(did)
        if d is None:
            continue
        best = e["best"]
        title = d["title"] or ""
        title_hit = any(t.lower() in title.lower() for t in terms)
        top3 = sum(sorted(e["scores"], reverse=True)[:3])
        score = top3 * 1000.0
        if title_hit:
            score += title_boost
        if heading_boost:
            if heading_idf:
                r = heading_rarity(conn, terms, best["heading_path"])
                score += heading_boost * r
            else:
                hp = (best["heading_path"] or "").lower()
                if any(t.lower() in hp for t in terms):
                    score += heading_boost
        if e["sem"]:
            score += 8.0
        score += len(e["terms"]) * 5.0
        q = float(d["quality"] or 1.0)
        score *= (0.75 + 0.25 * max(0.0, min(1.0, q)))

        body = best["text"] or ""
        if not any(t.lower() in body.lower() for t in terms):
            body = (best["heading_path"] or "") + " ｜ " + body
        results.append({
            "doc_id": did,
            "title": title,
            "file_path": d["file_path"],
            "node_names": d["node_names"] or "未分类",
            "node_ids": node_ids_of(d),
            "chunk_id": best["id"],
            "heading_path": best["heading_path"],
            "snippet": _snippet(body, terms),
            "quality": round(q, 3),
            "quality_note": d["quality_note"] or "",
            "matched_terms": sorted(e["terms"]),
            "semantic": e["sem"],
            "score": round(score, 2),
            "title_hit": title_hit,
        })
    results.sort(key=lambda x: -x["score"])
    return {"query": query, "terms": terms, "total": len(results),
            "results": results[:limit], "mode": "hybrid" if sem_ok else "keyword"}


def docs_in_scope(conn, node_id: Optional[int], scope: str = "subtree") -> dict:
    """「点节点 → 列出文档」，不做关键词过滤。"""
    scope_ids = tree.node_doc_ids(conn, node_id, scope)
    if scope_ids is None:
        rows = conn.execute(
            "SELECT id FROM documents WHERE deleted_at IS NULL ORDER BY title"
        ).fetchall()
        ids = [r[0] for r in rows]
    else:
        ids = sorted(scope_ids)
    metad = _doc_meta(conn, ids)
    out = []
    for did in ids:
        d = metad.get(did)
        if d is None:
            continue
        first = conn.execute(
            "SELECT id, heading_path, text FROM doc_chunks WHERE doc_id=? ORDER BY ord LIMIT 1",
            (did,),
        ).fetchone()
        n_chunks = conn.execute(
            "SELECT COUNT(*) FROM doc_chunks WHERE doc_id=?", (did,)
        ).fetchone()[0]
        out.append({
            "doc_id": did,
            "title": d["title"],
            "file_path": d["file_path"],
            "node_names": d["node_names"] or "未分类",
            "node_ids": node_ids_of(d),
            "quality": round(float(d["quality"] or 1.0), 3),
            "quality_note": d["quality_note"] or "",
            "chunk_id": first["id"] if first else None,
            "heading_path": (first["heading_path"] if first else "") or d["title"],
            "snippet": (first["text"][:220].replace("\n", " ") if first else ""),
            "chunks": n_chunks,
            "char_count": d["char_count"],
        })
    return {"total": len(out), "results": out}


def doc_detail(conn, doc_id: int) -> Optional[dict]:
    d = conn.execute(
        "SELECT * FROM documents WHERE id=? AND deleted_at IS NULL", (doc_id,)
    ).fetchone()
    if d is None:
        return None
    nodes = conn.execute(
        "SELECT n.id, n.name FROM node_documents nd JOIN nodes n ON n.id=nd.node_id "
        "WHERE nd.document_id=? AND n.deleted_at IS NULL", (doc_id,)
    ).fetchall()
    chunks = conn.execute(
        "SELECT id, ord, heading_path, char_len, is_table FROM doc_chunks "
        "WHERE doc_id=? ORDER BY ord", (doc_id,)
    ).fetchall()
    return {
        "id": d["id"],
        "title": d["title"],
        "file_path": d["file_path"],
        "char_count": d["char_count"],
        "file_size": d["file_size"],
        "nodes": [{"id": r["id"], "name": r["name"]} for r in nodes],
        "chunks": [{"id": r["id"], "ord": r["ord"], "heading_path": r["heading_path"],
                    "char_len": r["char_len"], "is_table": r["is_table"]} for r in chunks],
    }


def chunk_text(conn, chunk_id: int) -> Optional[dict]:
    r = conn.execute(
        "SELECT c.*, d.title AS doc_title, d.file_path AS file_path "
        "FROM doc_chunks c JOIN documents d ON d.id=c.doc_id WHERE c.id=?",
        (chunk_id,),
    ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"], "doc_id": r["doc_id"], "doc_title": r["doc_title"],
        "file_path": r["file_path"], "heading_path": r["heading_path"],
        "text": r["text"], "char_len": r["char_len"], "is_table": r["is_table"],
    }


def stats(conn) -> dict:
    def one(sql):
        row = conn.execute(sql).fetchone()
        return row[0] if row else 0

    return {
        "documents": one("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL"),
        "chunks": one("SELECT COUNT(*) FROM doc_chunks"),
        "nodes": one("SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"),
        "mounted": one("SELECT COUNT(*) FROM node_documents"),
        "chars": one("SELECT COALESCE(SUM(char_count),0) FROM documents WHERE deleted_at IS NULL"),
        "db_size": None,
    }
