# -*- coding: utf-8 -*-
"""DocLib 全接口 + 安全自检（在临时数据副本上跑，不动真实资料库）。

用法：python scripts\\audit_doclib.py
输出：控制台 PASS/FAIL/风险清单 + JSON 报告
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[1]   # 工程根目录（本文件在 scripts/ 下）
PY = sys.executable
PORT = 8795
BASE = f"http://127.0.0.1:{PORT}"
RESULTS = []


def rec(cat, name, ok, detail=""):
    RESULTS.append({"cat": cat, "name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {cat} · {name}" + (f"  ← {detail}" if detail and not ok else ""))


def wait_port(port, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.4)
    return False


def req(method, path, body=None, raw=None, ctype="application/json", timeout=30, headers=None):
    data = None
    hdrs = dict(headers or {})
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        hdrs.setdefault("Content-Type", ctype)
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", ctype)
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, x.read(), dict(x.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode(), {}


def j(method, path, body=None, **kw):
    st, raw, hdrs = req(method, path, body, **kw)
    try:
        return st, json.loads(raw.decode("utf-8")), raw, hdrs
    except Exception:
        return st, None, raw, hdrs


def main():
    data_src = Path(os.environ.get("DOCLIB_AUDIT_DATA", str(APP / "dist" / "DocLib" / "data")))  # 已收归的正式数据
    tmp = Path(tempfile.mkdtemp(prefix="doclib_audit_"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True)
    for name in ("doclib.db", "secrets.bin", "secrets.portable.json"):
        p = data_src / name
        if p.exists():
            shutil.copy2(p, data_dir / name)
    if (data_src / "mindmaps").exists():
        shutil.copytree(data_src / "mindmaps", data_dir / "mindmaps")
    env = dict(os.environ, DOCLIB_DATA=str(data_dir), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    log = open(tmp / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [PY, "-m", "doclib", "serve", "--no-browser", "--port", str(PORT), "--strict-port"],
        cwd=str(APP), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        if not wait_port(PORT):
            print("服务未启动，日志：", (tmp / "server.log").read_text(encoding="utf-8")[-2000:])
            return 1
        time.sleep(1.5)
        conn_ids = {}

        # ---------- 只读接口 ----------
        st, d, raw, _ = j("GET", "/api/health")
        rec("GET", "health", st == 200 and d and d.get("ok", True) and "build" in d, d)
        rec("GET", "stats", j("GET", "/api/stats")[1].get("documents", 0) > 0)
        st, d, _, _ = j("GET", "/api/tree")
        rec("GET", "tree", st == 200 and isinstance(d, dict), str(d)[:120])
        st, d, _, _ = j("GET", "/api/docs?node=1&scope=subtree")
        rec("GET", "docs", st == 200 and isinstance(d, dict), str(d)[:120])
        st, d, _, _ = j("GET", "/api/search?q=" + urllib.parse.quote("卷积定理") + "&node=1&scope=subtree")
        rec("GET", "search 中文", st == 200 and d and len(d.get("results", [])) > 0, d)
        st, d, _, _ = j("GET", "/api/maps")
        rec("GET", "maps", st == 200 and isinstance(d.get("items"), list), d)
        st, d, _, _ = j("GET", "/api/conv/list")
        items = (d or {}).get("items") or []
        rec("GET", "conv/list", st == 200 and bool(items), d)
        if items:
            cid = items[0]["id"]
            st, d, _, _ = j("GET", f"/api/conv/detail/{cid}")
            rec("GET", "conv/detail", st == 200 and d.get("ok"), d)
            st, d, _, _ = j("GET", f"/api/conv/detail/999999")
            rec("GET", "conv/detail 不存在", st == 200 and d and not d.get("ok"), d)
            conn_ids["conv"] = cid
        st, d, _, _ = j("GET", "/api/backups")
        rec("GET", "backups", st == 200, d)
        st, d, _, _ = j("GET", "/api/recycle")
        rec("GET", "recycle", st == 200, d)
        st, d, _, _ = j("GET", "/api/ai/providers")
        provs = (d or {}).get("items") or []
        rec("GET", "ai/providers", st == 200 and bool(provs), d)
        st, d, _, _ = j("GET", "/api/ai/runs")
        rec("GET", "ai/runs", st == 200, str(d)[:80])
        st, d, _, _ = j("GET", "/api/nonexistent")
        rec("GET", "未知路由", st == 200 and d and "unknown route" in (d.get("error") or ""), d)

        # ---------- 静态资源 ----------
        st, raw, hdrs = req("GET", "/")
        rec("静态", "主页", st == 200 and b"DocLib" in raw, f"status={st} len={len(raw)}")
        st, raw, _ = req("GET", "/mindmap.html")
        rec("静态", "导图页", st == 200 and b"svg" in raw.lower(), f"status={st} len={len(raw)}")
        st, raw, _ = req("GET", "/favicon.ico")
        rec("静态", "favicon", st in (200, 204), st)

        # ---------- 知识树写操作（临时库） ----------
        st, d, _, _ = j("POST", "/api/node/create", {"parent": 1, "name": "_审计临时节点"})
        nid = (d or {}).get("node_id") or (d or {}).get("id")
        rec("树", "node/create", bool(d and d.get("ok") and nid), d)
        if nid:
            rec("树", "node/rename", (j("POST", "/api/node/rename", {"node_id": nid, "name": "_审计改名"})[1] or {}).get("ok"))
            rec("树", "node/move", (j("POST", "/api/node/move", {"node_id": nid, "parent_id": 10})[1] or {}).get("ok"))
            rec("树", "node/indent", (j("POST", "/api/node/indent", {"node_id": nid})[1] or {}).get("ok"))
            _st, _d, _, _ = j("POST", "/api/node/create", {"parent_id": 1, "name": "_审计同级"})
            nid2 = (_d or {}).get("node_id")
            rec("树", "node/reorder", bool(nid2) and (j("POST", "/api/node/reorder", {"node_id": nid2, "delta": -1})[1] or {}).get("ok"))
            if nid2:
                j("POST", "/api/node/delete", {"node_id": nid2})
            st, d, _, _ = j("POST", "/api/node/delete", {"node_id": nid})
            rec("树", "node/delete", st == 200 and (d or {}).get("ok"), d)
        st_bad, d_bad, _, _ = j("POST", "/api/node/create", {})
        rec("树", "node/create 缺参数", st_bad < 500 and not (d_bad or {}).get("ok"), d_bad)

        # ---------- 文档操作（临时库，可回滚） ----------
        st, d, _, _ = j("GET", "/api/docs?node=1&scope=all")
        docs = (d or {}).get("items") or (d or {}).get("docs") or []
        doc_id = None
        for it in docs:
            doc_id = it.get("id") or it.get("doc_id")
            if doc_id:
                break
        if doc_id:
            rec("文档", "doc/mount", (j("POST", "/api/doc/mount", {"doc_id": doc_id, "node_id": 1})[1] or {}).get("ok"))
            rec("文档", "doc/set_nodes", j("POST", "/api/doc/set_nodes", {"doc_id": doc_id, "nodes": [1]})[0] != 500)
            rec("文档", "doc/delete", (j("POST", "/api/doc/delete", {"doc_id": doc_id})[1] or {}).get("ok"))
            rec("文档", "doc/restore", (j("POST", "/api/doc/restore", {"doc_id": doc_id})[1] or {}).get("ok"))

        # ---------- 会话/导出 ----------
        if items:
            cid = next((x["id"] for x in items if x.get("turns", 0) > 0), items[0]["id"])
            conn_ids["conv"] = cid
            rec("导出", "conv/export(qa)", (j("POST", "/api/conv/export", {"id": cid})[1] or {}).get("ok"))
            rec("导出", "conv/export(outline)", (j("POST", "/api/conv/export", {"id": cid, "mode": "outline"})[1] or {}).get("ok"))
            rec("导出", "conv/export_batch", (j("POST", "/api/conv/export_batch", {"ids": [cid], "mode": "outline", "title": "_审计合并"})[1] or {}).get("ok"))
            st, raw, hdrs = req("GET", f"/api/conv/{cid}/docx")
            rec("导出", "GET docx 下载", st == 200 and raw[:2] == b"PK" and "attachment" in (hdrs.get("Content-Disposition") or ""), f"status={st} len={len(raw)}")
            st, d, _, _ = j("GET", "/api/conv/999999/docx")
            rec("导出", "docx 不存在", st == 200 and d and not d.get("ok"), d)

        # ---------- 导图 ----------
        st, d, _, _ = j("POST", "/api/map/new", {"name": "_审计导图"})
        rec("导图", "map/new", (d or {}).get("ok"), d)
        rec("导图", "map/save", (j("POST", "/api/map/save", {"name": "_审计导图", "data": {"items": [], "edges": [], "strokes": []}})[1] or {}).get("ok"))
        rec("导图", "map/rename", (j("POST", "/api/map/rename", {"name": "_审计导图", "new_name": "_审计导图2"})[1] or {}).get("ok"))
        rec("导图", "map/delete", (j("POST", "/api/map/delete", {"name": "_审计导图2"})[1] or {}).get("ok"))
        st, d, _, _ = j("POST", "/api/map/save", {"name": "../../逃逸测试", "data": {}})
        escaped = list(data_dir.glob("**/逃逸测试*.json"))
        rec("导图", "路径逃逸防护", not any("mindmaps" not in str(p) for p in escaped), [str(p) for p in escaped])

        # ---------- 备份/维护/seed/密钥 ----------
        rec("运维", "backup", (j("POST", "/api/backup", {})[1] or {}).get("ok", True))
        rec("运维", "maintenance", (j("POST", "/api/maintenance", {})[1] or {}).get("ok", True))
        rec("运维", "seed", (j("POST", "/api/seed", {})[1] or {}).get("ok", True))
        rec("密钥", "secrets 写入", (j("POST", "/api/secrets", {"name": "audit_tmp", "value": "audit-1234567890abcdef"})[1] or {}).get("ok"))
        rec("密钥", "secrets 删除", (j("POST", "/api/secrets", {"delete": "audit_tmp"})[1] or {}).get("ok"))
        st, raw, _ = req("GET", "/api/secrets")
        rec("密钥", "GET secrets 不泄密", b"audit-1234567890abcdef" not in raw, raw[:120])

        # ---------- AI ----------
        if provs:
            name = provs[0].get("name")
            st, d, _, _ = j("POST", "/api/ai/test", {"name": name}, timeout=60)
            rec("AI", "ai/test", st == 200 and "ok" in (d or {}), str(d)[:120])

        # ---------- 安全探针 ----------
        # S1 CSRF：无 Origin 校验 + 忽略 Content-Type → 任意打开本地文件
        probe = tmp / "csrf_probe.txt"
        probe.write_text("csrf", encoding="utf-8")
        st, d, _, _ = j("POST", "/api/open", {"path": str(probe)},
                        ctype="text/plain", headers={"Origin": "http://evil.example"})
        rec("安全", "CSRF:/api/open 任意路径", not (d or {}).get("ok"),
            f"status={st} body={str(d)[:100]}")

        # S2 导入接口：跨站必须拒绝；非文档类型必须拒绝；同源文本允许（本地用户主动）
        leak = tmp / "leak_probe.txt"
        leak.write_text("SECRET-MARKER-12345", encoding="utf-8")
        st, d, _, _ = j("POST", "/api/import", {"path": str(leak)},
                        headers={"Origin": "http://evil.example"})
        rec("安全", "导入接口跨站拒绝", st == 403, f"status={st}")
        exe = tmp / "evil_probe.exe"
        exe.write_bytes(b"MZ")
        st, d, _, _ = j("POST", "/api/import", {"path": str(exe)})
        rec("安全", "非文档类型导入被拒", not (d or {}).get("ok"), d)
        st, d, _, _ = j("POST", "/api/import", {"path": str(leak)})
        imported = (d or {}).get("imported", 0)
        rec("功能", "同源文本导入", bool(imported), d)

        # S3 静态目录穿越
        for p in ("/../data/doclib.db", "/%2e%2e/data/doclib.db", "/..%2f..%2fdata%2fdoclib.db"):
            st, raw, hdrs = req("GET", p)
            body_ok = not raw.startswith(b"SQLite format")
            rec("安全", f"静态穿越 {p}", body_ok, f"status={st} head={raw[:24]!r}")

        # S4 缺参数→500 统计
        bad = {
            "/api/doc/mount": {}, "/api/doc/delete": {}, "/api/node/rename": {},
            "/api/conv/update": {}, "/api/conv/delete": {}, "/api/map/rename": {},
            "/api/conv/export": {}, "/api/conv/export_batch": {},
        }
        err500 = []
        for p, b in bad.items():
            st, _, _ = req("POST", p, b)
            if st >= 500:
                err500.append(p)
        rec("健壮性", "缺参数不返回 500", not err500, err500)

        # S5 非法 JSON
        st, d, _, _ = j("POST", "/api/search", raw="{not json", ctype="application/json")
        rec("健壮性", "非法 JSON 不 500", st < 500, st)

        # S6 超大 body
        big = {"q": "x" * 2_000_000}
        st, d, _, _ = j("POST", "/api/search", big, timeout=60)
        rec("健壮性", "2MB body 不崩", st < 500, st)

        # S1b：跨站 Origin + 正确 Content-Type → 403
        st, d, _, _ = j("POST", "/api/open", {"path": str(probe)},
                        headers={"Origin": "http://evil.example"})
        rec("安全", "跨站 Origin 被拒", st == 403, f"status={st} {d}")
        # S1c：同源 Origin → 正常
        st, d, _, _ = j("POST", "/api/open", {"path": str(probe)},
                        headers={"Origin": BASE})
        rec("安全", "同源 Origin 可用", st == 200, f"status={st} {d}")
        # S1d：text/plain → 415
        st, d, _, _ = j("POST", "/api/open", {"path": str(probe)}, ctype="text/plain")
        rec("安全", "非 JSON 类型被拒", st == 415, f"status={st} {d}")
        # S1e：资料库外的路径 → 拒绝（不能打开任意 exe/txt）
        outside = tmp / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        st, d, _, _ = j("POST", "/api/open", {"path": str(outside)})
        rec("安全", "资料库外路径被拒", not (d or {}).get("ok"), d)
        # 缺参数
        st, d, _, _ = j("POST", "/api/doc/mount", {})
        rec("健壮性", "doc/mount 缺参数友好", st < 500 and not (d or {}).get("ok"), d)
        st, d, _, _ = j("POST", "/api/node/rename", {})
        rec("健壮性", "node/rename 缺参数友好", st < 500 and not (d or {}).get("ok"), d)

        # S6b：所有 POST 路由空参扫描（不应 500）
        post_routes = ["/api/doc/mount", "/api/doc/delete", "/api/doc/restore", "/api/doc/purge",
                       "/api/doc/move", "/api/doc/set_nodes", "/api/node/create", "/api/node/rename",
                       "/api/node/move", "/api/node/indent", "/api/node/reorder", "/api/node/delete",
                       "/api/recycle/restore", "/api/recycle/purge", "/api/recycle/purge_docs",
                       "/api/backup", "/api/maintenance", "/api/seed", "/api/rebuild",
                       "/api/conv/new", "/api/conv/update", "/api/conv/delete",
                       "/api/conv/export", "/api/conv/export_batch",
                       "/api/map/new", "/api/map/save", "/api/map/rename", "/api/map/delete",
                       "/api/ai/test", "/api/ai/providers/default", "/api/ai/providers/toggle",
                       "/api/ai/providers/delete", "/api/ai/embed", "/api/ai/embed/clear",
                       "/api/import", "/api/open", "/api/secrets"]
        bad500 = []
        for rp in post_routes:
            if rp in ("/api/rebuild", "/api/ai/embed/index"):
                continue
            st, _, _ = req("POST", rp, {})
            if st >= 500:
                bad500.append((rp, st))
        rec("健壮性", "全路由空参不 500", not bad500, bad500)

        # S7 头信息
        st, raw, hdrs = req("GET", "/api/health")
        low = {k.lower(): v for k, v in hdrs.items()}
        rec("安全", "无 CORS 通配", "access-control-allow-origin" not in low, low)
        rec("安全", "安全响应头", low.get("x-content-type-options") == "nosniff"
            and low.get("x-frame-options") in ("DENY", "SAMEORIGIN"), low)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(RESULTS)
    failed = [r for r in RESULTS if not r["ok"]]
    print("\n" + "=" * 60)
    print(f"共 {total} 项，通过 {total - len(failed)}，失败 {len(failed)}")
    for r in failed:
        print(f"  ✗ {r['cat']} · {r['name']}  ← {r['detail']}")
    out = APP / "审计报告_接口与安全.json"
    out.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "total": total, "failed": failed,
                               "all": RESULTS}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("报告：", out)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())