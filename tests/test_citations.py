# -*- coding: utf-8 -*-
"""REV-102 + REV-P1 验收：引用必须真实、资料不足显式、会话带分区、提示词版本化。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

TMP = tempfile.mkdtemp(prefix="doclib_rev102_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, seed, tree                 # noqa: E402
from doclib.ai import rag, prompts                # noqa: E402

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


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {detail}"))
    assert cond, name


def main():
    conn = db.open_db()
    try:
        seed.seed(conn)
        a = tree.create_node(conn, "科目A", None)
        add_doc(conn, a, "A资料", "共享关键词 甲的甲内容")
        add_provider(conn)
        conn.commit()

        print("1) 有引用 → 正常保存来源")
        rag.gateway.chat = lambda *a, **k: {
            "ok": True, "content": "这是结论 [1]。", "model": "fake-model",
            "usage": {}, "cost_yuan": 0, "latency_ms": 1, "trace_id": "t"}
        r1 = rag.ask(conn, "共享关键词", a, "subtree")
        check("回答成功", r1.get("ok"), r1)
        check("来源 1 条", len(r1.get("sources") or []) == 1, r1.get("sources"))
        check("citation_status=cited", r1.get("citation_status") == "cited", r1.get("citation_status"))
        check("insufficient=False", r1.get("insufficient") is False, r1.get("insufficient"))
        n_cite = conn.execute("SELECT COUNT(*) FROM message_citations WHERE message_id=?",
                              (r1["message_id"],)).fetchone()[0]
        check("引用落库 1 条", n_cite == 1, n_cite)

        print("2) 无引用 → 判为资料不足，不伪造来源")
        conn.execute("DELETE FROM ai_cache"); conn.commit()   # 避免命中第 1 例的缓存
        rag.gateway.chat = lambda *a, **k: {
            "ok": True, "content": "资料中没有找到相关内容。", "model": "fake-model",
            "usage": {}, "cost_yuan": 0, "latency_ms": 1, "trace_id": "t2"}
        r2 = rag.ask(conn, "共享关键词", a, "subtree")
        check("回答成功（不算失败）", r2.get("ok"), r2)
        check("来源为空", (r2.get("sources") or []) == [], r2.get("sources"))
        check("citation_status=none", r2.get("citation_status") == "none", r2.get("citation_status"))
        check("insufficient=True", r2.get("insufficient") is True, r2.get("insufficient"))
        check("有资料不足提示", "资料不足" in (r2.get("notice") or ""), r2.get("notice"))
        n_cite2 = conn.execute("SELECT COUNT(*) FROM message_citations WHERE message_id=?",
                               (r2["message_id"],)).fetchone()[0]
        check("无引用不落库", n_cite2 == 0, n_cite2)

        print("3) 会话详情恢复分区")
        from doclib.web import server as web
        d = web.api_dispatch("GET", f"/api/conv/detail/{r1['conversation_id']}", {}, {})
        check("会话详情 ok", d.get("ok"), d)
        check("分区 = 科目A", d["conversation"].get("partition_id") == a,
              d["conversation"].get("partition_id"))

        print("4) 提示词版本化")
        h = web.api_dispatch("GET", "/api/health", {}, {})
        check("health 带 prompt_version", h.get("prompt_version") == prompts.PROMPT_VERSION,
              h.get("prompt_version"))
        check("提示词文件已加载", len(prompts.load_qa_prompt()) > 200)
        check("digest 形如 p<version>:xxxx",
              prompts.prompt_digest().startswith(f"p{prompts.PROMPT_VERSION}:"),
              prompts.prompt_digest())

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
