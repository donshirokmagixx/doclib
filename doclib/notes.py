# -*- coding: utf-8 -*-
"""把问答会话导出成 Word —— 两种版式，零依赖实现（只用 zipfile）。

版式一「问答笔记」（qa）：
    标题 → 元信息 → （多问答时）本篇问答 → 每问：Q1｜问题 + 答案 + 来源（可选摘录）→ 页脚统计

版式二「复习提纲」（outline，按复习资料规范做提纲化）：
    封面 → 一、速览要点（≤12 条，每条 ≤40 字，回指（见 Qn））
         → 二、分节提纲（H1 章节 → H2 小节 → 要点行）
         → 三、公式速查（表：编号 | 表达式 | 出处）
         → 四、易错清单（≤40 字/条，回指（见 Qn））
         → 五、自测与提示（问题 → 提示=该问答案首句）
         → 六、来源索引

两种版式都支持：只导出勾选的问答（msg_ids）、来源附原文摘录（include_snippet）、
多会话合并（batch：每个会话作一章）。

标题一律使用 Word 内置标题样式（Heading1/Heading2），便于导航窗格与自动目录。
"""
import io
import os
import re
import time
import zipfile
from xml.sax.saxutils import escape

from . import config

EXPORT_DIR = config.DATA_DIR / "exports"

_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# 内置标题样式：引用 Heading1 / Heading2，Word 导航窗格与自动目录都能识别
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults>
  <w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="微软雅黑"/>
    <w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:eastAsia="zh-CN"/>
  </w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="60" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
  <w:name w:val="Normal"/><w:qFormat/>
</w:style>
<w:style w:type="paragraph" w:styleId="Title">
  <w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:spacing w:before="240" w:after="120"/><w:jc w:val="center"/></w:pPr>
  <w:rPr><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/><w:color w:val="1F3864"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading1">
  <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="0"/>
    <w:pBdr><w:bottom w:val="single" w:sz="6" w:space="2" w:color="C9D3DF"/></w:pBdr></w:pPr>
  <w:rPr><w:b/><w:sz w:val="30"/><w:szCs w:val="30"/><w:color w:val="1F3864"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading2">
  <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="180" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr>
  <w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/><w:color w:val="2E5A88"/></w:rPr>
