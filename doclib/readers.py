# -*- coding: utf-8 -*-
"""多格式解析：docx / pptx / md / txt / pdf，统一输出「块」列表。

块格式与 docx_reader 一致：
    {"kind": "p" | "table", "text": str, "style": str, "level": int | None}
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from .docx_reader import DocxError, parse_docx

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_HEADING_NAMED = re.compile(r"^(第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节篇部页]"
                            r"|[0-9]{1,2}(\.[0-9]{1,2}){0,3}[\s、.．]"
                            r"|[一二三四五六七八九十]+[、.．])")
_MD_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_INLINE = [
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),          # 图片
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),      # 链接
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"__([^_]+)__"), r"\1"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
    (re.compile(r"~~([^~]+)~~"), r"\1"),
    (re.compile(r"<[^>]{1,80}>"), ""),                  # HTML 标签
]


def _blk(text: str, level=None, kind="p") -> dict:
    return {"kind": kind, "text": text, "style": "", "level": level}


# ---------------- 纯文本 / Markdown ----------------
def _detect_encoding(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    try:
        import chardet
        guess = chardet.detect(raw[:20000]).get("encoding")
        if guess:
            return guess
    except Exception:
        pass
    return "utf-8"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    return raw.decode(_detect_encoding(raw), errors="replace")


def parse_text(path: Path, markdown: bool = False) -> List[dict]:
    text = _read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    blocks: List[dict] = []

    in_fence = False
    in_front = False
    if markdown and lines and lines[0].strip() == "---":
        in_front = True

    for no, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        if in_front:
            if no > 0 and line.strip() == "---":
                in_front = False
            continue
        if markdown:
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence:
                m = _MD_HEAD.match(line)
                if m:
                    blocks.append(_blk(m.group(2).strip(), level=len(m.group(1))))
                    continue
                for pat, rep in _MD_INLINE:
                    line = pat.sub(rep, line)
            if not in_fence:
                line = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", line)
        s = line.strip()
        if not s:
            continue
        if (not markdown) and len(s) <= 40 and _HEADING_NAMED.match(s):
            blocks.append(_blk(s, level=2 if re.match(r"^[0-9]", s) else 1))
            continue
        blocks.append(_blk(s))
    return blocks


# ---------------- PPTX ----------------
def parse_pptx(path: Path) -> List[dict]:
    try:
        zf = zipfile.ZipFile(str(path))
    except zipfile.BadZipFile as e:
        raise DocxError(f"不是有效的 .pptx：{e}") from e
    names = [n for n in zf.namelist()
             if re.match(r"^ppt/slides/slide\d+\.xml$", n)]
    if not names:
        raise DocxError("这个 .pptx 里没有幻灯片（可能只是模板）")
    names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))

    blocks: List[dict] = []
    for idx, name in enumerate(names, 1):
        try:
            root = ET.fromstring(zf.read(name))
        except ET.ParseError:
            continue
        paras: List[str] = []
        for p in root.iter(A + "p"):
            bits = [t.text for t in p.iter(A + "t") if t.text]
            line = "".join(bits).strip()
            if line:
                paras.append(line)
        if not paras:
            continue
        title = ""
        if len(paras[0]) <= 40:
            title = paras[0]
        head = f"第 {idx} 张幻灯片" + (f"：{title}" if title else "")
        blocks.append(_blk(head, level=2))
        body = paras[1:] if title else paras
        for line in body:
            blocks.append(_blk(line))
    zf.close()
    return blocks


# ---------------- PDF ----------------
def parse_pdf(path: Path, max_pages: int = 500) -> List[dict]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise DocxError(
            "读取 PDF 需要 pypdf。请在命令行执行：pip install pypdf"
        ) from e
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        raise DocxError(f"PDF 打不开：{e}") from e

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise DocxError("PDF 有密码保护，无法读取") from e

    from . import config, ocr

    ocr_ok = ocr.available()["ok"] and ocr.has_pdfium()
    ocr_used = 0
    blocks: List[dict] = []
    total = len(reader.pages)

    for i, page in enumerate(reader.pages[:max_pages], 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()

        # 没有文字层（扫描件 / 图片型 PDF）→ 渲染该页再 OCR
        if len(text) < config.OCR_MIN_TEXT and ocr_ok and ocr_used < config.OCR_MAX_PAGES:
            try:
                page_text = ocr.ocr_pdf_page(path, i - 1)
                ocr_used += 1
                if len(page_text.strip()) > len(text):
                    text = page_text.strip()
            except Exception:
                pass

        if not text:
            continue
        blocks.append(_blk(f"第 {i} 页", level=2))
        for line in text.split("\n"):
            s = line.strip()
            if s:
                blocks.append(_blk(s))

    if not blocks:
        hint = "" if ocr_ok else "（本机 OCR 未启用：pip install pypdfium2 + winrt-* 包）"
        raise DocxError(f"这个 PDF 没有可提取的文字，可能是扫描件{hint}")
    if total > max_pages:
        blocks.append(_blk(f"（本 PDF 共 {total} 页，仅索引了前 {max_pages} 页）"))
    if ocr_used:
        blocks.append(_blk(f"（其中 {ocr_used} 页为图片，已用 OCR 识别）"))
    return blocks


# ---------------- 图片（OCR） ----------------
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}


def parse_image(path: Path) -> List[dict]:
    from . import ocr
    if not ocr.available()["ok"]:
        raise DocxError(
            "这台机器暂时没有 OCR 能力，无法读取图片文字。\n"
            "启用方法：pip install pypdfium2 以及 winrt-runtime / winrt-Windows.Media.Ocr 等包")
    text = ocr.ocr_image(path)
    if not text.strip():
        raise DocxError("这张图片里没有识别出文字（可能是纯图形/照片）")
    blocks = [_blk("图片文字", level=2)]
    for line in text.split("\n"):
        s = line.strip()
        if s:
            blocks.append(_blk(s))
    return blocks


# ---------------- 统一入口 ----------------
TEXT_EXT = {".txt", ".text", ".log", ".csv"}
MD_EXT = {".md", ".markdown", ".mdown"}
PPTX_EXT = {".pptx"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
DOC_EXT = {".doc"}

SUPPORTED_EXT = (DOCX_EXT | DOC_EXT | TEXT_EXT | MD_EXT | PPTX_EXT | PDF_EXT | IMAGE_EXT)


def parse_any(path) -> List[dict]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in DOCX_EXT:
        return parse_docx(str(p))
    if ext in DOC_EXT:
        from .convert import convert_doc
        return parse_docx(str(convert_doc(p)))
    if ext in MD_EXT:
        return parse_text(p, markdown=True)
    if ext in TEXT_EXT:
        return parse_text(p, markdown=False)
    if ext in PPTX_EXT:
        return parse_pptx(p)
    if ext in PDF_EXT:
        return parse_pdf(p)
    if ext in IMAGE_EXT:
        return parse_image(p)
    raise DocxError(f"不支持的格式：{ext}")
