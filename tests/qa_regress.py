# -*- coding: utf-8 -*-
"""问答检索回归测试：验证「关键内容块是否进前 N」。

只跑检索（块级），不调用任何大模型 → 0 token、秒级。
用法（在 DocLib 目录）：
    python tests\\qa_regress.py
    python tests\\qa_regress.py --top 8 --verbose
"""
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from doclib import db                      # noqa: E402
from doclib.ai import rag                  # noqa: E402

YAML_PATH = APP / "tests" / "eval" / "qa_regression.yaml"


def load_cases(path: Path):
    """极简 YAML 读取（只支持本文件用到的结构，避免额外依赖）。"""
    cases, cur = [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        s = re.sub(r"\s+#.*$", "", line.strip())   # 去掉行内注释
        if not s or s.startswith("#"):
            continue
        if s.startswith("- id:"):
            if cur:
                cases.append(cur)
            cur = {"id": s.split(":", 1)[1].strip(), "expect_any": [], "top": 8}
        elif cur is None:
            continue
        elif s.startswith("q:"):
            cur["q"] = s.split(":", 1)[1].strip()
        elif s.startswith("top:"):
            cur["top"] = int(s.split(":", 1)[1].strip())
        elif s.startswith("known_fail:"):
            cur["known_fail"] = s.split(":", 1)[1].strip().lower() == "true"
        elif s.startswith("expect_any:"):
            body = s.split(":", 1)[1].strip()
            body = body.strip("[]")
            cur["expect_any"] = [x.strip().strip('"').strip("'")
                                 for x in body.split(",") if x.strip()]
        elif s.startswith("- ") and cur is not None and s[2:].startswith('"'):
            cur["expect_any"].append(s[2:].strip().strip('"').strip("'"))
    if cur:
        cases.append(cur)
    return [c for c in cases if c.get("q")]


def main():
    argv = sys.argv[1:]
    verbose = "--verbose" in argv or "-v" in argv
    top_override = None
    if "--top" in argv:
        top_override = int(argv[argv.index("--top") + 1])

    cases = load_cases(YAML_PATH)
    conn = db.open_db()
    rag._chunk_candidates(conn, "预热", None, "all", 3)   # 预热嵌入模型

    ok = fail = xfail = xpass = 0
    print(f"问答检索回归：{len(cases)} 条\n")
    print(f"{'ID':<6}{'Top?':<7}{'结果':<9}问题")
    print("-" * 72)
    for c in cases:
        top = top_override or c.get("top", 8)
        rows = rag._chunk_candidates(conn, c["q"], None, "all", top)
        hay = " ".join((r["heading_path"] or "") + " " + (r["text"] or "") for r in rows)
        hits = [e for e in c["expect_any"] if e and e in hay]
        passed = bool(hits)
        known_fail = c.get("known_fail", False)

        if passed and known_fail:
            status, xpass = "XPASS", xpass + 1
        elif passed:
            status, ok = "PASS", ok + 1
        elif known_fail:
            status, xfail = "xfail", xfail + 1
        else:
            status, fail = "FAIL", fail + 1
        print(f"{c['id']:<6}{('前'+str(top)):<7}{status:<9}{c['q'][:40]}")
        if verbose or status == "FAIL":
            for i, r in enumerate(rows[:top], 1):
                print(f"        [{i}] {(r['heading_path'] or r['title'])[:52]}")
    conn.close()

    total = len(cases)
    print("-" * 72)
    print(f"通过 {ok}/{total} · 已知未达标 {xfail} · 失败 {fail}"
          + (f" · 意外转好 {xpass}（可去掉 known_fail）" if xpass else ""))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
