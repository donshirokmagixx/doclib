# -*- coding: utf-8 -*-
"""阅读器数据层验收：分页、TOC、around、软删除、原文件 MIME、原文编码、HTTP Range。

用法：
    .venv\\Scripts\\python.exe tests\\test_reader.py
（内部使用临时 DOCLIB_DATA 与 tempfile 资料，不碰 dist/data 与真实资料。）
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

TMP = tempfile.mkdtemp(prefix="doclib_reader_db_")
FILES = tempfile.mkdtemp(prefix="doclib_reader_files_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, reader, seed, tree  # noqa: E402

NOW = 1700000000000

UTF8_TEXT = "# 第一章\n\n你好，DocLib。\n"
BOM_TEXT = "# BOM 文档\n\n正文。\n"
GB_TEXT = "中文编码测试：卷积、傅里叶变换与抽样。"


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + ("" if cond else "  <- %r" % (detail,)))
    assert cond, name


def expect_value_error(name, fn):
    try:
        fn()
    except ValueError:
        check(name, True)
    except Exception as exc:  # noqa: BLE001
        check(name, False, "抛了 %s: %s" % (type(exc).__name__, exc))
    else:
        check(name, False, "没有抛 ValueError")


def write_file(name, data: bytes) -> Path:
    path = Path(FILES) / name
    path.write_bytes(data)
    return path


def add_doc(conn, title, path, file_type="md", mount=None, deleted=False):
    path = Path(path)
    size = path.stat().st_size if path.is_file() else 0
    cur = conn.execute(
        "INSERT INTO documents(title,file_path,path_key,file_type,file_size,"
        "parse_status,char_count,created_at,updated_at,deleted_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (title, str(path), str(path).lower(), file_type, size, 2, 0,
         NOW, NOW, NOW if deleted else None),
    )
    did = cur.lastrowid
    if mount is not None:
        conn.execute(
            "INSERT INTO node_documents(node_id,document_id,created_at) VALUES(?,?,?)",
            (mount, did, NOW),
        )
    return did


def add_chunk(conn, doc_id, ord_, heading, text, is_table=0,
              page=None, start_off=None, end_off=None):
    cur = conn.execute(
        "INSERT INTO doc_chunks(doc_id,ord,heading_path,text,char_len,is_table,"
        "page,start_off,end_off) VALUES(?,?,?,?,?,?,?,?,?)",
        (doc_id, ord_, heading, text, len(text), is_table,
         page, start_off, end_off),
    )
    return cur.lastrowid


def ords(payload):
    return [c["ord"] for c in payload["chunks"]]


def main():
    conn = db.open_db()
    try:
        seed.seed(conn)
        part = tree.create_node(conn, "阅读测试分区", None)
        sub = tree.create_node(conn, "阅读测试章节", part)

        utf8_file = write_file("主文档.md", UTF8_TEXT.encode("utf-8"))
        empty_file = write_file("无块文档.txt", b"")
        other_file = write_file("另一文档.txt", "另一个文档".encode("utf-8"))
        del_file = write_file("已删除.md", b"deleted")
        pdf_file = write_file("二进制.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        exe_file = write_file("不支持.exe", b"MZ\x90\x00")
        gb_file = write_file("GB18030.txt", GB_TEXT.encode("gb18030"))
        bom_file = write_file("BOM.md", "\ufeff".encode("utf-8") + BOM_TEXT.encode("utf-8"))
        md_type_file = write_file("markdown类型.markdown", b"# Markdown\n")
        safe_file = write_file("安全文件.md", b"# safe\n")

        main_id = add_doc(conn, "阅读器主文档", utf8_file, "md", mount=sub)
        other_id = add_doc(conn, "另一文档", other_file, "txt", mount=sub)
        no_chunk_id = add_doc(conn, "无块文档", empty_file, "txt", mount=sub)
        deleted_id = add_doc(conn, "已删除文档", del_file, "md", mount=sub)
        conn.execute("UPDATE documents SET deleted_at=? WHERE id=?", (NOW, deleted_id))
        missing_id = add_doc(conn, "缺失文件文档", Path(FILES) / "missing.md", "md", mount=sub)
        pdf_id = add_doc(conn, "二进制 PDF", pdf_file, "pdf", mount=sub)
        exe_id = add_doc(conn, "不支持类型", exe_file, "exe", mount=sub)
        dir_id = add_doc(conn, "目录路径文档", Path(FILES), "pdf", mount=sub)
        gb_id = add_doc(conn, "GB18030 文本", gb_file, "txt", mount=sub)
        bom_id = add_doc(conn, "BOM 文本", bom_file, "md", mount=sub)
        md_type_id = add_doc(conn, "markdown 类型", md_type_file, "markdown", mount=sub)
        safe_id = add_doc(conn, "<script>alert(1)</script>\r\n标题", safe_file, "md", mount=sub)

        headings = [
            "第 1 章 绪论",
            "第 1 章 绪论 > 1.1 背景",
            "第 1 章 绪论 > 1.1 背景",
            "第 1 章 绪论 > 1.2 方法",
            "第 2 章 结论",
        ]
        texts = ["绪论正文", "背景一段", "背景二段", "方法正文", "结论正文"]
        main_chunks = []
        for i, (heading, text) in enumerate(zip(headings, texts)):
            main_chunks.append(add_chunk(
                conn, main_id, i, heading, text,
                is_table=1 if i == 3 else 0,
                page=7 if i == 1 else None,
                start_off=100 if i == 1 else None,
                end_off=120 if i == 1 else None,
            ))
        other_chunk = add_chunk(conn, other_id, 0, "另一文档", "别的块")
        add_chunk(conn, gb_id, 0, "编码", "GB 块")

        print("1) get_doc：文档头 + 挂载节点 + 分区")
        doc = reader.get_doc(conn, main_id)
        check("get_doc 返回文档", doc and doc["id"] == main_id, doc)
        check("标题", doc["title"] == "阅读器主文档", doc)
        check("file_type/file_size/parse_status",
              (doc["file_type"], doc["file_size"], doc["parse_status"])
              == ("md", utf8_file.stat().st_size, 2), doc)
        check("挂载节点", doc["nodes"] == [{"id": sub, "name": "阅读测试章节"}], doc)
        check("分区为一级节点", doc["partition_id"] == part, doc)
        check("文件路径来自 DB", doc["file_path"] == str(utf8_file), doc)
        check("不存在返回 None", reader.get_doc(conn, 999999) is None)
        check("非法 id 返回 None", reader.get_doc(conn, "abc") is None)
        check("软删除返回 None", reader.get_doc(conn, deleted_id) is None)

        print("2) reader_payload：文档头/分页/TOC/around/has_more")
        payload = reader.reader_payload(conn, main_id)
        check("ok", payload.get("ok") is True, payload)
        check("doc 指定字段齐全",
              set(payload["doc"]) == {"id", "title", "file_path", "file_type",
                                      "file_size", "parse_status", "nodes",
                                      "partition_id"}, set(payload["doc"]))
        check("doc 节点与分区", payload["doc"]["nodes"] == [{"id": sub, "name": "阅读测试章节"}]
              and payload["doc"]["partition_id"] == part, payload["doc"])
        check("total=5", payload["total"] == 5, payload["total"])
        check("默认从 ord 0 返回全部", ords(payload) == [0, 1, 2, 3, 4], ords(payload))
        check("块字段齐全",
              set(payload["chunks"][0]) == {"id", "ord", "heading_path", "text",
                                             "char_len", "is_table", "page",
                                             "start_off", "end_off"},
              set(payload["chunks"][0]))
        check("块内容与 id", payload["chunks"][0]["id"] == main_chunks[0]
              and payload["chunks"][0]["text"] == "绪论正文", payload["chunks"][0])
        check("page/start_off/end_off 透传",
              (payload["chunks"][1]["page"], payload["chunks"][1]["start_off"],
               payload["chunks"][1]["end_off"]) == (7, 100, 120),
              payload["chunks"][1])
        check("is_table 透传", payload["chunks"][3]["is_table"] == 1,
              payload["chunks"][3])
        check("默认 has_more=False", payload["has_more"] is False, payload["has_more"])
        toc = payload["toc"]
        check("TOC 层级/标题连续去重",
              [(t["level"], t["title"]) for t in toc] == [
                  (1, "第 1 章 绪论"),
                  (2, "1.1 背景"),
                  (2, "1.2 方法"),
                  (1, "第 2 章 结论"),
              ], toc)
        check("TOC 指向块 id 与 ord",
              [(t["chunk_id"], t["ord"]) for t in toc] == [
                  (main_chunks[0], 0), (main_chunks[1], 1),
                  (main_chunks[3], 3), (main_chunks[4], 4),
              ], toc)

        p2 = reader.reader_payload(conn, main_id, limit=2)
        check("limit=2 只返回 2 块", ords(p2) == [0, 1], ords(p2))
        check("limit=2 has_more=True", p2["has_more"] is True, p2["has_more"])
        p0 = reader.reader_payload(conn, main_id, limit=0)
        check("limit=0 收紧为 1", len(p0["chunks"]) == 1 and p0["has_more"] is True,
              ords(p0))
        pbig = reader.reader_payload(conn, main_id, limit=9999)
        check("limit 上限 500 不截断 5 块", ords(pbig) == [0, 1, 2, 3, 4]
              and pbig["has_more"] is False, ords(pbig))

        pa = reader.reader_payload(conn, main_id, around=main_chunks[2], limit=3)
        check("around 居中窗口 ord 1..3", ords(pa) == [1, 2, 3], ords(pa))
        check("around 中段 has_more=True", pa["has_more"] is True, pa["has_more"])
        pb = reader.reader_payload(conn, main_id, around=main_chunks[4], limit=3)
        check("around 末尾前移窗口 ord 2..4", ords(pb) == [2, 3, 4], ords(pb))
        check("around 末尾 has_more=False", pb["has_more"] is False, pb["has_more"])
        pc = reader.reader_payload(conn, main_id, around=main_chunks[2], limit=2)
        check("around limit=2", ords(pc) == [1, 2], ords(pc))
        pbad = reader.reader_payload(conn, main_id, around=999999, limit=2)
        check("无效 around 退回 ord 0", ords(pbad) == [0, 1], ords(pbad))
        pother = reader.reader_payload(conn, main_id, around=other_chunk, limit=2)
        check("跨文档 around 退回 ord 0", ords(pother) == [0, 1], ords(pother))

        pn = reader.reader_payload(conn, no_chunk_id)
        check("无 chunk 文档 ok", pn["ok"] is True, pn)
        check("无 chunk total=0/chunks=[]/toc=[]/has_more=False",
              pn["total"] == 0 and pn["chunks"] == [] and pn["toc"] == []
              and pn["has_more"] is False, pn)
        check("无 chunk 仍有文档头", pn["doc"]["id"] == no_chunk_id
              and pn["doc"]["file_type"] == "txt", pn["doc"])
        check("文档不存在 payload ok=False",
              reader.reader_payload(conn, 999999).get("ok") is False)
        check("软删除 payload ok=False",
              reader.reader_payload(conn, deleted_id).get("ok") is False)
        try:
            json.dumps(payload, ensure_ascii=False)
            serializable = True
        except (TypeError, ValueError):
            serializable = False
        check("payload 可 JSON 序列化", serializable)

        print("3) resolve_file：MIME 白名单/缺失文件/路径安全")
        info = reader.resolve_file(conn, main_id)
        check("返回三元组", isinstance(info, tuple) and len(info) == 3, info)
        check("路径与 MIME", info[0] == str(utf8_file)
              and info[1] == "text/markdown", info)
        check("download_name 用真实文件名", info[2] == "主文档.md", info)
        expected_mime = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".ppt": "application/vnd.ms-powerpoint",
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".txt": "text/plain",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        for ext, mime in expected_mime.items():
            f = write_file("mime" + ext, b"x")
            did = add_doc(conn, "MIME " + ext, f, ext.lstrip("."), mount=sub)
            got = reader.resolve_file(conn, did)
            check("MIME %s" % ext, got is not None and got[1] == mime, got)
        check("缺失文件 None", reader.resolve_file(conn, missing_id) is None)
        check("软删除 None", reader.resolve_file(conn, deleted_id) is None)
        check("目录路径 None", reader.resolve_file(conn, dir_id) is None)
        check("白名单外后缀 None", reader.resolve_file(conn, exe_id) is None)
        check("不存在 None", reader.resolve_file(conn, 999999) is None)
        check("非法 id None", reader.resolve_file(conn, "../../etc/passwd") is None)
        safe = reader.resolve_file(conn, safe_id)
        check("标题不进入 download_name", safe[2] == "安全文件.md", safe)
        check("download_name 无控制字符",
              not any(ch in safe[2] for ch in "\r\n\x00"), safe)
        check("中文空格文件名", reader.resolve_file(
            conn, add_doc(conn, "空格文件名", write_file("中文 资料 (1).md", b"x"),
                          "md", mount=sub))[2] == "中文 资料 (1).md")

        print("4) raw_text：UTF-8/GB18030/二进制拒绝")
        rt = reader.raw_text(conn, main_id)
        check("utf-8 ok", rt.get("ok") is True, rt)
        check("utf-8 内容", rt.get("text") == UTF8_TEXT, rt.get("text"))
        check("utf-8 encoding", rt.get("encoding") == "utf-8", rt.get("encoding"))
        check("mtime 为 stat 秒", rt.get("mtime") == int(utf8_file.stat().st_mtime), rt)
        rgb = reader.raw_text(conn, gb_id)
        check("GB18030 ok", rgb.get("ok") is True, rgb)
        check("GB18030 内容", rgb.get("text") == GB_TEXT, rgb.get("text"))
        check("GB18030 encoding", rgb.get("encoding") == "gb18030", rgb.get("encoding"))
        rbom = reader.raw_text(conn, bom_id)
        check("BOM 被去掉", rbom.get("text") == BOM_TEXT, rbom.get("text"))
        check("BOM 报 utf-8", rbom.get("encoding") == "utf-8", rbom.get("encoding"))
        rmd = reader.raw_text(conn, md_type_id)
        check("file_type=markdown 可读", rmd.get("ok") is True, rmd)
        rpdf = reader.raw_text(conn, pdf_id)
        check("PDF 拒绝", rpdf.get("ok") is False and rpdf.get("error"), rpdf)
        check("缺失文件拒绝", reader.raw_text(conn, missing_id).get("ok") is False)
        check("软删除拒绝", reader.raw_text(conn, deleted_id).get("ok") is False)
        check("不存在拒绝", reader.raw_text(conn, 999999).get("ok") is False)

        print("5) parse_range：正常/后缀/越界/非法")
        cases = [
            ("bytes=0-9", 100, (0, 9)),
            ("bytes=10-", 100, (10, 99)),
            ("bytes=-10", 100, (90, 99)),
            ("bytes=-200", 100, (0, 99)),
            ("bytes=0-0", 100, (0, 0)),
            ("bytes=99-99", 100, (99, 99)),
            ("Bytes=5-9", 100, (5, 9)),
            (" bytes=0-9 ", 100, (0, 9)),
        ]
        for header, size, want in cases:
            got = reader.parse_range(header, size)
            check("Range %r -> %r" % (header, want), got == want, got)
        check("无 Range 头返回 None", reader.parse_range(None, 100) is None)
        check("空 Range 头返回 None", reader.parse_range("  ", 100) is None)
        for header, size in [
            ("bytes=10-5", 100),
            ("bytes=abc-def", 100),
            ("bytes=", 100),
            ("bytes=-", 100),
            ("bytes=-0", 100),
            ("bytes=0-9,20-29", 100),
            ("items=0-1", 100),
            ("bytes=100-", 100),
            ("bytes=0-100", 100),
            ("bytes=99-100", 100),
            ("bytes=0-9", 0),
            ("bytes=0-9", -1),
        ]:
            expect_value_error(
                "非法 Range %r（size=%s）" % (header, size),
                lambda h=header, s=size: reader.parse_range(h, s),
            )

        print("\n全部通过（临时库：%s）" % TMP)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    rc = 1
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
        shutil.rmtree(FILES, ignore_errors=True)
    sys.exit(rc)
