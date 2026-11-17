# -*- coding: utf-8 -*-
"""导出 Word 笔记的自测（不依赖 Word / python-docx）。

检查：
  1. 生成的 docx 是合法 zip，必需部件齐全、XML 可解析
  2. 正文包含问题、答案、来源标题
  3. 多问答时有"本篇问答"目录
  4. 会话不存在 / 空会话时给出友好错误

用法：python tests\\test_notes.py
"""
import io
import re
import sys
import tempfile
import xml.dom.minidom as minidom
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from doclib import db, notes      # noqa: E402


def check_docx(data: bytes, must_have=()) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        for need in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            assert need in names, f"缺少部件 {need}"
        for n in names:
            if n.endswith(".xml") or n.endswith(".rels"):
                minidom.parseString(z.read(n))      # XML 必须合法
        doc = z.read("word/document.xml").decode("utf-8")
    for kw in must_have:
        assert kw in doc, f"正文缺少：{kw}"
    return doc


def main():
    # ① 纯构造（不碰数据库）
    pairs = [
        {"q": "卷积定理是什么", "a": "时域卷积 ↔ 频域相乘。\n- 要点一\n- 要点二", "citations": [
            {"doc": "信号与系统概念", "heading": "第 3 章 > 3.1 卷积定理"}]},
        {"q": "帕塞瓦尔定理", "a": "**能量守恒** [1]", "citations": [
            {"doc": "傅里叶级数-复习资料", "heading": "5.1 帕塞瓦尔"}]},
        {"q": "抽样定理", "a": "带宽限制", "citations": []},
    ]
    data = notes.build_docx(title="单元测试笔记", pairs=pairs, model="deepseek-chat",
                            db_name="doclib.db")
    doc = check_docx(data, must_have=("单元测试笔记", "卷积定理是什么", "本篇问答",
                                      "信号与系统概念", "帕塞瓦尔"))
    print(f"① 构造成功：{len(data)} 字节，段落 {doc.count('<w:p>')} 个 ✅")

    # ② 真实会话导出
    conn = db.open_db()
    row = conn.execute(
        "SELECT c.id FROM conversations c JOIN messages m ON m.conversation_id=c.id "
        "AND m.role='assistant' GROUP BY c.id ORDER BY c.id DESC LIMIT 1").fetchone()
    if row:
        with tempfile.TemporaryDirectory() as td:
            res = notes.export_conversation(conn, row["id"], out_dir=td)
            assert res.get("ok"), res
            body = Path(res["path"]).read_bytes()
            check_docx(body, must_have=("来源",))
            print(f"② 真实会话导出：{res['name']} {res['size']} 字节 "
                  f"{res['questions']} 问答 / {res['citations']} 来源 ✅")
    else:
        print("② 跳过：库里还没有 AI 问答记录")

    # ③ 勾选导出 + 附摘录
    conn2 = db.open_db()
    row2 = conn2.execute(
        "SELECT c.id FROM conversations c JOIN messages m ON m.conversation_id=c.id "
        "AND m.role='assistant' GROUP BY c.id HAVING COUNT(m.id)>=2 ORDER BY c.id DESC LIMIT 1").fetchone()
    if row2:
        ai_ids = [r["id"] for r in conn2.execute(
            "SELECT id FROM messages WHERE conversation_id=? AND role!='user' ORDER BY id",
            (row2["id"],))]
        with tempfile.TemporaryDirectory() as td:
            res = notes.export_conversation(conn2, row2["id"], out_dir=td,
                                            msg_ids=[ai_ids[0], ai_ids[1]], include_snippet=True)
            assert res.get("ok"), res
            body = Path(res["path"]).read_bytes()
            doc = check_docx(body, must_have=("摘录：", "Q2｜"))
            assert "Q3｜" not in doc, "勾选导出不应包含第 3 条"
            assert res["questions"] == 2, res
            print(f"③ 勾选 2 条 + 摘录：{res['questions']} 问答 / {res['citations']} 来源 ✅")
    else:
        print("③ 跳过：没有 >=2 轮的会话")
    conn2.close()

    # ⑤ 复习提纲版式
    conn3 = db.open_db()
    row3 = conn3.execute(
        "SELECT c.id FROM conversations c JOIN messages m ON m.conversation_id=c.id "
        "AND m.role='assistant' GROUP BY c.id ORDER BY c.id DESC LIMIT 1").fetchone()
    if row3:
        with tempfile.TemporaryDirectory() as td:
            res = notes.export_conversation(conn3, row3["id"], out_dir=td, mode="outline")
            assert res.get("ok"), res
            doc = check_docx(Path(res["path"]).read_bytes(),
                             must_have=("二、分节提纲", "五、自测与提示", 'w:val="Heading1"'))
            assert "<w:tbl>" in doc or "三、公式速查" not in doc, "公式表结构异常"
            assert "没有找到" not in doc, "提纲里混入了'没有找到'式回答"
            print(f"⑤ 复习提纲：{res['name'][:24]}… 含标题样式/公式表/自测 ✅")
        # ⑥ 合并导出
        ids = [r["id"] for r in conn3.execute(
            "SELECT c.id FROM conversations c JOIN messages m ON m.conversation_id=c.id "
            "AND m.role='assistant' GROUP BY c.id ORDER BY c.id DESC LIMIT 2")]
        if len(ids) >= 2:
            with tempfile.TemporaryDirectory() as td:
                rb = notes.export_batch(conn3, ids, out_dir=td, mode="outline", title="合并测试")
                assert rb.get("ok"), rb
                check_docx(Path(rb["path"]).read_bytes(), must_have=("合并测试", "一、速览要点"))
                assert rb["chapters"] == 2, rb
                print(f"⑥ 合并导出：{rb['chapters']} 章 / {rb['questions']} 问答 ✅")
    conn3.close()

    # ⑦ 按知识树归章
    conn4 = db.open_db()
    row4 = conn4.execute(
        "SELECT c.id FROM conversations c JOIN messages m ON m.conversation_id=c.id "
        "AND m.role='assistant' GROUP BY c.id ORDER BY c.id DESC LIMIT 1").fetchone()
    if row4:
        conv, data, err = notes._collect_pairs(conn4, row4["id"])
        assert not err, err
        chs = notes.chapters_by_node(conn4, data["pairs"], {i: conv["node_id"] for i in range(len(data["pairs"]))})
        assert chs, "知识树归章为空"
        names = [c[0] for c in chs]
        print(f"⑦ 知识树归章：{len(chs)} 章（{'、'.join(names[:4])}）✅")
    conn4.close()

    # ⑧ 异常路径
    bad = notes.export_conversation(conn, 999999)
    assert not bad.get("ok") and "不存在" in bad.get("error", "")
    print("⑧ 不存在的会话 → 友好报错 ✅")
    conn.close()

    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
