# -*- coding: utf-8 -*-
"""REV-103 验收：会话与检索范围隔离（后端成立，不依赖前端隐藏）。

覆盖：
  1. 同名标题不再合并会话（旧缺陷）
  2. 追问只带本会话历史；会话范围随会话保存
  3. 会话内显式换节点 → 写回 + op_log 留痕
  4. 检索严格限制在范围内（A 分区搜不到 B 分区文档）
  5. 缺范围/非法范围/不存在会话 → 友好拒绝
  6. /api/ask 同样做范围校验

用法（必须在临时库上跑，避免污染正本）：
    set DOCLIB_DATA=D:\tmp\doclib-rev103
    python tests\test_scope_isolation.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

TMP = tempfile.mkdtemp(prefix="doclib_rev103_")
os.environ["DOCLIB_DATA"] = TMP           # 必须在 import config 之前设置

from doclib import db, tree                 # noqa: E402
from doclib.ai import rag                   # noqa: E402

NOW = 1700000000000


def add_doc(conn, node_id, title, text):
    cur = conn.execute(
        "INSERT INTO documents(title, file_path, path_key, file_type, parse_status,"
        " char_count, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (title, f"D:/tmp/{title}.md", f"d:/tmp/{title}.md", "md", 2, len(text), NOW, NOW))
    doc_id = cur.lastrowid
    conn.execute(
        "INSERT INTO doc_chunks(doc_id, ord, heading_path, text, char_len)"
        " VALUES(?,?,?,?,?)", (doc_id, 0, "第 1 章", text, len(text)))
    conn.execute(
        "INSERT INTO node_documents(node_id, document_id, weight, note, created_at)"
        " VALUES(?,?,?,?,?)", (node_id, doc_id, 1.0, "", NOW))
    return doc_id


def add_provider(conn):
    conn.execute(
        "INSERT INTO ai_providers(name, kind, base_url, model, key_ref, role, enabled,"
        " extra_json, created_at, updated_at, is_default, free, price_in, price_out, note)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("fake", "openai_compatible", "http://127.0.0.1:1/v1", "fake-model", "",
         "chat", 1, "{}", NOW, NOW, 1, 0, 0, 0, "test"))


def fake_chat(*_a, **_kw):
    return {"ok": True, "content": "这是测试回答，引用 [1]。", "model": "fake-model",
            "usage": {"tokens_in": 1, "tokens_out": 1}, "cost_yuan": 0,
            "latency_ms": 1, "trace_id": "test"}


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {detail}"))
    assert cond, name


def main():
    conn = db.open_db()
    try:
        a = tree.create_node(conn, "分区A", None, "测试分区 A")
        b = tree.create_node(conn, "分区B", None, "测试分区 B")
        doc_a = add_doc(conn, a, "A资料", "共享关键词 甲分区专有内容")
        doc_b = add_doc(conn, b, "B资料", "共享关键词 乙分区专有内容")
        add_provider(conn)
        conn.commit()

        print("1) 同名标题不再合并会话")
        c1 = rag._get_or_create_conversation(conn, "同一个问题开头", a)
        c2 = rag._get_or_create_conversation(conn, "同一个问题开头", b)
        check("两个同名问题得到两个会话", c1 != c2, f"{c1} vs {c2}")
        check("按 id 取回原会话", rag._get_or_create_conversation(
            conn, "任意标题", a, conversation_id=c1) == c1)
        try:
            rag._get_or_create_conversation(conn, "x", a, conversation_id=999999)
            check("不存在的会话应报错", False)
        except ValueError:
            check("不存在的会话报错", True)

        print("2) 检索严格限制在范围内")
        ids_a = tree.node_doc_ids(conn, a, "subtree")
        ids_b = tree.node_doc_ids(conn, b, "subtree")
        check("A 范围只含 A 文档", ids_a == {doc_a}, ids_a)
        check("B 范围只含 B 文档", ids_b == {doc_b}, ids_b)
        rows_a = rag._chunk_candidates(conn, "共享关键词", a, "subtree", 5)
        rows_b = rag._chunk_candidates(conn, "共享关键词", b, "subtree", 5)
        check("A 检索不含 B 文档", rows_a and all(r["doc_id"] == doc_a for r in rows_a),
              [r["doc_id"] for r in rows_a])
        check("B 检索不含 A 文档", rows_b and all(r["doc_id"] == doc_b for r in rows_b),
              [r["doc_id"] for r in rows_b])

        print("3) ask：范围校验 / 会话范围写回 / 留痕")
        rag.gateway.chat = fake_chat
        r1 = rag.ask(conn, "共享关键词", a, "subtree")
        check("首次提问成功", r1.get("ok"), r1)
        conv_id = r1["conversation_id"]
        check("返回生效范围", r1.get("node_id") == a and r1.get("scope") == "subtree", r1)
        check("来源属于 A", all(s["doc_id"] == doc_a for s in r1["sources"]),
              [s["doc_id"] for s in r1["sources"]])

        r2 = rag.ask(conn, "共享关键词", b, "subtree", conversation_id=conv_id)
        check("同会话换节点后提问成功", r2.get("ok"), r2)
        check("会话节点已写回 B",
              conn.execute("SELECT node_id FROM conversations WHERE id=?",
                           (conv_id,)).fetchone()[0] == b)
        check("来源切换到 B", all(s["doc_id"] == doc_b for s in r2["sources"]),
              [s["doc_id"] for s in r2["sources"]])
        logged = conn.execute(
            "SELECT COUNT(*) FROM op_log WHERE op='scope_update' AND entity_id=?",
            (conv_id,)).fetchone()[0]
        check("换范围有 op_log 留痕", logged >= 1, logged)

        r3 = rag.ask(conn, "共享关键词", None, "subtree")
        check("缺范围被拒绝", not r3.get("ok") and "范围" in (r3.get("error") or ""), r3)
        r4 = rag.ask(conn, "共享关键词", a, "bogus")
        check("非法范围被拒绝", not r4.get("ok") and "范围" in (r4.get("error") or ""), r4)
        r5 = rag.ask(conn, "共享关键词", a, "subtree", conversation_id=999999)
        check("不存在会话被拒绝", not r5.get("ok") and "会话" in (r5.get("error") or ""), r5)

        print("4) /api/ask 的范围校验（HTTP 层入口）")
        from doclib.web import server as web
        bad1 = web.api_dispatch("POST", "/api/ask", {}, {"question": "q", "scope": "bogus"})
        check("scope=bogus 被拒", not bad1.get("ok"), bad1)
        bad2 = web.api_dispatch("POST", "/api/ask", {}, {"question": "q", "scope": "self"})
        check("scope=self 缺 node 被拒", not bad2.get("ok"), bad2)
        bad3 = web.api_dispatch("POST", "/api/ask", {}, {"question": "q"})
        check("缺省 scope 且无 node 被拒", not bad3.get("ok"), bad3)

        print("\n全部通过 ✅（临时库：%s）" % TMP)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
