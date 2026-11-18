# -*- coding: utf-8 -*-
"""REV-104 验收：资料 → 可编辑导图（模型结构化 + 规则回退），节点带 sources，重开仍在。"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

TMP = tempfile.mkdtemp(prefix="doclib_rev104_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, seed, tree, mindmap      # noqa: E402
from doclib import mindmap_gen                  # noqa: E402
from doclib.ai import gateway                   # noqa: E402

NOW = 1700000000000


def add_doc(conn, node_id, title, heads):
    cur = conn.execute(
        "INSERT INTO documents(title, file_path, path_key, file_type, parse_status,"
        " char_count, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (title, f"D:/tmp/{title}.md", f"d:/tmp/{title}.md", "md", 2, 100, NOW, NOW))
    did = cur.lastrowid
    for i, h in enumerate(heads):
        conn.execute("INSERT INTO doc_chunks(doc_id, ord, heading_path, text, char_len)"
                     " VALUES(?,?,?,?,?)", (did, i, h, f"{h} 的正文内容", 20))
    conn.execute("INSERT INTO node_documents(node_id, document_id, weight, note, created_at)"
                 " VALUES(?,?,?,?,?)", (node_id, did, 1.0, "", NOW))
    return did


def add_provider(conn):
    conn.execute(
        "INSERT INTO ai_providers(name, kind, base_url, model, key_ref, role, enabled,"
        " extra_json, created_at, updated_at, is_default, free, price_in, price_out, note)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("fake", "openai_compatible", "http://127.0.0.1:1/v1", "fake-model", "",
         "chat", 1, "{}", NOW, NOW, 1, 0, 0, 0, "test"))


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {detail}"))
    assert cond, name


def main():
    conn = db.open_db()
    try:
        seed.seed(conn)
        a = tree.create_node(conn, "科目A", None)
        d1 = add_doc(conn, a, "A资料1", ["第 1 章", "1.1 抽样"])
        d2 = add_doc(conn, a, "A资料2", ["第 2 章", "2.1 混叠"])
        add_provider(conn)
        conn.commit()

        print("1) 模型不可用 → 规则版")
        gateway.chat = lambda *a, **k: {"ok": False, "error": "no model"}
        r1 = mindmap_gen.generate(conn, node_id=a, scope="subtree")
        check("规则版成功", r1.get("ok"), r1)
        check("method=rule", r1.get("method") == "rule", r1.get("method"))
        check("有回退提示", "规则版" in (r1.get("warning") or ""), r1.get("warning"))
        m1 = mindmap.load(r1["name"])
        check("导图已保存且 version=2", m1.get("version") == 2, m1.get("version"))
        check("items 有节点", len(m1["items"]) >= 4, len(m1["items"]))
        check("generated_from 记了来源文档",
              set(m1["generated_from"]["doc_ids"]) == {d1, d2}, m1["generated_from"])
        check("边均有效（无 None）",
              all(e.get("from") and e.get("to") for e in m1["edges"]), m1["edges"][:2])

        print("2) 模型可用 → 结构化 JSON + sources")
        payload = {
            "title": "科目A",
            "children": [
                {"title": "A资料1", "sources": [{"doc_id": d1, "heading_path": "第 1 章"}],
                 "children": [{"title": "抽样", "sources": [{"doc_id": d1, "heading_path": "1.1 抽样"}],
                                "children": []}]},
                {"title": "A资料2", "sources": [{"doc_id": d2, "heading_path": "第 2 章"}],
                 "children": []},
            ],
        }
        gateway.chat = lambda *a, **k: {"ok": True, "content": json.dumps(payload, ensure_ascii=False),
                                         "model": "fake-model", "usage": {}, "cost_yuan": 0,
                                         "latency_ms": 1, "trace_id": "t"}
        r2 = mindmap_gen.generate(conn, node_id=a, scope="subtree")
        check("模型版成功", r2.get("ok"), r2)
        check("method=llm", r2.get("method") == "llm", r2.get("method"))
        m2 = mindmap.load(r2["name"])
        check("节点带 sources", any(it.get("sources") for it in m2["items"]),
              [it.get("sources") for it in m2["items"]][:3])
        check("重开仍在（文件可再次读取）", m2.get("title") == r2["name"], m2.get("title"))
        check("无回退提示", not r2.get("warning"), r2.get("warning"))

        print("3) 范围内无资料 → 友好报错")
        empty = tree.create_node(conn, "空分区", None)
        r3 = mindmap_gen.generate(conn, node_id=empty, scope="subtree")
        check("空范围报错", not r3.get("ok") and "资料" in (r3.get("error") or ""), r3)

        print("\n全部通过 ✅（临时库：%s）" % TMP)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
