# -*- coding: utf-8 -*-
"""REV-101 验收：科目分区（一级节点=分区）的列表、范围过滤、检索/问答隔离、/api/rev/* 入口。

用法：
    python tests\test_partitions.py
（脚本内部建临时库，不碰正本）
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

TMP = tempfile.mkdtemp(prefix="doclib_rev101_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, seed, tree, search   # noqa: E402
from doclib.ai import rag                   # noqa: E402

NOW = 1700000000000


def add_doc(conn, node_id, title, text):
    cur = conn.execute(
        "INSERT INTO documents(title, file_path, path_key, file_type, parse_status,"
        " char_count, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (title, f"D:/tmp/{title}.md", f"d:/tmp/{title}.md", "md", 2, len(text), NOW, NOW))
    did = cur.lastrowid
    conn.execute("INSERT INTO doc_chunks(doc_id, ord, heading_path, text, char_len)"
                 " VALUES(?,?,?,?,?)", (did, 0, "第 1 章", text, len(text)))
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


def fake_chat(*_a, **_kw):
    return {"ok": True, "content": "测试回答 [1]。", "model": "fake-model",
            "usage": {}, "cost_yuan": 0, "latency_ms": 1, "trace_id": "t"}


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {detail}"))
    assert cond, name


def main():
    conn = db.open_db()
    try:
        seed.seed(conn)
        a = tree.create_node(conn, "科目A", None)
        a1 = tree.create_node(conn, "A-第一章", a)
        b = tree.create_node(conn, "科目B", None)
        doc_a = add_doc(conn, a, "A总论", "共享关键词 甲的甲内容")
        doc_a1 = add_doc(conn, a1, "A第一章", "共享关键词 甲的细内容")
        doc_b = add_doc(conn, b, "B总论", "共享关键词 乙的内容")
        add_provider(conn)
        conn.commit()

        print("1) 分区列表")
        parts = tree.list_partitions(conn)
        names = [p["name"] for p in parts]
        check("包含 A/B 两个分区", "科目A" in names and "科目B" in names, names)
        check("排除系统节点「未分类」", "未分类" not in names, names)
        pa = next(p for p in parts if p["name"] == "科目A")
        check("分区文档数含下级", pa["doc_count"] == 2, pa)

        print("2) 节点归属")
        check("子节点归属 A", tree.partition_of_node(conn, a1) == a)
        check("B 归属 B", tree.partition_of_node(conn, b) == b)
        unc = conn.execute("SELECT id FROM nodes WHERE is_system=1 LIMIT 1").fetchone()
        check("系统节点无分区", tree.partition_of_node(conn, unc[0]) is None)

        print("3) 范围过滤")
        check("分区A + all = A 全部文档",
              tree.node_doc_ids(conn, None, "all", a) == {doc_a, doc_a1})
        check("分区A + self(A-第一章) 只含本章",
              tree.node_doc_ids(conn, a1, "self", a) == {doc_a1})
        check("跨分区被拒绝（B 节点 + 分区A）",
              tree.node_doc_ids(conn, b, "subtree", a) == set())

        print("4) 检索按分区隔离")
        rd_a = search.search(conn, "共享关键词", None, "all", partition_id=a)
        ids_a = {r["doc_id"] for r in rd_a["results"]}
        check("A 分区检索只返回 A 文档", ids_a and ids_a <= {doc_a, doc_a1}, ids_a)
        docs_a = search.docs_in_scope(conn, None, "all", partition_id=a)
        check("A 分区文档列表只含 A", {d["doc_id"] for d in docs_a["results"]} == {doc_a, doc_a1})
        chunks_a = rag._chunk_candidates(conn, "共享关键词", None, "all", 5, partition_id=a)
        check("A 分区块检索只含 A", chunks_a and {c["doc_id"] for c in chunks_a} <= {doc_a, doc_a1})

        print("5) 问答按分区 + 会话记住分区")
        rag.gateway.chat = fake_chat
        r1 = rag.ask(conn, "共享关键词", a, "all", partition_id=a)
        check("分区A提问成功", r1.get("ok"), r1)
        check("来源属于 A", {s["doc_id"] for s in r1["sources"]} <= {doc_a, doc_a1})
        cid = r1["conversation_id"]
        r2 = rag.ask(conn, "共享关键词", None, "all", conversation_id=cid)
        check("同会话无分区参数时回读 A",
              r2.get("ok") and r2.get("partition_id") == a, r2)
        r3 = rag.ask(conn, "共享关键词", None, "all", conversation_id=cid, partition_id=b)
        check("显式换分区成功", r3.get("ok"), r3)
        check("来源切换到 B", all(s["doc_id"] == doc_b for s in r3["sources"]),
              [s["doc_id"] for s in r3["sources"]])
        check("会话节点写到 B 分区根",
              conn.execute("SELECT node_id FROM conversations WHERE id=?", (cid,)).fetchone()[0] == b)
        check("换分区有 op_log", conn.execute(
            "SELECT COUNT(*) FROM op_log WHERE op='partition_update' AND entity_id=?",
            (cid,)).fetchone()[0] >= 1)

        print("6) /api/rev/* 入口")
        from doclib.web import server as web
        p = web.api_dispatch("GET", "/api/rev/partitions", {}, {})
        check("/api/rev/partitions 返回列表", p.get("ok") and any(
            x["name"] == "科目A" for x in p["items"]), p)
        q = web.api_dispatch("GET", "/api/rev/search",
                             {"q": ["共享关键词"], "scope": ["all"], "partition": [str(a)]}, {})
        check("/api/rev/search 只返回 A", {r["doc_id"] for r in q["results"]} <= {doc_a, doc_a1},
              [r["doc_id"] for r in q["results"]])
        t = web.api_dispatch("GET", "/api/rev/tree", {"partition": [str(a)]}, {})
        check("/api/rev/tree 只给一个分区", len(t["tree"]) == 1 and t["tree"][0]["id"] == a, len(t["tree"]))
        # 7) 分区导入：落到分区外会被收回分区根
        import tempfile, pathlib
        f = pathlib.Path(tempfile.mkdtemp()) / "分区导入.md"
        f.write_text("# 分区导入\n\n共享关键词 分区导入内容\n", encoding="utf-8")
        imp = web.api_dispatch("POST", "/api/rev/import", {}, {"path": str(f), "partition": a})
        check("分区导入成功", imp.get("ok") and imp.get("imported") == 1, imp)
        new_id = (imp.get("items") or [{}])[0].get("doc_id")
        nodes = [r[0] for r in conn.execute(
            "SELECT node_id FROM node_documents WHERE document_id=?", (new_id,)).fetchall()]
        check("导入文档落在分区 A 内",
              nodes and all(tree.partition_of_node(conn, n) == a for n in nodes), nodes)

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
