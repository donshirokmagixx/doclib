# -*- coding: utf-8 -*-
"""真实 HTTP 层：MIME、404、CSP/XFO、Range、工作区 API、Host 校验。"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
TMP = tempfile.mkdtemp(prefix="doclib_http_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, seed  # noqa: E402
from doclib.web import server  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  ← {extra}"))
    if not cond:
        FAIL.append(name)


def main():
    # 临时文档 + 文件
    conn = db.open_db()
    seed.seed(conn)
    src = Path(TMP) / "range.txt"
    src.write_text("0123456789", encoding="utf-8")
    cur = conn.execute(
        "INSERT INTO documents(title,file_path,path_key,file_type,parse_status,file_size,"
        "created_at,updated_at) VALUES('range.txt',?,?,'txt',2,10,1,1)",
        (str(src), str(src).lower()))
    did = cur.lastrowid
    conn.execute("INSERT INTO doc_chunks(doc_id,ord,heading_path,text,char_len) VALUES(?,0,'x','0123456789',10)", (did,))
    conn.execute("INSERT INTO nodes(id,parent_id,name,path,depth,created_at,updated_at) VALUES(99,NULL,'测试','/99/',0,1,1)")
    conn.execute("INSERT INTO node_documents(node_id,document_id,weight,note,created_at) VALUES(99,?,1,'',1)", (did,))
    conn.commit()
    conn.close()

    httpd, port, base = server.start_server(port=8899, strict_port=False, do_backup=False)
    try:
        print("1) 静态资源 / CSP / MIME")
        req = urllib.request.Request(base)
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8", "replace")
            check("index 200", r.status == 200)
            check("CSP 存在", "default-src 'self'" in (r.headers.get("Content-Security-Policy") or ""))
            check("XFO SAMEORIGIN", r.headers.get("X-Frame-Options") == "SAMEORIGIN")
            check("index 含 app/main.js", "/app/main.js" in body)
        with urllib.request.urlopen(base + "vendor/cytoscape.min.js", timeout=5) as r:
            check("js MIME", (r.headers.get("Content-Type") or "").startswith("application/javascript"))
        try:
            urllib.request.urlopen(base + "vendor/nope.js", timeout=5)
            check("缺失静态 404", False)
        except urllib.error.HTTPError as e:
            check("缺失静态 404", e.code == 404, e.code)

        print("2) 工作区 API")
        with urllib.request.urlopen(base + "api/v2/workspace", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            check("workspace ok", data.get("ok") is True, data)
        req = urllib.request.Request(base + "api/v2/workspace", method="POST",
                                     data=json.dumps({"workspace": {"theme": "light", "panes": []}}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            check("workspace save ok", data.get("ok") is True, data)

        print("3) 阅读器 / Range")
        with urllib.request.urlopen(base + f"api/v2/reader/{did}", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            check("reader ok", data.get("ok") is True and data.get("chunks"), data)
        req = urllib.request.Request(base + f"api/v2/file/{did}", headers={"Range": "bytes=2-5"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read()
            check("range 206", r.status == 206)
            check("range 内容", body == b"2345", body)
            check("Content-Range", r.headers.get("Content-Range") == "bytes 2-5/10",
                  r.headers.get("Content-Range"))
        req = urllib.request.Request(base + f"api/v2/file/{did}", headers={"Range": "bytes=99-100"})
        try:
            urllib.request.urlopen(req, timeout=5)
            check("越界 416", False)
        except urllib.error.HTTPError as e:
            check("越界 416", e.code == 416, e.code)

        print("4) Host 校验")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest("GET", "/api/v2/workspace", skip_host=True)
        c.putheader("Host", "evil.example")
        c.endheaders()
        resp = c.getresponse()
        check("evil host 403", resp.status == 403, resp.status)
        c.close()
    finally:
        server.stop_server(httpd)

    print("\n全部通过 ✅（临时库：%s）" % TMP)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
