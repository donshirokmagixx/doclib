# -*- coding: utf-8 -*-
"""自动出题 + 自检召回（不调用任何大模型，零成本）。

思路：
  1. 从库里的块（chunk）反推"这一节讲了什么"，生成贴近学生的提问（模板化）
  2. 拿这些问题跑检索，看"答案所在的那一节"有没有进前 N —— 这就是召回@N
  3. 输出按文档/章节汇总的失败清单，用来定位检索短板

用法：
  python tests\\eval\\autoeval.py            # 全部文档
  python tests\\eval\\autoeval.py --top 8    # 指定 N
  python tests\\eval\\autoeval.py --doc 5    # 只测某篇
  python tests\\eval\\autoeval.py --md out.md
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))

from doclib import db                     # noqa: E402
from doclib.ai import rag                 # noqa: E402

# 标题里去掉编号/空格： "3.3 傅里叶变换的性质" -> "傅里叶变换的性质"
_NUM = re.compile(r"^[\d０-９]+([.．、]\s*[\d０-９]+)*[\s、.．]*")
_SPACE = re.compile(r"[\s\u3000]+")


def norm_heading(h: str) -> str:
    h = _SPACE.sub(" ", (h or "").strip())
    last = h.split(">")[-1].strip()
    last = _NUM.sub("", last).strip()
    return last


def key_terms(text: str, k: int = 6):
    """抽几个像术语的片段（中文 2-8 字、含英文缩写）。"""
    cand = re.findall(r"[\u4e00-\u9fa5]{2,8}(?=[，。；：、\s])|"
                      r"[A-Za-z][A-Za-z0-9\-]{1,12}", text or "")
    stop = {"因此", "所以", "可以", "如果", "这里", "下面", "例如", "注意", "说明",
            "结论", "所示", "如图", "如表", "其中", "一个", "我们", "就是"}
    out = []
    for c in cand:
        if c in stop or any(c in o for o in out):
            continue
        out.append(c)
        if len(out) >= k:
            break
    return out


_SKIP_HEAD = ("思考题", "参考文献", "目录", "本章导读", "小结", "练习", "附录",
              "前言", "导读", "索引", "致谢")


def build_questions(rows):
    """每个章节 → 2~3 个"像学生会问的"问题；只用章节标题，避免拼出病句。"""
    qs, seen = [], set()
    for r in rows:
        raw = r["heading_path"] or r["title"]
        h = norm_heading(raw)
        if not h or len(h) < 4 or h in seen:
            continue
        if any(w in h for w in _SKIP_HEAD) or h.isdigit():
            continue
        seen.add(h)
        qs.append((f"{h}是什么", raw))
        qs.append((f"{h}有哪些内容", raw))
        qs.append((f"能不能讲一下{h}", raw))
        if any(w in h for w in ("性质", "定理", "关系", "对照", "公式")):
            qs.append((f"{h}怎么理解", raw))
    return qs


def hit(rows, expect_heading: str) -> bool:
    want = norm_heading(expect_heading)
    for r in rows:
        if norm_heading(r["heading_path"] or r["title"]) == want:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--doc", type=int, default=0)
    ap.add_argument("--md", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = db.open_db()
    sql = ("SELECT c.id, c.doc_id, c.heading_path, c.text, d.title FROM doc_chunks c "
           "JOIN documents d ON d.id=c.doc_id WHERE d.deleted_at IS NULL")
    params = ()
    if args.doc:
        sql += " AND c.doc_id=?"
        params = (args.doc,)
    sql += " ORDER BY c.doc_id, c.ord"
    rows = [dict(r) for r in conn.execute(sql, params)]

    qs = build_questions(rows)
    if args.limit:
        qs = qs[: args.limit]

    rag._chunk_candidates(conn, "预热", None, "all", 3)   # 预热嵌入模型

    per_doc = defaultdict(lambda: [0, 0])
    fails = []
    for q, expect in qs:
        got = rag._chunk_candidates(conn, q, None, "all", args.top)
        doc = next((r["title"] for r in rows if r["heading_path"] == expect), "?")
        ok = hit(got, expect)
        per_doc[doc][1] += 1
        if ok:
            per_doc[doc][0] += 1
        else:
            fails.append((doc, norm_heading(expect), q,
                          [norm_heading(r["heading_path"] or r["title"]) for r in got[:5]]))
    conn.close()

    total_ok = sum(v[0] for v in per_doc.values())
    total = sum(v[1] for v in per_doc.values())
    print(f"自动评测：{len(qs)} 个问题 · 召回@{args.top} = {total_ok}/{total} "
          f"({(total_ok / max(total, 1)) * 100:.1f}%)\n")
    print(f"{'文档':<34}{'命中':<10}")
    print("-" * 60)
    for doc, (ok, n) in sorted(per_doc.items(), key=lambda x: x[1][0] / max(x[1][1], 1)):
        print(f"{doc[:32]:<34}{ok}/{n:<8}{ok / max(n, 1) * 100:.0f}%")

    # 失败模式：按"期望章节"统计，找出最常漏的
    miss = Counter(x[1] for x in fails)
    print("\n最常漏掉的章节（Top 15）：")
    for name, cnt in miss.most_common(15):
        print(f"  {cnt:>2}  {name}")

    if args.md:
        lines = [f"# 自动评测报告（召回@{args.top}）", "",
                 f"- 问题数：{len(qs)}", f"- 命中：{total_ok}/{total} "
                 f"({(total_ok / max(total, 1)) * 100:.1f}%)", "",
                 "## 按文档", "", "| 文档 | 命中 |", "|---|---|"]
        for doc, (ok, n) in sorted(per_doc.items()):
            lines.append(f"| {doc} | {ok}/{n} |")
        lines += ["", "## 失败清单（前 120 条）", ""]
        for doc, exp, q, got in fails[:120]:
            lines.append(f"- **{q}**")
            lines.append(f"  - 期望：{exp}")
            lines.append(f"  - 实际前5：{'；'.join(got)}")
        Path(args.md).write_text("\n".join(lines), encoding="utf-8")
        print(f"\n报告已写入：{args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