</w:style>
</w:styles>"""


def _core(title: str, creator: str = "DocLib") -> str:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(title)}</dc:title>'
            f'<dc:creator>{escape(creator)}</dc:creator>'
            f'<cp:lastModifiedBy>{escape(creator)}</cp:lastModifiedBy>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            '</cp:coreProperties>')


def _r(text: str, *, bold: bool = False, italic: bool = False,
       size: int = 0, color: str = "", underline: bool = False) -> str:
    if text == "":
        return "<w:r><w:t/></w:r>"
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if underline:
        props.append('<w:u w:val="single"/>')
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _p(runs: str, *, style: str = "", align: str = "", before: int = 0, after: int = 60,
       indent: int = 0, line: int = 300, shade: str = "", border: bool = False,
       keep: bool = False, page_break: bool = False) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if keep:
        ppr.append("<w:keepNext/>")
    if page_break:
        ppr.append("<w:pageBreakBefore/>")
    ppr.append(f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="auto"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    if indent:
        ppr.append(f'<w:ind w:left="{indent}"/>')
    if shade:
        ppr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    if border:
        ppr.append('<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="2" w:color="C9D3DF"/></w:pBdr>')
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs}</w:p>"


def _cell(text: str, *, bold: bool = False, width: int = 0, shade: str = "") -> str:
    tcpr = []
    if width:
        tcpr.append(f'<w:tcW w:w="{width}" w:type="dxa"/>')
    if shade:
        tcpr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    tcpr.append('<w:vAlign w:val="center"/>')
    return ('<w:tc><w:tcPr>' + "".join(tcpr) + '</w:tcPr>'
            + _p(_r(text, bold=bold, size=18), after=20) + '</w:tc>')


def _table(rows, widths, *, header: bool = True) -> str:
    """三线表（表头加粗并加浅底）。rows[0] 为表头。"""
    n = len(widths)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    out = ['<w:tbl><w:tblPr>'
           '<w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
           '<w:top w:val="single" w:sz="8" w:color="7F7F7F"/>'
           '<w:left w:val="none" w:sz="0" w:color="auto"/>'
           '<w:bottom w:val="single" w:sz="8" w:color="7F7F7F"/>'
           '<w:right w:val="none" w:sz="0" w:color="auto"/>'
           '<w:insideH w:val="single" w:sz="4" w:color="D9D9D9"/>'
           '<w:insideV w:val="none" w:sz="0" w:color="auto"/>'
           '</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>',
           f"<w:tblGrid>{grid}</w:tblGrid>"]
    for i, row in enumerate(rows):
        cells = list(row) + [""] * (n - len(row))
        trpr = "<w:trPr><w:cantSplit/></w:trPr>"
        tcs = "".join(_cell(str(c), bold=(header and i == 0), width=widths[j],
                            shade="EDF2F8" if (header and i == 0) else "")
                      for j, c in enumerate(cells[:n]))
        out.append(f"<w:tr>{trpr}{tcs}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_TICK = re.compile(r"`([^`]+)`")
_BANNED = ("值得反复体会", "众所周知", "综上所述", "总的来说", "简单来说", "值得注意的是",
           "十分重要", "非常", "不难发现", "本章小结", "本章要点", "阅读建议")
# "没找到 / 无法判断"这类回答不是知识点，提纲里要丢掉
_NEGATIVE = ("没有找到", "找不到", "无法确认", "无法判断", "无法依据", "无法回答",
             "资料中没有", "资料中未", "片段没有", "片段未", "未给出", "没有涉及",
             "没有讨论", "没有明确", "缺乏", "无相关内容")
_PREFIX = ("补充要点：", "结论：", "前提说明：", "最接近的相关内容是：", "补充：",
           "记忆要点：", "一句话：", "主要性质对照如下（时域 → 频域）：",
           "片段只给出：", "片段只给出", "所给片段只给出：", "所给片段只给出",
           "资料只给出：", "资料只给出")


def _strip_md(s: str) -> str:
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_TICK.sub(r"\1", s)
    s = s.replace("**", "")
    for w in _BANNED:
        s = s.replace(w, "")
    return s.strip()


def _answer_paragraphs(text: str):
    out = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        s = line.strip()
        if s.startswith("#"):
            head = _strip_md(s.lstrip("#").strip())
            out.append(_p(_r(head, bold=True, size=24, color="1F3864"), before=120, after=60))
        elif re.match(r"^([-*•])\s+", s):
            body = _strip_md(re.sub(r"^([-*•])\s+", "", s))
            out.append(_p(_r("•　" + body, size=21), indent=360, after=40))
        elif re.match(r"^\d+[.)、]\s+", s):
            out.append(_p(_r(_strip_md(s), size=21), indent=360, after=40))
        else:
            out.append(_p(_r(_strip_md(s), size=21), after=60))
    return out


def _short(s: str, n: int = 60) -> str:
    s = re.sub(r"\s+", " ", _strip_md(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------- 提纲抽取（纯规则，不调用模型） ----------------

_FORMULA = re.compile(r"[=↔∝≈≡]|→|∫|Σ|∑")
_ISSUE = ("注意", "易错", "前提", "必须", "容易", "误区", "不成立", "不能直接", "不得", "边界")
_ENDS = "。；;！？!?"


def _clean_point(s: str) -> str:
    s = (s or "").strip()
    for pre in _PREFIX:
        if s.startswith(pre):
            s = s[len(pre):].strip()
    # 去掉标点前的空格（"主瓣变宽 。" → "主瓣变宽。"）
    s = re.sub(r"\s+([。；，、！？])", r"\1", s)
    # 去掉列表符号与中文序号（"三、"、"（1）"、"· " 等）
    s = re.sub(r"^[-*•·–—]\s*", "", s)
    s = re.sub(r"^[（(]?[一二三四五六七八九十]+[）)、.．]\s*", "", s)
    s = re.sub(r"^[（(]?\d+[）)][、.．]?\s*", "", s)
    s = re.sub(r"^(以及|并且|而且|还有|另外)", "", s.strip())
    s = s.strip().rstrip("；，、;,")
    return s.strip()


def _is_negative(s: str) -> bool:
    return any(w in (s or "") for w in _NEGATIVE)


def _split_lines(text: str):
    for raw in (text or "").splitlines():
        s = _strip_md(raw).strip(" \t-*•")
        if s:
            yield s


def _sentences(text: str):
    buf = ""
    for ch in (text or ""):
        buf += ch
        if ch in _ENDS:
            s = _strip_md(buf).strip()
            if s:
                yield s
            buf = ""
    tail = _strip_md(buf).strip()
    if tail:
        yield tail


def extract_points(pairs, max_points: int = 12, per_pair: int = 4):
    """提纲要点：优先项目符号行/箭头行，其次短句；每条 ≤40 字。"""
    out, seen = [], set()
    for idx, p in enumerate(pairs, 1):
        got = 0
        cands = []
        for line in _split_lines(p.get("a") or ""):
            if re.match(r"^([-*•]|\d+[.)、])\s*", line) or "→" in line:
                cands.append(line)
        if len(cands) < per_pair:
            cands += [s for s in _sentences(p.get("a") or "") if 8 <= len(s) <= 60]
        for c in cands:
            c = re.sub(r"^([-*•]|\d+[.)、])\s*", "", c).strip()
            c = re.sub(r"\[\d+\]", "", c).strip()
            if len(c) < 6:
                continue
            c = _clean_point(c)
            if len(c) < 6 or _is_negative(c):
                continue
            key = re.sub(r"[\s，。；：、（）()「」]", "", c)[:14]
            if key in seen:
                continue
            seen.add(key)
            out.append((_short(c, 40), idx))
            got += 1
            if got >= per_pair or len(out) >= max_points:
                break
        if len(out) >= max_points:
            break
    return out


def extract_formulas(pairs, limit: int = 18):
    """公式清单：含等号/↔/∫ 等符号的行。"""
    out, seen = [], set()
    for idx, p in enumerate(pairs, 1):
        for line in _split_lines(p.get("a") or ""):
            s = re.sub(r"^([-*•]|\d+[.)、])\s*", "", line).strip()
            s = re.sub(r"\[\d+\]", "", s).strip()
            if len(s) < 6 or len(s) > 90 or not _FORMULA.search(s):
                continue
            key = re.sub(r"\s", "", s)[:18]
            if key in seen:
                continue
            seen.add(key)
            out.append((_short(s, 60), idx))
            if len(out) >= limit:
                return out
    return out


def extract_issues(pairs, limit: int = 12):
    out, seen = [], set()
    for idx, p in enumerate(pairs, 1):
        for s in _sentences(p.get("a") or ""):
            s = _clean_point(re.sub(r"\[\d+\]", "", s).strip())
            if _is_negative(s) or not any(w in s for w in _ISSUE):
                continue
            if len(s) > 40:
                s = s[:38] + "…"
            key = re.sub(r"\s", "", s)[:12]
            if key in seen:
                continue
            seen.add(key)
            out.append((s, idx))
            if len(out) >= limit:
                return out
    return out


def _node_maps(conn):
    """返回 (nodes: id→{name,parent,depth,sort}, doc2node: doc_id→node_id)。"""
    nodes = {}
    for r in conn.execute(
            "SELECT id, parent_id, name, depth, sort_order, path, deleted_at "
            "FROM nodes"):
        if r["deleted_at"] is not None:
            continue
        nodes[r["id"]] = {"name": r["name"] or "", "parent": r["parent_id"],
                          "depth": r["depth"] or 0, "sort": r["sort_order"] or 0,
                          "path": r["path"] or ""}
    doc2node = {}
    for r in conn.execute(
            "SELECT nd.document_id, nd.node_id, n.depth FROM node_documents nd "
            "JOIN nodes n ON n.id = nd.node_id WHERE n.deleted_at IS NULL "
            "ORDER BY n.depth DESC"):
        doc2node.setdefault(r["document_id"], r["node_id"])   # 取最深的挂载
    return nodes, doc2node


def _top_of(nid, nodes):
    """归到"一级知识组"：深度 1 的节点作章；只有根节点时返回根。"""
    seen = set()
    cur = nid
    while (cur in nodes and nodes[cur]["parent"]
           and nodes[cur]["parent"] in nodes and cur not in seen
           and nodes[cur]["depth"] > 1):
        seen.add(cur)
        cur = nodes[cur]["parent"]
    return cur


def _node_for(item, conv_node, nodes, doc2node):
    """问句归属节点：会话节点（深度≥1 才算具体）→ 引用文档挂载 → 会话根节点。"""
    if conv_node and conv_node in nodes and nodes[conv_node]["depth"] >= 1:
        return conv_node
    for c in item.get("citations") or []:
        nid = doc2node.get(c.get("doc_id"))
        if nid in nodes:
            return nid
    if conv_node and conv_node in nodes:
        return conv_node
    return None


def chapters_by_node(conn, pairs, conv_nodes=None):
    """按知识树归章：[(top_name, [(leaf_name, [pairs...]), ...]), ...]

    conv_nodes: {pairs 下标: 会话 node_id}，可为 None。
    """
    nodes, doc2node = _node_maps(conn)
    groups = {}          # top_id -> {leaf_id -> [items]}
    order = []
    for i, item in enumerate(pairs):
        cn = (conv_nodes or {}).get(i)
        nid = _node_for(item, cn, nodes, doc2node)
        top = _top_of(nid, nodes) if nid else None
        leaf = nid if nid else 0
        if top not in groups:
            groups[top] = {}
            order.append(top)
        groups[top].setdefault(leaf, []).append(item)

    def key(nid):
        n = nodes.get(nid)
        return (n["sort"] if n else 999, n["name"] if n else "")

    out = []
    for top in sorted(order, key=lambda x: key(x) if x else (999, "综合")):
        leaves = groups[top]
        name = nodes[top]["name"] if top in nodes else "综合"
        subs = []
        for leaf in sorted(leaves, key=lambda x: key(x) if x else (999, "综合")):
            sub_name = nodes[leaf]["name"] if leaf in nodes else "其他"
            if sub_name == name:
                sub_name = ""
            subs.append((sub_name, leaves[leaf]))
        out.append((name, subs))
    return out


def _chapter_of(item):
    """按来源文档聚类（同一本书/资料归一章）；没有来源就归"综合"。"""
    for c in item.get("citations") or []:
        doc = (c.get("doc") or "").strip()
        if doc:
            return doc
    return "综合"


def _pack(document: str, title: str) -> bytes:
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
            'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           f'<w:document {_NS}><w:body>{document}{sect}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("docProps/core.xml", _core(title))
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def build_docx(*, title: str, pairs, model: str = "", db_name: str = "",
               include_snippet: bool = False) -> bytes:
    """版式一：问答笔记（逐问记录）。"""
    body = []
    body.append(_p(_r(title, bold=True, size=36, color="1F3864"), align="center", after=80))
    meta = f"导出自 DocLib · {time.strftime('%Y-%m-%d %H:%M')}"
    if model:
        meta += f" · 模型：{model}"
    if db_name:
        meta += f" · 资料库：{db_name}"
    body.append(_p(_r(meta, size=17, color="7F7F7F"), align="center", after=200, border=True))

    if len(pairs) >= 3:
        body.append(_p(_r("本篇问答", bold=True, size=20, color="2E5A88"), before=120, after=40))
        for i, item in enumerate(pairs, 1):
            body.append(_p(_r(f"{i}. {_short(item.get('q') or '', 70)}", size=19),
                           indent=240, after=10))

    n_q = n_c = 0
    for i, item in enumerate(pairs, 1):
        q = _short(item.get("q") or "", 120)
        body.append(_p(_r(f"Q{i}｜{q}", bold=True, size=26, color="2E5A88"),
                       before=220, after=80, border=True))
        n_q += 1
        body.extend(_answer_paragraphs(item.get("a") or ""))
        cites = item.get("citations") or []
        if cites:
            n_c += len(cites)
            body.append(_p(_r("来源", bold=True, size=19, color="7F7F7F"), before=100, after=30))
            for k, c in enumerate(cites, 1):
                doc = c.get("doc") or ""
                heading = c.get("heading") or ""
                label = f"[{k}] {doc} › {heading}" if heading else f"[{k}] {doc}"
                body.append(_p(_r(label, size=17, color="404040"), indent=240, after=20))
                snippet = (c.get("snippet") or "").strip()
                if include_snippet and snippet:
                    body.append(_p(_r("摘录：" + _short(snippet, 150), size=16, color="6B6B6B",
                                      italic=True), indent=420, after=40))
    body.append(_p(_r(f"共 {n_q} 个问答 · {n_c} 条来源　|　由 DocLib 生成，仅供个人复习使用",
                      size=16, color="9A9A9A"), align="center", before=300, after=0, border=True))
    return _pack("".join(body), title)


def build_outline_docx(*, title: str, pairs, model: str = "", db_name: str = "",
                       include_snippet: bool = False, subtitle: str = "",
                       chapters=None) -> bytes:
    """版式二：复习提纲（信息密度优先）。chapters 可传 [(章名, [pairs...])]。"""
    body = []
    # —— 封面 ——
    body.append(_p(_r(title, size=40, color="1F3864", bold=True), style="Title", after=120))
    body.append(_p(_r(subtitle or "要点 · 公式 · 易错", size=22, color="5B7A99"),
                   align="center", after=240))
    meta = (f"课程：信号与系统　　用途：期末复习 · 公式速查　　"
            f"日期：{time.strftime('%Y年%m月')}　　·　资料库：{db_name or 'doclib.db'}")
    body.append(_p(_r(meta, size=17, color="7F7F7F"), align="center", after=60, border=True))
    body.append(_p(_r(f"问答来源：{len(pairs)} 条" + (f"（模型 {model}）" if model else ""),
                      size=15, color="9A9A9A"), align="center", after=0))

    # —— 一、速览要点 ——
    points = extract_points(pairs, max_points=12, per_pair=3)
    if points:
        body.append(_p(_r("一、速览要点", size=28, color="1F3864"), style="Heading1", page_break=True))
        for text, idx in points:
            body.append(_p(_r("•　" + text + f"（见 Q{idx}）", size=20), indent=200, after=30))

    # —— 二、分节提纲 ——
    if chapters is None:
        order, groups = [], {}
        for item in pairs:
            ch = _chapter_of(item)
            if ch not in groups:
                groups[ch] = []
                order.append(ch)
            groups[ch].append(item)
        chapters = [(ch, groups[ch]) for ch in order]

    body.append(_p(_r("二、分节提纲", size=28, color="1F3864"), style="Heading1", before=320))
    q_no = {id(p): i for i, p in enumerate(pairs, 1)}
    for ch, items in chapters:
        # items 可能是 [pairs...] 或 [(子章名, [pairs...]), ...]
        subs = items if (items and isinstance(items[0], tuple)) else [("", items)]
        body.append(_p(_r(ch, size=24, color="2E5A88"), style="Heading2", before=200, after=60))
        for sub_name, sub_items in subs:
            if sub_name:
                body.append(_p(_r(sub_name, bold=True, size=21, color="3A6B99"),
                               indent=80, after=40, keep=True))
            seen_q = set()
            for item in sub_items:
                idx = q_no.get(id(item), 1)
                q = _short(item.get("q") or "", 40)
                if q in seen_q:
                    continue
                seen_q.add(q)
                pts = extract_points([item], max_points=4, per_pair=4)
                if not pts:
                    continue
                body.append(_p(_r("◆　" + q, bold=True, size=20), indent=120, after=30, keep=True))
                for text, _ in pts:
                    body.append(_p(_r("·　" + text + f"（见 Q{idx}）", size=20),
                                   indent=420, after=20))

    # —— 三、公式速查 ——
    formulas = extract_formulas(pairs)
    if formulas:
        body.append(_p(_r("三、公式速查", size=28, color="1F3864"), style="Heading1", before=320))
        rows = [("编号", "表达式", "出处")]
        for k, (text, idx) in enumerate(formulas, 1):
            rows.append((f"F{k}", text, f"Q{idx}"))
        body.append(_table(rows, [1100, 5200, 1300]))
        body.append(_p(_r("记忆：先认形式，再对性质（时移/频移/尺度/卷积）套用途。",
                          size=17, color="6B6B6B", italic=True), before=80, after=60))

    # —— 四、易错清单 ——
    issues = extract_issues(pairs)
    if issues:
        body.append(_p(_r("四、易错清单", size=28, color="1F3864"), style="Heading1", before=320))
        for k, (text, idx) in enumerate(issues, 1):
            body.append(_p(_r(f"{k}. {text}（见 Q{idx}）", size=20), indent=200, after=30))

    # —— 五、自测与提示 ——
    body.append(_p(_r("五、自测与提示", size=28, color="1F3864"), style="Heading1", before=320))
    seen_qq = set()
    for i, item in enumerate(pairs, 1):
        q = _short(item.get("q") or "", 60)
        if q in seen_qq:
            continue
        seen_qq.add(q)
        body.append(_p(_r(f"Q{i}. {q}", size=20), indent=120, after=20, keep=True))
        hint = ""
        for _s in _sentences(item.get("a") or ""):
            _s = _clean_point(re.sub(r"\[\d+\]", "", _s))
            if _s and not _is_negative(_s) and len(_s) >= 8:
                hint = _s
                break
        hint = hint or "（见分节提纲）"
        body.append(_p(_r("提示：" + _short(hint, 70), size=19, color="6B6B6B"),
                       indent=420, after=40))

    # —— 六、来源索引 ——
    seen, index = set(), []
    for item in pairs:
        for c in item.get("citations") or []:
            key = ((c.get("doc") or ""), (c.get("heading") or ""))
            if key in seen:
                continue
            seen.add(key)
            index.append(key)
    if index:
        body.append(_p(_r("六、来源索引", size=28, color="1F3864"), style="Heading1", before=320))
        for doc, heading in index[:30]:
            body.append(_p(_r(f"{doc} › {heading}" if heading else doc, size=17, color="404040"),
                           indent=200, after=20))

    return _pack("".join(body), title)


_SAFE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(s: str, n: int = 40) -> str:
    s = _SAFE.sub("_", (s or "").strip()) or "未命名"
    return s[:n]


def _collect_pairs(conn, conv_id: int, msg_ids=None):
    conv = conn.execute("SELECT * FROM conversations WHERE id=?", (int(conv_id),)).fetchone()
    if conv is None:
        return None, None, "会话不存在"
    msgs = [dict(r) for r in conn.execute(
        "SELECT id, role, content, model FROM messages WHERE conversation_id=? ORDER BY id",
        (int(conv_id),))]
    docs = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM documents")}
    want = None
    if msg_ids:
        try:
            want = {int(x) for x in msg_ids}
        except Exception:
            return conv, None, "选中的问答 id 不合法"
    pairs, last_q, model = [], None, ""
    for m in msgs:
        if m["role"] == "user":
            last_q = m
        elif m["role"] == "assistant" and last_q is not None:
            cits = [{"doc": docs.get(c["doc_id"], ""), "doc_id": c["doc_id"],
                     "heading": c["heading_path"] or "",
                     "snippet": c["snippet"] or ""}
                    for c in conn.execute(
                        "SELECT doc_id, heading_path, snippet FROM message_citations "
                        "WHERE message_id=? ORDER BY id", (m["id"],))]
            pairs.append({"mid": m["id"], "q": (last_q["content"] or "").strip(),
                          "a": (m["content"] or "").strip(), "citations": cits})
            model = m["model"] or model
            last_q = None
    if want is not None:
        pairs = [p for p in pairs if p["mid"] in want]
    if not pairs:
        return conv, None, "没有可导出的问答"
    return conv, {"pairs": pairs, "model": model}, None


def export_conversation(conn, conv_id: int, out_dir=None, msg_ids=None,
                        include_snippet: bool = False, mode: str = "qa",
                        group: str = "node") -> dict:
    """导出单个会话（mode: qa / outline）。"""
    conv, data, err = _collect_pairs(conn, conv_id, msg_ids)
    if err:
        return {"ok": False, "error": err}
    title = conv["title"] or "问答笔记"
    pairs, model = data["pairs"], data["model"]
    if mode == "outline":
        chapters = None
        if group == "node":
            cn = {i: conv["node_id"] for i in range(len(pairs))}
            chapters = chapters_by_node(conn, pairs, cn) or None
        blob = build_outline_docx(title=title, pairs=pairs, model=model,
                                  db_name=config.DB_PATH.name,
                                  include_snippet=bool(include_snippet),
                                  chapters=chapters)
        suffix = "复习提纲"
    else:
        blob = build_docx(title=title, pairs=pairs, model=model, db_name=config.DB_PATH.name,
                          include_snippet=bool(include_snippet))
        suffix = "问答笔记"
    out_dir = out_dir or EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    name = f"{safe_name(title)}-{suffix}_{time.strftime('%Y%m%d-%H%M%S')}.docx"
    path = os.path.join(out_dir, name)
    with open(path, "wb") as f:
        f.write(blob)
    return {"ok": True, "path": path, "name": name, "size": len(blob),
            "questions": len(pairs),
            "citations": sum(len(p["citations"]) for p in pairs),
            "snippet": bool(include_snippet), "mode": mode, "title": title}


def export_batch(conn, conv_ids, out_dir=None, include_snippet: bool = False,
                 mode: str = "outline", title: str = "合并复习提纲",
                 group: str = "node") -> dict:
    """多会话合并成一本：每个会话作为一章。"""
    if not conv_ids:
        return {"ok": False, "error": "没有选择会话"}
    conv_chapters, all_pairs, models = [], [], set()
    conv_nodes = {}
    for cid in conv_ids:
        conv, data, err = _collect_pairs(conn, cid)
        if err:
            continue
        conv_chapters.append((conv["title"] or f"会话 {cid}", data["pairs"]))
        if conv["node_id"]:
            for _ in data["pairs"]:
                conv_nodes[len(all_pairs) + data["pairs"].index(_)] = conv["node_id"]
        all_pairs += data["pairs"]
        if data["model"]:
            models.add(data["model"])
    if not all_pairs:
        return {"ok": False, "error": "选中的会话都没有可导出的问答"}
    model = "、".join(sorted(models)) if models else ""
    if mode == "outline":
        if group == "node":
            chapters = chapters_by_node(conn, all_pairs, conv_nodes) or conv_chapters
            unit = f"{len(chapters)} 个知识组"
        else:
            chapters = conv_chapters
            unit = f"{len(chapters)} 个会话"
        subtitle = f"要点 · 公式 · 易错　|　{unit} · {len(all_pairs)} 个问答"
        blob = build_outline_docx(title=title, pairs=all_pairs, model=model,
                                  db_name=config.DB_PATH.name, subtitle=subtitle,
                                  include_snippet=bool(include_snippet), chapters=chapters)
        suffix = "复习提纲"
    else:
        blob = build_docx(title=title, pairs=all_pairs, model=model,
                          db_name=config.DB_PATH.name, include_snippet=bool(include_snippet))
        suffix = "问答笔记"
    out_dir = out_dir or EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    name = f"{safe_name(title)}-{suffix}_{time.strftime('%Y%m%d-%H%M%S')}.docx"
    path = os.path.join(out_dir, name)
    with open(path, "wb") as f:
        f.write(blob)
    return {"ok": True, "path": path, "name": name, "size": len(blob),
            "questions": len(all_pairs),
            "chapters": len(conv_chapters if group != "node" else chapters),
            "citations": sum(len(p["citations"]) for p in all_pairs),
            "snippet": bool(include_snippet), "mode": mode, "title": title}
