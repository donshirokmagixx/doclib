# -*- coding: utf-8 -*-
"""解析质量评分（A2）。

目的不是「精确评估」，而是**让明显坏掉的解析结果浮出水面**：
- OCR 出乱码（大量 0xFFFD 替换字符）
- PDF 乱序/乱码、表格线被当成正文（长串重复符号）
- 全是控制字符/零宽字符
- 几乎提取不到可读字符

分数 0~1：
  >= 0.85  正常
  0.60~0.85 略有噪声
  < 0.60   识别质量低（界面标红，检索降权）
"""
import re

# 替换字符、BOM、零宽、控制字符
_JUNK_CHARS = set("\ufffd\ufeff\u200b\u200c\u200d\x00")
_JUNK_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# 连续 6 个以上相同的非空白字符，通常是表格线 / 乱码 / 占位
_GARBAGE_RUN_RE = re.compile(r"([^\s])\1{5,}")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LETTER_RE = re.compile(r"[A-Za-z0-9]")
_PUNCT = set("，。！？；：、（）《》【】“”‘’—…·,.!?;:()[]{}<>\"'-_/\\|@#$%^&*+=~` \t\n\r")


def _meaningful_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = len(_CJK_RE.findall(text))
    letters = len(_LETTER_RE.findall(text))
    punct = sum(1 for ch in text if ch in _PUNCT)
    return (cjk + letters + punct) / len(text)


def score_text(text: str) -> tuple:
    """返回 (score, note)；note 用来在界面上解释原因。"""
    n = len(text or "")
    if n == 0:
        return 0.0, "空文本"

    junk = sum(1 for ch in text if ch in _JUNK_CHARS) + len(_JUNK_RE.findall(text))
    junk_ratio = junk / n
    garbage = sum(len(m.group(0)) for m in _GARBAGE_RUN_RE.finditer(text))
    garbage_ratio = garbage / n
    meaningful = _meaningful_ratio(text)
    wordish = (len(_CJK_RE.findall(text)) + len(_LETTER_RE.findall(text))) / n

    score = 1.0
    score -= min(0.60, junk_ratio * 40)          # 乱码字符：很严重
    score -= min(0.30, garbage_ratio * 3)        # 长串重复符号
    if meaningful < 1.0:
        score -= min(0.35, (1.0 - meaningful) * 0.5)
    if n > 120 and meaningful < 0.35:
        score -= 0.20                            # 可读字符太少
    if n > 80 and wordish < 0.12:
        score -= 0.25                            # 几乎不含文字：表格线/符号汤

    score = max(0.0, min(1.0, score))

    notes = []
    if junk_ratio > 0.005:
        notes.append(f"含 {junk_ratio*100:.1f}% 无法识别字符")
    if garbage_ratio > 0.10:
        notes.append("含大量重复符号（可能是表格线或乱码）")
    if n > 80 and wordish < 0.12:
        notes.append("几乎不含文字（可能是表格线或乱码）")
    if meaningful < 0.5:
        notes.append("可读字符比例偏低")
    if not notes and score < 0.85:
        notes.append("文本噪声偏多")
    return round(score, 3), "；".join(notes)


def score_chunks(chunks) -> tuple:
    """按字数加权平均，返回 (score, note)。"""
    total = 0
    acc = 0.0
    notes = []
    for c in chunks:
        text = c.get("text") or ""
        s, note = score_text(text)
        w = max(len(text), 1)
        acc += s * w
        total += w
        if note and note not in notes:
            notes.append(note)
    if total == 0:
        return 0.0, "空文本"
    score = round(acc / total, 3)
    note = "；".join(notes[:3])
    return score, note


def is_low(quality, threshold: float = 0.6) -> bool:
    try:
        return float(quality) < threshold
    except (TypeError, ValueError):
        return False
