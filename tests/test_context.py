# -*- coding: utf-8 -*-
"""v2.0 AI 上下文：document / selection / node / note / partition + 引用来源。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
TMP = tempfile.mkdtemp(prefix="doclib_context_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, seed, tree, notebook  # noqa: E402
from doclib.ai import rag  # noqa: E402
from doclib.db import now_ms  # noqa: E402

NOW = 1700000000000
FAIL = []


def check(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {extra}"))
    if not cond:
        FAIL.append(name)


def add_doc(conn, node_id, title, text, name):
    p = Path(TMP) / name
    p.write_text(text, encoding="utf-8")
    cur = conn.execute(
        "INSERT INTO documents(title,file_path,path_key,file_type,parse_status,char_count,"
        "created_at,updated_at) VALUES(?,?,?, 'md',2,?,?,?)",
        (title, str(p), str(p).lower(), len(text), NOW, NOW))
    did = cur.lastrowid
    for i, part in enumerate([text, text + "（续）"]):
        conn.execute(
            "INSERT INTO doc_chunks(doc_id,ord,heading_path,text,char_len) VALUES(?,?,?,?,?)",
            (did, i, "第 1 章 > 1.1 定义" if i == 0 else "第 1 章 > 1.2 性质", part, len(part)))
    conn.execute("INSERT INTO node_documents(node_id,document_id,weight,note,created_at) VALUES(?,?,?,?,?)",
                 (node_id, did, 1.0, "", NOW))
    return did


def add_provider(conn):
    conn.execute(
        "INSERT INTO ai_providers(name,kind,base_url,model,key_ref,role,enabled,extra_json,"
        "created_at,updated_at,is_default,free,price_in,price_out,note) "
        "VALUES('fake','openai_compatible','http://x','fake','','chat',1,'{}',?,?,1,1,0,0,'t')",
        (NOW, NOW))


def fake_chat(*_a, **_kw):
    return {"ok": True, "content": "依据片段 [1]。", "model": "fake-model",
            "usage": {}, "cost_yuan": 0, "latency_ms": 1, "trace_id": "t"}


def main():
    conn = db.open_db()
    try:
        seed.seed(conn)
        parts = tree.list_partitions(conn)
        part = parts[0]["id"]
        a = tree.create_node(conn, "卷积", part)
        b = tree.create_node(conn, "傅里叶", part)
        doc_a = add_doc(conn, a, "卷积资料", "卷积定理告诉我们时域卷积等于频域相乘。卷积是线性时不变系统的核心。", "a.md")
        doc_b = add_doc(conn, b, "傅里叶资料", "DFT 是离散傅里叶变换，FFT 是快速算法。傅里叶变换用于频谱分析，也与卷积定理相关。", "b.md")
        note = notebook.save_note(conn, title="我的傅里叶笔记", body_md="# 笔记\n\nFFT 是计算 DFT 的快速算法。\n",
                                  node_id=b, partition_id=part)
        add_provider(conn)
        rag.gateway.chat = fake_chat

        print("1) document 上下文只检索该文档")
        r = rag.ask(conn, "卷积 频域", context={"kind": "document", "doc_id": doc_a, "partition_id": part})
        check("ok", r.get("ok"), r)
        check("只来自 doc_a", all(s["doc_id"] == doc_a for s in r["sources"]), r.get("sources"))
        check("context=document", (r.get("context") or {}).get("kind") == "document")
        check("conversation context 落库", bool(r.get("conversation_id")))
        row = conn.execute("SELECT context_json FROM conversations WHERE id=?", (r["conversation_id"],)).fetchone()
        check("conversation.context_json 有 document", "document" in (row[0] or ""))
        check("citation source_kind=document", all(s.get("source_kind") == "document" for s in r["sources"]))
        cid = r["conversation_id"]

        print("2) selection 上下文：选文作为首条来源")
        r2 = rag.ask(conn, "这段是什么意思？", conversation_id=cid,
                     context={"kind": "selection", "doc_id": doc_b, "partition_id": part,
                              "quote": "FFT 是快速算法", "chunk_id": None, "heading_path": "第 1 章"})
        check("ok", r2.get("ok"), r2)
        check("首条为 selection", r2["sources"] and r2["sources"][0]["source_kind"] == "selection", r2.get("sources"))
        check("selection 引用带 quote/长度", any(s.get("source_kind") == "selection" for s in r2["sources"]))

        print("3) node 上下文：只在该节点子树")
        r3 = rag.ask(conn, "卷积 频域", context={"kind": "node", "node_id": a, "partition_id": part})
        check("ok", r3.get("ok"), r3)
        check("不含 doc_b", all(s["doc_id"] != doc_b for s in r3["sources"]), r3.get("sources"))
        check("context=node", (r3.get("context") or {}).get("kind") == "node")

        print("4) note 上下文：来源是笔记")
        r4 = rag.ask(conn, "FFT 快速算法", context={"kind": "note", "note_id": note["id"], "partition_id": part})
        check("ok", r4.get("ok"), r4)
        check("note source_kind", r4["sources"] and all(s.get("source_kind") == "note" for s in r4["sources"]), r4.get("sources"))
        check("note_id 正确", r4["sources"] and r4["sources"][0].get("note_id") == note["id"])

        print("5) 空范围/非法上下文")
        bad = rag.ask(conn, "x", context={"kind": "document", "doc_id": 99999})
        check("不存在文档被拒", bad.get("ok") is False, bad)
        bad2 = rag.ask(conn, "x", context={"kind": "node", "node_id": 99999})
        check("不存在节点被拒", bad2.get("ok") is False, bad2)

        print("6) all 上下文：全库范围")
        rall = rag.ask(conn, "卷积", context={"kind": "all"})
        check("all ok", rall.get("ok"), rall)
        check("all context=all", (rall.get("context") or {}).get("kind") == "all")
        check("all partition 为空", (rall.get("context") or {}).get("partition_id") is None)
        rall2 = rag.ask(conn, "傅里叶", context={"kind": "all"})
        check("all 能检索到另一篇", rall2.get("ok") and rall2["sources"]
              and any(s["doc_id"] == doc_b for s in rall2["sources"]), rall2.get("sources"))

        print("7) 旧调用不受 context 影响")
        old = rag.ask(conn, "卷积", node_id=a, scope="subtree", partition_id=part)
        check("旧调用 ok", old.get("ok"), old)
        check("旧调用 context 为空", old.get("context") is None)

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
