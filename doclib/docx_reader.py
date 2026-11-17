# -*- coding: utf-8 -*-
"""零依赖 .docx 解析器（只用标准库 zipfile + xml.etree）。

输出按文档顺序排列的块列表：
    {"kind": "p" | "table", "text": str, "style": str, "level": int | None}
level 为标题级别（1 起），非标题为 None。

不支持 .doc（旧二进制格式）——导入时会明确报错而不是静默跳过。
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

_HEADING_NAME_RE = re.compile(r"^(?:heading|标题)\s*(\d)$", re.IGNORECASE)
_TOC_HINT_RE = re.compile(r"^(toc|目录|contents)", re.IGNORECASE)


class DocxError(Exception):
    pass


def _style_table(zf: zipfile.ZipFile) -> Dict[str, dict]:
    """styleId -> {name, outline}"""
    table: Dict[str, dict] = {}
    try:
        raw = zf.read("word/styles.xml")
    except KeyError:
        return table
    root = ET.fromstring(raw)
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        if not sid:
            continue
        name_el = st.find(W + "name")
        name = name_el.get(W + "val") if name_el is not None else sid
        outline = None
        ppr = st.find(W + "pPr")
        if ppr is not None:
            ol = ppr.find(W + "outlineLvl")
            if ol is not None:
                try:
                    outline = int(ol.get(W + "val")) + 1
                except (TypeError, ValueError):
                    outline = None
        table[sid] = {"name": name or sid, "outline": outline}
    return table


def _paragraph_text(p: ET.Element) -> str:
    parts: List[str] = []
    for el in p.iter():
        tag = el.tag
        if tag == W + "t" or tag == M + "t":
            if el.text:
                parts.append(el.text)
        elif tag == W + "tab":
            parts.append("\t")
        elif tag == W + "br":
            parts.append("\n")
        elif tag == W + "noBreakHyphen":
            parts.append("-")
    return "".join(parts)


def _heading_level(p: ET.Element, styles: Dict[str, dict]) -> Optional[int]:
    ppr = p.find(W + "pPr")
    if ppr is None:
        return None
    ps = ppr.find(W + "pStyle")
    sid = ps.get(W + "val") if ps is not None else None
    if sid and sid in styles:
        info = styles[sid]
        m = _HEADING_NAME_RE.match((info.get("name") or "").strip())
        if m:
            return int(m.group(1))
        if info.get("outline"):
            return int(info["outline"])
    if sid:
        m = _HEADING_NAME_RE.match(sid.strip())
        if m:
            return int(m.group(1))
    ol = ppr.find(W + "outlineLvl")
    if ol is not None:
        try:
            return int(ol.get(W + "val")) + 1
        except (TypeError, ValueError):
            return None
    return None


def _style_id(p: ET.Element) -> str:
    ppr = p.find(W + "pPr")
    if ppr is None:
        return ""
    ps = ppr.find(W + "pStyle")
    return (ps.get(W + "val") or "") if ps is not None else ""


def _is_toc(p: ET.Element, styles: Dict[str, dict]) -> bool:
    sid = _style_id(p)
    name = (styles.get(sid, {}).get("name") or sid or "").strip()
    return bool(_TOC_HINT_RE.match(name))


def _table_text(tbl: ET.Element) -> str:
    lines: List[str] = []
    for tr in tbl.findall(W + "tr"):
        cells: List[str] = []
        for tc in tr.findall(W + "tc"):
            bits: List[str] = []
            for p in tc.findall(W + "p"):
                t = _paragraph_text(p).strip()
                if t:
                    bits.append(t)
            cells.append(" ".join(bits))
        row = " | ".join(c for c in cells if c)
        if row:
            lines.append(row)
    return "\n".join(lines)


def parse_docx(path: str) -> List[dict]:
    """解析 .docx，返回块列表。"""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise DocxError(f"不是有效的 .docx（可能是旧版 .doc 或已损坏）：{e}") from e
    try:
        raw = zf.read("word/document.xml")
    except KeyError as e:
        raise DocxError("这不是 Word 文档（缺少 word/document.xml）") from e
    styles = _style_table(zf)
    root = ET.fromstring(raw)
    body = root.find(W + "body")
    if body is None:
        return []

    blocks: List[dict] = []
    skip_heading_ctx = False

    for el in list(body):
        if el.tag == W + "p":
            text = _paragraph_text(el).strip()
            level = _heading_level(el, styles)
            if _is_toc(el, styles):
                continue
            if not text:
                continue
            if level is not None and _TOC_HINT_RE.match(text):
                skip_heading_ctx = True
                continue
            if level is not None:
                skip_heading_ctx = False
            elif skip_heading_ctx:
                # 「目录」标题后的目录正文（未被样式标记的情况）也跳过
                continue
            blocks.append({
                "kind": "p",
                "text": text,
                "style": styles.get(_style_id(el), {}).get("name", ""),
                "level": level,
            })
        elif el.tag == W + "tbl":
            text = _table_text(el)
            if text.strip():
                blocks.append({"kind": "table", "text": text, "style": "table", "level": None})
    zf.close()
    return blocks
