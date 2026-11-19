# -*- coding: utf-8 -*-
"""工作区持久化：校验/夹取/损坏回退/重置。"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
TMP = tempfile.mkdtemp(prefix="doclib_ws_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import workspace  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {extra}"))
    if not cond:
        FAIL.append(name)


def main():
    print("1) 默认与保存")
    w = workspace.default_workspace()
    check("默认 theme=dark", w["theme"] == "dark")
    w["layout"]["left_width"] = 9999
    w["layout"]["right_width"] = 10
    w["theme"] = "light"
    r = workspace.save(w)
    check("保存 ok", r.get("ok"), r)
    loaded = workspace.load()
    check("宽度夹取", loaded["layout"]["left_width"] == 420 and loaded["layout"]["right_width"] == 300,
          loaded["layout"])
    check("主题保留", loaded["theme"] == "light")

    print("2) 非法结构收敛")
    bad = {"version": 1, "theme": "purple", "panes": [
        {"id": "p1", "active_tab": "nope", "tabs": [
            {"id": "a", "kind": "evil", "params": {"x": "y"}},
            {"id": "b", "kind": "doc", "title": "x", "params": {"docId": 1, "evil": "x" * 1000}},
        ]}
    ]}
    r = workspace.save(bad)
    check("保存 ok", r.get("ok"), r)
    loaded = workspace.load()
    check("非法 theme 回退 dark", loaded["theme"] == "dark")
    tabs = loaded["panes"][0]["tabs"]
    check("非法 tab kind 被移除", all(t["kind"] != "evil" for t in tabs), tabs)
    check("doc params 只留白名单", "docId" in tabs[0]["params"] and "evil" not in tabs[0]["params"], tabs[0])

    print("3) 损坏文件回退 + 保留副本")
    p = Path(TMP) / "workspace.json"
    p.write_text("{not json", encoding="utf-8")
    loaded = workspace.load()
    check("损坏回退默认", loaded["panes"][0]["tabs"][0]["kind"] == "graph")
    check("损坏副本存在", bool(list(Path(TMP).glob("workspace.corrupt-*.json"))))

    print("4) 重置")
    r = workspace.reset()
    check("重置 ok", r.get("ok"), r)
    check("重置后为 graph tab", workspace.load()["panes"][0]["tabs"][0]["kind"] == "graph")

    print("\n全部通过 ✅（临时库：%s）" % TMP)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
