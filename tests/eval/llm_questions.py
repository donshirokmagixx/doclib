# -*- coding: utf-8 -*-
"""让 DeepSeek 把章节标题改写成"学生会自然提出的问句"，再跑召回评测。

用途：标题原词提问 = 送分题；改写后的问句才接近真实使用。
用法：python tests\\eval\\llm_questions.py --n 120
输出：tests/eval/llm_questions.jsonl  + 控制台召回报告
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))

from doclib import db                     # noqa: E402
from doclib.ai import gateway, rag        # noqa: E402

OUT = APP / "tests" / "eval" / "llm_questions.jsonl"
_NUM = re.compile(r"^[\d０-９]+([.．、]\s*[\d０-９]+)*[\s、.．]*")
_SPACE = re.compile(r"[\s\u3000]+")
_SKIP = ("思考题", "参考文献", "目录", "本章导读", "小结", "练习", "附录",
         "前言", "导读", "索引", "致谢", "测试文档")
# 非学科文档（项目文档/方案）不参与学科问答评测
_SKIP_DOC = ("优化方案与实施指南",)


def norm_heading(h: str) -> str:
    h = _SPACE.sub(" ", (h or "").strip())
    last = h.split(">")[-1].strip()
    return _NUM.sub("", last).strip()


def collect(conn, n):
    rows = [dict(r) for r in conn.execute(
        "SELECT c.heading_path, c.text, d.title FROM doc_chunks c "
        "JOIN documents d ON d.id=c.doc_id WHERE d.deleted_at IS NULL")]
    sections, seen = [], set()
    for r in rows:
        h = norm_heading(r["heading_path"] or r["title"])
        if len(h) < 4 or h in seen:
            continue
        if any(w in h for w in _SKIP):
            continue
        if any(w in (r["title"] or "") for w in _SKIP_DOC):
            continue
        seen.add(h)
        sections.append({"heading": h, "path": r["heading_path"], "doc": r["title"]})
    random.Random(20261113).shuffle(sections)
    return sections[:n]


PROMPT = """你是信号与系统课程的本科生，正在用资料库复习。
把下面每个章节标题，改写成你会自然问出口的一句中文提问（可以不用术语、可以口语化，但必须仍然指向这一节的内容）。
要求：
1. 严格保持行数一致：输入 20 行 → 输出 20 行；
2. 每行只写一个问题，不要编号、不要解释、不要空行；
3. 不要出现"这一节""该章节"等指代，直接问内容。
输入标题：
%s"""


def gen(conn, sections, batch=20):
    out = []
    prov = gateway.load_provider(conn)
    for i in range(0, len(sections), batch):
        chunk = sections[i:i + batch]
        titles = "\n".join(s["heading"] for s in chunk)
        r = gateway.chat(conn, [
            {"role": "system", "content": "只输出问题列表，不解释。"},
            {"role": "user", "content": PROMPT % titles},
        ], provider=prov, temperature=0.7, max_tokens=900, task_type="eval_gen")
        text = (r.get("answer") or r.get("content") or "") if r.get("ok") else ""
        lines = [x.strip(" -•\t") for x in text.splitlines() if x.strip()]
        lines = [re.sub(r"^\d+[.、)]\s*", "", x) for x in lines]
        if len(lines) != len(chunk):
            print(f"  [warn] 第 {i//batch+1} 批行数不齐（{len(lines)}/{len(chunk)}），按顺序尽量对齐")
        for s, q in zip(chunk, lines):
            if len(q) >= 6:
                out.append({"q": q, "heading": s["heading"], "path": s["path"], "doc": s["doc"]})
        print(f"  批次 {i//batch+1}: 生成 {len(lines)} 条")
    return out


def evaluate(conn, items, top=8):
    rag._chunk_candidates(conn, "预热", None, "all", 3)
    ok, fails = 0, []
    for it in items:
        got = rag._chunk_candidates(conn, it["q"], None, "all", top)
        names = [norm_heading(r["heading_path"] or r["title"]) for r in got]
        docs = [r["title"] for r in got]
        want = it["heading"]
        hit = False
        for n, d in zip(names, docs):
            if not n:
                continue
            if want == n or (want in n) or (n in want):
                if d == it["doc"] or (want in n and n in want):
                    hit = True
                    break
        if hit:
            ok += 1
        else:
            fails.append((it, names[:5]))
    return ok, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--reuse", action="store_true", help="复用已生成的 jsonl")
    args = ap.parse_args()

    conn = db.open_db()
    if args.reuse and OUT.exists():
        items = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
        print(f"复用 {len(items)} 条已有问句")
    else:
        secs = collect(conn, args.n)
        print(f"已选 {len(secs)} 个章节，开始让 DeepSeek 改写问句…")
        items = gen(conn, secs)
        OUT.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items),
                       encoding="utf-8")
        print(f"已保存 {len(items)} 条 → {OUT}")

    ok, fails = evaluate(conn, items, args.top)
    total = len(items)
    print(f"\n真实问句召回@{args.top}：{ok}/{total} = {ok/max(total,1)*100:.1f}%")
    for it, names in fails[:25]:
        print(f"\n  问：{it['q']}")
        print(f"  期望：{it['heading']}   ← 《{it['doc'][:20]}》")
        print(f"  实际：{'；'.join(n[:18] for n in names)}")
    conn.close()


if __name__ == "__main__":
    main()
