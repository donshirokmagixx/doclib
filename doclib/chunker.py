# -*- coding: utf-8 -*-
"""按标题层级把 Word 块合并成「章节块」。

每个块带 heading_path（例如「第 1 章 卷积是什么 > 1.4 三个可以直接手算的例子」），
这是检索结果里能告诉用户「在哪一节」的基础。
"""
from typing import List

from . import config


# 公式/表格里只有符号，补中文别名，让「正弦/余弦/冲激」等中文提问也能命中
_SYMBOL_CN = [("sin", "正弦"), ("cos", "余弦"), ("δ", "冲激"), ("u(t)", "阶跃"),
              ("Sa", "抽样函数"), ("rect", "矩形脉冲"), ("e^", "指数"),
              ("sgn", "符号函数")]


def _alias_hint(text: str) -> str:
    found = []
    for sym, cn in _SYMBOL_CN:
        if sym in text and cn not in text:
            found.append(cn)
    if len(found) >= 2:
        return "（本段涉及：" + "、".join(found) + "）"
    return ""


def chunk_blocks(blocks: List[dict], doc_title: str = "") -> List[dict]:
    chunks: List[dict] = []
    stack: List[tuple] = []          # [(level, text), ...]
    buf: List[str] = []
    buf_table_only = True

    def heading_path() -> str:
        return " > ".join(t for _, t in stack)

    def flush():
        nonlocal buf, buf_table_only
        text = "\n\n".join(x for x in buf if x.strip()).strip()
        if not text:
            buf = []
            buf_table_only = True
            return
        hint = _alias_hint(text) if (buf_table_only or " | " in text) else ""
        chunks.append({
            "heading_path": heading_path() or doc_title,
            "text": (text + hint) if hint else text,
            "char_len": len(text),
            "is_table": 1 if (buf_table_only and text) else 0,
        })
        buf = []
        buf_table_only = True

    for b in blocks:
        level = b.get("level")
        text = (b.get("text") or "").strip()
        if not text:
            continue
        if level is not None:
            flush()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            continue

        current_len = sum(len(x) for x in buf)
        if current_len and current_len + len(text) > config.CHUNK_MAX:
            flush()
        buf.append(text)
        if b.get("kind") == "table":
            buf_table_only = buf_table_only and True
        else:
            buf_table_only = False

    flush()

    # 合并过短的尾块（同一标题路径下）
    if len(chunks) >= 2:
        a, b = chunks[-2], chunks[-1]
        if (b["char_len"] < config.CHUNK_MIN_MERGE
                and a["heading_path"] == b["heading_path"]
                and a["char_len"] + b["char_len"] <= config.CHUNK_MAX * 1.4):
            a["text"] = a["text"] + "\n\n" + b["text"]
            a["char_len"] = len(a["text"])
            a["is_table"] = 0
            chunks.pop()

    for i, c in enumerate(chunks):
        c["ord"] = i
    return chunks
