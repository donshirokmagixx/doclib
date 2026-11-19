# -*- coding: utf-8 -*-
"""阅读器数据层：文档头、正文分页、TOC、原文件解析、文本原文与 HTTP Range。

本模块只读写数据库与本地文件，不构造 HTTP 响应：
- 文档、路径必须来自未删除的 documents 行，不接受任意路径；
- 分块来自 doc_chunks（0006 起带 page/start_off/end_off）；
- 原文件 MIME 用显式白名单，不依赖系统注册表。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

from . import tree

DEFAULT_LIMIT = 200
MAX_LIMIT = 500

# 原文件流白名单：后缀 -> Content-Type。
MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

TEXT_TYPES = {"md", "markdown", "txt"}

_HEADING_SEP = " > "
_HEADER_CTRL = re.compile(r'[\x00-\x1f\x7f"\\/]')
_DIGITS = re.compile(r"[0-9]+")


def _doc_row(conn, doc_id):
    """未删除文档行；id 不合法或不存在返回 None。"""
    try:
        did = int(doc_id)
    except (TypeError, ValueError):
        return None
    if did <= 0:
        return None
    return conn.execute(
        "SELECT id, title, file_path, file_type, file_size, parse_status "
        "FROM documents WHERE id=? AND deleted_at IS NULL",
        (did,),
    ).fetchone()


def get_doc(conn, doc_id) -> Optional[dict]:
    """文档头 + 挂载节点 + 分区；文档不存在/已软删返回 None。

    partition_id 取第一个所属分区非空的挂载节点；只挂在系统节点（未分类）
    或多分区节点上时按第一个分区计，没有分区则为 None。
    """
    d = _doc_row(conn, doc_id)
    if d is None:
        return None
    rows = conn.execute(
        "SELECT n.id, n.name FROM node_documents nd "
        "JOIN nodes n ON n.id = nd.node_id "
        "WHERE nd.document_id=? AND n.deleted_at IS NULL "
        "ORDER BY n.id",
        (d["id"],),
    ).fetchall()
    nodes = [{"id": r["id"], "name": r["name"]} for r in rows]
    partition_id = None
    for node in nodes:
        pid = tree.partition_of_node(conn, node["id"])
        if pid is not None:
            partition_id = pid
            break
    return {
        "id": d["id"],
        "title": d["title"],
        "file_path": d["file_path"],
        "file_type": d["file_type"],
        "file_size": d["file_size"],
        "parse_status": d["parse_status"],
        "nodes": nodes,
        "partition_id": partition_id,
    }


def _coerce_limit(limit) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, n))


def _window_start(conn, doc_id: int, total: int, limit: int, around) -> int:
    """around 所在块居中（前一半、后一半）；无 around 或找不到时从 0 开始。"""
    if around is None or total <= 0:
        return 0
    try:
        around_id = int(around)
    except (TypeError, ValueError):
        return 0
    target = conn.execute(
        "SELECT ord FROM doc_chunks WHERE id=? AND doc_id=?",
        (around_id, doc_id),
    ).fetchone()
    if target is None:
        return 0
    pos = conn.execute(
        "SELECT COUNT(*) FROM doc_chunks WHERE doc_id=? AND ord<?",
        (doc_id, target["ord"]),
    ).fetchone()[0]
    start = max(0, pos - limit // 2)
    if total > limit:
        # 靠近末尾时整体前移，保证返回满一页。
        start = min(start, total - limit)
    else:
        start = 0
    return start


def _heading_parts(heading_path: str) -> list:
    return [p.strip() for p in (heading_path or "").split(_HEADING_SEP) if p.strip()]


def _build_toc(rows) -> list:
    """按 heading_path 的 " > " 层级生成 TOC，连续重复的路径只记一次。"""
    toc = []
    prev = []
    for r in rows:
        parts = _heading_parts(r["heading_path"])
        if not parts:
            prev = []
            continue
        if parts == prev:
            continue
        common = 0
        while (common < len(parts) and common < len(prev)
               and parts[common] == prev[common]):
            common += 1
        for i in range(common, len(parts)):
            toc.append({
                "level": i + 1,
                "title": parts[i],
                "chunk_id": r["id"],
                "ord": r["ord"],
            })
        prev = parts
    return toc


def reader_payload(conn, doc_id, around=None, limit=200) -> dict:
    """阅读内容：文档头、TOC、一页正文块。

    limit 限制在 1..500；around 是 doc_chunks.id，返回其前后各一半的窗口，
    找不到该块（已失效/属于别的文档）时退回从 ord 0 开始。
    """
    doc = get_doc(conn, doc_id)
    if doc is None:
        return {"ok": False, "error": "文档不存在"}

    limit = _coerce_limit(limit)
    total = conn.execute(
        "SELECT COUNT(*) FROM doc_chunks WHERE doc_id=?", (doc["id"],)
    ).fetchone()[0]
    start = _window_start(conn, doc["id"], total, limit, around)

    rows = conn.execute(
        "SELECT id, ord, heading_path, text, char_len, is_table, page,"
        " start_off, end_off FROM doc_chunks WHERE doc_id=? "
        "ORDER BY ord LIMIT ? OFFSET ?",
        (doc["id"], limit, start),
    ).fetchall()
    chunks = [{
        "id": r["id"],
        "ord": r["ord"],
        "heading_path": r["heading_path"],
        "text": r["text"],
        "char_len": r["char_len"],
        "is_table": r["is_table"],
        "page": r["page"],
        "start_off": r["start_off"],
        "end_off": r["end_off"],
    } for r in rows]

    toc_rows = conn.execute(
        "SELECT id, ord, heading_path FROM doc_chunks WHERE doc_id=? ORDER BY ord",
        (doc["id"],),
    ).fetchall()
    return {
        "ok": True,
        "doc": doc,
        "toc": _build_toc(toc_rows),
        "chunks": chunks,
        "total": total,
        "has_more": start + len(rows) < total,
    }


def _safe_download_name(name: str) -> str:
    """去掉会破坏 Content-Disposition 的控制字符与路径分隔符。"""
    name = _HEADER_CTRL.sub("", name or "").strip()
    if len(name) > 180:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 12:
            name = stem[:180 - len(ext) - 1] + "." + ext
        else:
            name = name[:180]
    return name


def resolve_file(conn, doc_id) -> Optional[Tuple[str, str, str]]:
    """原文件流信息 (path, mime, download_name)；不可用返回 None。

    只认数据库里的未删除文档；路径必须存在且为普通文件，后缀必须在
    MIME_BY_EXT 白名单内。
    """
    d = _doc_row(conn, doc_id)
    if d is None:
        return None
    try:
        path = Path(str(d["file_path"])).expanduser()
        if not path.is_file():
            return None
    except (OSError, ValueError):
        return None
    mime = MIME_BY_EXT.get(path.suffix.lower())
    if mime is None:
        return None
    name = _safe_download_name(path.name)
    if not name:
        name = "document-%s%s" % (d["id"], path.suffix.lower())
    return str(path), mime, name


def _decode_text(raw: bytes) -> Tuple[Optional[str], Optional[str]]:
    for codec in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(codec), ("utf-8" if codec == "utf-8-sig" else codec)
        except UnicodeDecodeError:
            continue
    return None, None


def raw_text(conn, doc_id) -> dict:
    """md/txt/markdown 原文；UTF-8（含 BOM）优先，回退 GB18030。"""
    d = _doc_row(conn, doc_id)
    if d is None:
        return {"ok": False, "error": "文档不存在"}
    path = Path(str(d["file_path"]))
    ftype = str(d["file_type"] or "").strip().lower().lstrip(".")
    if not ftype:
        ftype = path.suffix.lower().lstrip(".")
    if ftype not in TEXT_TYPES:
        return {"ok": False, "error": "该格式不支持读取原文，请打开原文件"}
    try:
        if not path.is_file():
            return {"ok": False, "error": "文件不存在"}
        raw = path.read_bytes()
    except OSError:
        return {"ok": False, "error": "文件读取失败"}
    text, encoding = _decode_text(raw)
    if text is None:
        return {"ok": False, "error": "文本编码无法识别（需要 UTF-8 或 GB18030）"}
    try:
        mtime = int(path.stat().st_mtime)
    except OSError:
        mtime = 0
    return {"ok": True, "text": text, "encoding": encoding, "mtime": mtime}


def parse_range(header, size) -> Optional[Tuple[int, int]]:
    """解析单段 HTTP Range，返回闭区间 (start, end)。

    - 没有 Range 头（None/空）返回 None，调用方按 200 返回整个文件；
    - 支持 bytes=start-end、bytes=start-、bytes=-suffix；
    - 后缀长度超过文件大小时返回整个文件；
    - 非法头、start 越界、end 越界、空文件都抛 ValueError（调用方回 416）。
    """
    if header is None:
        return None
    if not isinstance(header, str):
        raise ValueError("Range 头必须是字符串")
    value = header.strip()
    if not value:
        return None
    unit, sep, spec = value.partition("=")
    if not sep or unit.strip().lower() != "bytes":
        raise ValueError("只支持 bytes= 范围")
    spec = spec.strip()
    if not spec or "," in spec:
        raise ValueError("只支持单段 Range")
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ValueError("文件大小不合法") from None
    if size < 0:
        raise ValueError("文件大小不合法")
    if size == 0:
        raise ValueError("空文件不支持 Range")

    first, dash, last = spec.partition("-")
    if not dash:
        raise ValueError("Range 缺少 '-'")
    first, last = first.strip(), last.strip()
    if not first:
        if not _DIGITS.fullmatch(last):
            raise ValueError("后缀长度不合法")
        suffix = int(last)
        if suffix <= 0:
            raise ValueError("后缀长度必须大于 0")
        suffix = min(suffix, size)
        return size - suffix, size - 1
    if not _DIGITS.fullmatch(first):
        raise ValueError("起始位置不合法")
    start = int(first)
    if start >= size:
        raise ValueError("起始位置越界")
    if not last:
        return start, size - 1
    if not _DIGITS.fullmatch(last):
        raise ValueError("结束位置不合法")
    end = int(last)
    if end < start or end >= size:
        raise ValueError("结束位置不合法")
    return start, end
