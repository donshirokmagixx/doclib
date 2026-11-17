# -*- coding: utf-8 -*-
"""导入：扫描 → 解析 → 切块 → 入库 → FTS → 给出挂载建议。"""
import hashlib
import os
from pathlib import Path
from typing import List, Optional

from . import chunker, tree
from . import quality as quality_mod
from .db import now_ms, bump_library_version
from .docx_reader import DocxError
from .readers import SUPPORTED_EXT, parse_any
from .versioning import PARSE_VERSION

SUPPORTED = SUPPORTED_EXT
LEGACY = set()      # .doc 现在通过 Word / LibreOffice 转换后解析
OTHER = {".ppt", ".xls", ".xlsx", ".rtf", ".odt", ".html", ".htm", ".epub"}
SKIP_NAMES = {"thumbs.db", "desktop.ini"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def scan(path: str) -> List[Path]:
    p = Path(path)
    if p.is_file():
        return [p]
    if not p.exists():
        raise FileNotFoundError(f"路径不存在：{path}")
    out: List[Path] = []
    for root, _dirs, files in os.walk(p):
        for name in files:
            if name.lower() in SKIP_NAMES or name.startswith("~$"):
                continue
            out.append(Path(root) / name)
    out.sort(key=lambda x: str(x).lower())
    return out


def _path_key(path: Path) -> str:
    return str(path.resolve()).lower()


def _suggest_nodes(conn, title: str, text: str, headings=None, limit: int = 3):
    """按名称/关键词命中给挂载建议（纯规则，不联网）。

    权重顺序：标题（文档名）> 章节标题 > 正文出现次数。
    章节标题比正文更能代表文档主题，所以单独加权。
    """
    hay_title = title.lower()
    hay_text = text.lower()[:20000]
    heads = " \n ".join(headings or []).lower()
    cands = []
    rows = conn.execute(
        "SELECT * FROM nodes WHERE deleted_at IS NULL AND is_system=0"
    ).fetchall()
    for r in rows:
        name = (r["name"] or "").lower()
        if not name:
            continue
        score = 0.0
        if name in hay_title:
            score += 8.0
        if name in heads:
            score += 4.0
        cnt = hay_text.count(name)
        score += min(cnt, 30) * 0.6
        for kw in tree.get_keywords(r):
            k = kw.lower()
            if not k:
                continue
            if k in hay_title:
                score += 5.0
            if k in heads:
                score += 3.0
            score += min(hay_text.count(k), 20) * 0.4
        if score > 0:
            cands.append({"node_id": r["id"], "name": r["name"],
                          "depth": r["depth"], "score": round(score, 2)})
    cands.sort(key=lambda x: -x["score"])
    return cands[:limit]


def import_file(conn, path: Path) -> dict:
    path = Path(path)
    ext = path.suffix.lower()
    title = path.stem
    res = {"file": str(path), "title": title, "status": "skipped", "doc_id": None,
           "chunks": 0, "chars": 0, "note": "", "suggestion": []}

    if ext in LEGACY:
        res["status"] = "failed"
        res["note"] = "旧版 .doc 暂不支持：请用 Word 另存为 .docx 后再导入"
        return res
    if ext in OTHER:
        res["status"] = "skipped"
        res["note"] = f"{ext} 暂不支持（当前支持 docx / doc / pdf / pptx / 图片 / md / txt）"
        return res
    if ext not in SUPPORTED:
        res["status"] = "skipped"
        res["note"] = f"{ext or '无扩展名'} 不是资料格式，已跳过"
        return res

    st = path.stat()
    pkey = _path_key(path)
    digest = _sha256(path)

    existing = conn.execute(
        "SELECT * FROM documents WHERE path_key=? AND deleted_at IS NULL", (pkey,)
    ).fetchone()

    # 同一份文件换了位置（换电脑/挪目录）→ 更新路径即可，不必重解析
    if existing is None:
        by_hash = conn.execute(
            "SELECT * FROM documents WHERE file_hash=? AND deleted_at IS NULL LIMIT 1",
            (digest,)).fetchone()
        if by_hash is not None and str(by_hash["file_path"]) != str(path):
            conn.execute(
                "UPDATE documents SET file_path=?, path_key=?, file_size=?, file_mtime=?,"
                " updated_at=? WHERE id=?",
                (str(path), pkey, st.st_size, int(st.st_mtime * 1000), now_ms(),
                 by_hash["id"]))
            res.update(status="relocated", doc_id=by_hash["id"],
                       chunks=conn.execute("SELECT COUNT(*) FROM doc_chunks WHERE doc_id=?",
                                           (by_hash["id"],)).fetchone()[0],
                       chars=by_hash["char_count"],
                       note=f"内容相同，已把源文件路径更新为新位置")
            return res

    # 内容没变 **且** 解析管线版本相同才算「未变化」。
    # 否则必须重新解析，避免旧版解析/OCR 的脏数据被永久固化。
    same_version = bool(existing) and (existing["parse_version"] or 0) == PARSE_VERSION
    if existing and existing["file_hash"] == digest and same_version:
        res.update(status="unchanged", doc_id=existing["id"],
                   chunks=conn.execute("SELECT COUNT(*) FROM doc_chunks WHERE doc_id=?",
                                       (existing["id"],)).fetchone()[0],
                   chars=existing["char_count"],
                   quality=existing["quality"] if "quality" in existing.keys() else 1.0,
                   note="内容与解析版本均未变化，已跳过")
        return res

    try:
        blocks = parse_any(path)
    except DocxError as e:
        res["status"] = "failed"
        res["note"] = str(e)
        return res

    chunks = chunker.chunk_blocks(blocks, title)
    if not chunks:
        res["status"] = "failed"
        res["note"] = "没有解析到可索引的正文（可能是整篇扫描图或纯公式）"
        return res

    full_text = "\n".join(c["text"] for c in chunks)
    quality, quality_note = quality_mod.score_chunks(chunks)
    ts = now_ms()
    note = "解析版本升级，已重建索引" if (existing and existing["file_hash"] == digest
                                   and not same_version) else ""

    conn.execute("BEGIN")
    try:
        if existing:
            doc_id = existing["id"]
            try:
                from .ai import vectors as _vectors
                _vectors.delete_for_doc(conn, doc_id)
            except Exception:
                pass
            conn.execute("DELETE FROM doc_chunks WHERE doc_id=?", (doc_id,))
            conn.execute(
                "UPDATE documents SET title=?, file_path=?, file_hash=?, file_size=?, "
                "file_mtime=?, parse_status=2, parse_note='', char_count=?, "
                "parse_version=?, quality=?, quality_note=?, updated_at=? "
                "WHERE id=?",
                (title, str(path), digest, st.st_size, int(st.st_mtime),
                 len(full_text), PARSE_VERSION, quality, quality_note, ts, doc_id),
            )
            res["status"] = "updated"
        else:
            cur = conn.execute(
                "INSERT INTO documents(title,file_path,path_key,file_hash,file_size,"
                "file_mtime,file_type,parse_status,char_count,parse_version,"
                "quality,quality_note,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,2,?,?,?,?,?,?)",
                (title, str(path), pkey, digest, st.st_size, int(st.st_mtime),
                 ext.lstrip("."), len(full_text), PARSE_VERSION, quality, quality_note,
                 ts, ts),
            )
            doc_id = cur.lastrowid
            res["status"] = "imported"

        conn.executemany(
            "INSERT INTO doc_chunks(doc_id,ord,heading_path,text,char_len,is_table) "
            "VALUES(?,?,?,?,?,?)",
            [(doc_id, c["ord"], c["heading_path"], c["text"], c["char_len"], c["is_table"])
             for c in chunks],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    if note:
        res["note"] = note
    res["quality"] = quality
    res["quality_note"] = quality_note

    suggestion = _suggest_nodes(
        conn, title, full_text,
        headings=[c["heading_path"] for c in chunks],
    )
    res.update(doc_id=doc_id, chunks=len(chunks), chars=len(full_text),
               suggestion=suggestion)
    res["text_preview"] = full_text[:400]
    return res


def auto_mount(conn, doc_id: int, suggestion: List[dict]) -> Optional[int]:
    """建议足够明确时自动挂载，否则留在未分类（由用户决定）。

    判定：第一名分数 ≥ 第二名 1.35 倍，且分数 ≥ 8。
    """
    if not suggestion:
        return None
    first = suggestion[0]
    second_score = suggestion[1]["score"] if len(suggestion) > 1 else 0
    clear = second_score == 0 or first["score"] >= second_score * 1.35
    if not clear or first["score"] < 8:
        return None
    mount_smart(conn, doc_id, first["node_id"])
    return first["node_id"]


def mount(conn, doc_id: int, node_id: int) -> None:
    conn.execute(
        "INSERT INTO node_documents(node_id,document_id,created_at) VALUES(?,?,?) "
        "ON CONFLICT(node_id,document_id) DO NOTHING",
        (node_id, doc_id, now_ms()),
    )
    bump_library_version(conn)


def mount_smart(conn, doc_id: int, node_id: int) -> None:
    """挂到目标节点；如果目标是正式节点，同时解除「未分类」这类系统节点上的临时挂载。"""
    mount(conn, doc_id, node_id)
    row = conn.execute("SELECT is_system FROM nodes WHERE id=?", (node_id,)).fetchone()
    if row is not None and row[0] == 0:
        conn.execute(
            "DELETE FROM node_documents WHERE document_id=? AND node_id IN "
            "(SELECT id FROM nodes WHERE is_system=1)", (doc_id,))


def unmount(conn, doc_id: int, node_id: int) -> None:
    conn.execute("DELETE FROM node_documents WHERE node_id=? AND document_id=?",
                 (node_id, doc_id))
    bump_library_version(conn)


def unmount_all_user_nodes(conn, doc_id: int) -> int:
    """解除该文档在「非系统节点」上的所有挂载（拖拽移动文档时用）。"""
    cur = conn.execute(
        "DELETE FROM node_documents WHERE document_id=? AND node_id IN "
        "(SELECT id FROM nodes WHERE is_system=0)", (doc_id,))
    bump_library_version(conn)
    return cur.rowcount or 0


def set_doc_nodes(conn, doc_id: int, node_ids) -> list:
    """一次设置文档的挂载集合（支持一份文档挂多个节点）。空集合则回到「未分类」。"""
    wanted = []
    for nid in node_ids or []:
        try:
            nid = int(nid)
        except (TypeError, ValueError):
            continue
        row = conn.execute(
            "SELECT id, is_system FROM nodes WHERE id=? AND deleted_at IS NULL", (nid,)
        ).fetchone()
        if row is not None and row["is_system"] == 0 and nid not in wanted:
            wanted.append(nid)

    conn.execute(
        "DELETE FROM node_documents WHERE document_id=? AND node_id IN "
        "(SELECT id FROM nodes WHERE is_system=0)", (doc_id,))
    for nid in wanted:
        conn.execute(
            "INSERT INTO node_documents(node_id,document_id,created_at) VALUES(?,?,?) "
            "ON CONFLICT(node_id,document_id) DO NOTHING", (nid, doc_id, now_ms()))
    # 有正式挂载就不需要「未分类」
    conn.execute(
        "DELETE FROM node_documents WHERE document_id=? AND node_id IN "
        "(SELECT id FROM nodes WHERE is_system=1)", (doc_id,))
    if not wanted:
        unc = tree.ensure_uncategorized(conn)
        conn.execute(
            "INSERT INTO node_documents(node_id,document_id,created_at) VALUES(?,?,?) "
            "ON CONFLICT(node_id,document_id) DO NOTHING", (unc, doc_id, now_ms()))
    bump_library_version(conn)
    return wanted


# ---------------- 文档删除 / 恢复 / 彻底删除 ----------------
def delete_document(conn, doc_id: int) -> None:
    """软删除文档：移入回收站，文件本身不动，挂载关系保留以便恢复。"""
    ts = now_ms()
    cur = conn.execute(
        "UPDATE documents SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
        (ts, ts, doc_id))
    if not cur.rowcount:
        raise ValueError("文档不存在或已在回收站")
    bump_library_version(conn)


def restore_document(conn, doc_id: int) -> None:
    cur = conn.execute(
        "UPDATE documents SET deleted_at=NULL, updated_at=? WHERE id=? AND deleted_at IS NOT NULL",
        (now_ms(), doc_id))
    if not cur.rowcount:
        raise ValueError("该文档不在回收站")
    bump_library_version(conn)


def purge_document(conn, doc_id: int) -> None:
    """彻底删除文档记录（不可恢复）；磁盘上的原文件不受影响。"""
    row = conn.execute("SELECT id, deleted_at FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row is None:
        raise ValueError("文档不存在")
    if row["deleted_at"] is None:
        raise ValueError("只能彻底删除回收站里的文档；正在使用的请先删除")
    try:
        from .ai import vectors as _vectors
        _vectors.delete_for_doc(conn, doc_id)
    except Exception:
        pass
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    bump_library_version(conn)


def list_deleted_documents(conn, limit: int = 500) -> list:
    rows = conn.execute(
        "SELECT d.id, d.title, d.file_type, d.deleted_at, d.char_count, "
        "       (SELECT GROUP_CONCAT(n.name, ' / ') FROM node_documents nd "
        "        JOIN nodes n ON n.id = nd.node_id "
        "        WHERE nd.document_id = d.id) AS node_names "
        "FROM documents d WHERE d.deleted_at IS NOT NULL "
        "ORDER BY d.deleted_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def purge_all_deleted_documents(conn) -> int:
    cur = conn.execute("DELETE FROM documents WHERE deleted_at IS NOT NULL")
    n = cur.rowcount or 0
    bump_library_version(conn)
    return n


def import_path(conn, path: str, mount_mode: str = "auto") -> dict:
    """mount_mode: auto | none | uncategorized"""
    files = scan(path)
    results = []
    for f in files:
        r = import_file(conn, f)
        if r["doc_id"] and mount_mode == "auto" and r["status"] in ("imported", "updated"):
            node_id = auto_mount(conn, r["doc_id"], r["suggestion"])
            r["mounted_to"] = node_id
            if node_id is None and mount_mode == "auto":
                unc = tree.ensure_uncategorized(conn)
                mount(conn, r["doc_id"], unc)
                r["mounted_to"] = unc
        results.append(r)

    changed = [r for r in results if r["status"] in ("imported", "updated")]
    if changed:
        bump_library_version(conn)
    return {
        "scanned": len(results),
        "imported": sum(1 for r in results if r["status"] == "imported"),
        "updated": sum(1 for r in results if r["status"] == "updated"),
        "unchanged": sum(1 for r in results if r["status"] == "unchanged"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "items": results,
    }


# ---------------- A1：按解析版本批量重建索引 ----------------
def outdated_documents(conn, limit: int = 0):
    """列出解析版本落后于当前版本的文档。"""
    sql = ("SELECT id, title, file_path, parse_version FROM documents "
           "WHERE deleted_at IS NULL AND COALESCE(parse_version,0) < ? "
           "ORDER BY id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (PARSE_VERSION,)).fetchall()


def rebuild(conn, limit: int = 0, dry_run: bool = False) -> dict:
    """把解析版本过旧的文档重新解析一遍（源文件不动，只重建派生数据）。"""
    rows = outdated_documents(conn, limit)
    report = {
        "current_version": PARSE_VERSION,
        "outdated": len(rows),
        "rebuilt": 0,
        "failed": 0,
        "missing": 0,
        "dry_run": dry_run,
        "items": [],
    }
    if dry_run:
        report["items"] = [{"id": r["id"], "title": r["title"],
                            "from_version": r["parse_version"]} for r in rows]
        return report

    for r in rows:
        p = Path(r["file_path"])
        item = {"id": r["id"], "title": r["title"],
                "from_version": r["parse_version"], "status": ""}
        if not p.exists():
            conn.execute(
                "UPDATE documents SET parse_status=3, "
                "parse_note='源文件不存在，无法重建（可能被移动或删除）', updated_at=? "
                "WHERE id=?", (now_ms(), r["id"]))
            item["status"] = "missing"
            report["missing"] += 1
        else:
            res = import_file(conn, p)
            item["status"] = res["status"]
            item["note"] = res.get("note", "")
            item["quality"] = res.get("quality")
            if res["status"] in ("imported", "updated"):
                report["rebuilt"] += 1
            else:
                report["failed"] += 1
        report["items"].append(item)

    if report["rebuilt"]:
        bump_library_version(conn)
    return report
