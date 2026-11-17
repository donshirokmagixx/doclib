# -*- coding: utf-8 -*-
"""命令行入口：python -m doclib <命令>

常用：
    python -m doclib init
    python -m doclib import "D:\\资料库"
    python -m doclib search 卷积
    python -m doclib serve
"""
import argparse
import json
import sys

from . import config, db, importer, search, seed, system, tree
from .versioning import PARSE_VERSION


def _p(*args):
    print(*args)


def cmd_rebuild(args):
    """按解析版本重建索引（改动解析/切块后跑一次）。"""
    conn = db.open_db()
    rep = importer.rebuild(conn, limit=args.limit, dry_run=args.dry_run)
    _p(f"当前解析版本 v{rep['current_version']}；落后文档 {rep['outdated']} 份")
    if rep["dry_run"]:
        for it in rep["items"]:
            _p(f"  将重建 [{it['id']}] {it['title']}（v{it['from_version']} → v{rep['current_version']}）")
        if not rep["items"]:
            _p("  没有需要重建的文档。")
    else:
        _p(f"重建成功 {rep['rebuilt']} / 失败 {rep['failed']} / 源文件缺失 {rep['missing']}")
        for it in rep["items"]:
            _p(f"  [{it['status']}] {it['title']} {it.get('note','')}")
    conn.close()


def cmd_key(args):
    """管理本地密钥（DPAPI 加密，不进数据库）。"""
    from . import secrets
    if args.action == "list":
        names = secrets.list_secrets()
        st = secrets.status()
        _p(f"密钥文件：{st['file']}（已存 {st['count']} 个）")
        for n in names:
            _p(f"  {n} = {secrets.masked(n)}")
        if not names:
            _p("  （空）")
    elif args.action == "set":
        import getpass
        val = getpass.getpass(f"请输入 {args.name} 的密钥（不会回显、不会存明文）：")
        if not val:
            _p("已取消")
            return
        secrets.set_secret(args.name, val)
        _p(f"已加密保存，掩码：{secrets.masked(args.name)}")
    elif args.action == "delete":
        _p("已删除" if secrets.delete_secret(args.name) else "没有这个键")


def cmd_providers(args):
    conn = db.open_db()
    rows = conn.execute("SELECT * FROM ai_providers ORDER BY id").fetchall()
    if not rows:
        _p("还没有配置 AI 供应商。")
    for r in rows:
        _p(f"[{r['id']}] {r['name']} · {r['kind']} · {r['base_url']} · {r['model']} "
           f"· key_ref={r['key_ref'] or '（无）'} · role={r['role']} "
           f"· {'启用' if r['enabled'] else '停用'}")
    conn.close()


def cmd_quality(args):
    """列出识别质量低的文档。"""
    conn = db.open_db()
    rows = conn.execute(
        "SELECT id, title, quality, quality_note, file_type FROM documents "
        "WHERE deleted_at IS NULL AND quality < ? ORDER BY quality",
        (args.threshold,),
    ).fetchall()
    _p(f"质量低于 {args.threshold} 的文档：{len(rows)} 份")
    for r in rows:
        _p(f"  [{r['id']}] {r['quality']:.2f} {r['file_type']} {r['title']}  {r['quality_note']}")
    conn.close()


def cmd_init(args):
    conn = db.open_db()
    info = seed.seed(conn)
    _p("数据目录 :", config.DATA_DIR)
    _p("数据库   :", config.DB_PATH)
    _p("知识树   : 新建节点", info["created_nodes"], "个",
       "（未分类节点 id=", info["uncategorized_node"], "）")
    _p("提示     : python -m doclib import \"你的资料文件夹\"")
    conn.close()


def cmd_seed(args):
    conn = db.open_db()
    info = seed.seed(conn)
    _p("新建节点:", info["created_nodes"])
    conn.close()


def cmd_import(args):
    conn = db.open_db()
    rep = importer.import_path(conn, args.path, mount_mode=args.mount)
    _p(f"扫描 {rep['scanned']} 个文件 | 新增 {rep['imported']} | 更新 {rep['updated']} | "
       f"未变 {rep['unchanged']} | 失败 {rep['failed']}")
    for r in rep["items"]:
        flag = {"imported": "+", "updated": "~", "unchanged": "=", "failed": "!",
                "skipped": "-"}.get(r["status"], "?")
        _p(f"  [{flag}] {r['title']}")
        if r["status"] in ("imported", "updated"):
            _p(f"       块 {r['chunks']} / {r['chars']} 字 → 挂载节点 "
               f"{r.get('mounted_to') or '（未分类）'}")
            for s in r.get("suggestion", []):
                _p(f"       建议：{s['name']}（{s['score']}）")
        elif r.get("note"):
            _p(f"       {r['note']}")
    conn.close()


def cmd_mount(args):
    conn = db.open_db()
    importer.mount(conn, args.doc_id, args.node_id)
    _p(f"已把文档 {args.doc_id} 挂到节点 {args.node_id}")
    conn.close()


def cmd_tree(args):
    conn = db.open_db()

    def walk(nodes, indent=0):
        for n in nodes:
            _p("  " * indent + f"[{n['id']}] {n['name']}  "
               f"(本节点 {n['doc_count']} / 含下级 {n['_sub_count']})")
            walk(n["children"], indent + 1)

    walk(tree.tree_json(conn))
    conn.close()


def cmd_docs(args):
    conn = db.open_db()
    rep = search.docs_in_scope(conn, args.node_id, args.scope)
    _p(f"范围内文档 {rep['total']} 份（scope={args.scope}）")
    for r in rep["results"]:
        _p(f"  [{r['doc_id']}] {r['title']}  · {r['chunks']} 块 · "
           f"{r['char_count']} 字 · {r['node_names']}")
    conn.close()


def cmd_search(args):
    conn = db.open_db()
    rep = search.search(conn, args.query, args.node, args.scope)
    _p(f"查询：{rep['query']}   命中词：{rep['terms']}   结果：{rep['total']} 份")
    for i, r in enumerate(rep["results"], 1):
        _p(f"\n{i}. [{r['doc_id']}] {r['title']}   (相关度 {r['score']})")
        _p(f"   来源：{r['node_names']}  ·  {r['heading_path']}")
        _p(f"   {r['snippet']}")
    conn.close()


def cmd_stats(args):
    conn = db.open_db()
    s = search.stats(conn)
    _p(json.dumps(s, ensure_ascii=False, indent=2))
    conn.close()


def cmd_backup(args):
    conn = db.open_db()
    r = system.backup(conn)
    _p(f"备份完成：{r['file']}  ({r['size_kb']} KB)")
    if r["removed"]:
        _p("已清理旧备份：", ", ".join(r["removed"]))
    conn.close()


def cmd_doctor(args):
    conn = db.open_db()
    _p(json.dumps(system.health(conn), ensure_ascii=False, indent=2))
    conn.close()


def cmd_ai_test(args):
    """真发一次最小请求，验证 密钥 / 地址 / 模型 是否都通。"""
    from .ai import gateway
    conn = db.open_db()
    rep = gateway.test_connection(conn, args.name or None)
    if rep.get("ok"):
        _p("连接成功 ✅")
        _p("  配置   :", rep["provider"])
        _p("  模型   :", rep["model"])
        _p("  地址   :", rep["base_url"])
        _p("  回复   :", repr(rep.get("reply")))
        _p("  耗时   :", rep.get("latency_ms"), "ms")
        _p("  token  :", rep.get("tokens"))
    else:
        _p("连接失败 ❌")
        _p(" ", rep.get("error"))
    conn.close()


def cmd_ai_runs(args):
    """最近调用记录与总量。"""
    from .ai import gateway
    conn = db.open_db()
    s = gateway.cost_summary(conn)
    _p(f"累计调用 {s['calls']} 次，失败 {s['failed']} 次，"
       f"tokens: 入 {s['tokens_in']} / 出 {s['tokens_out']}")
    for r in gateway.recent_runs(conn, args.limit):
        ok = "OK" if r["ok"] else "ERR"
        _p(f"  [{ok}] {r['task_type']:<6} {r['provider']}/{r['model']} "
           f"{r['latency_ms']}ms in={r['tokens_in']} out={r['tokens_out']}"
           + (f"  {r['error'][:60]}" if r["error"] else ""))
    conn.close()


def cmd_serve(args):
    if getattr(args, 'window', False):
        from .window import run_window
        raise SystemExit(run_window(port=args.port) or 0)
    from .web.server import run
    rc = run(port=args.port, open_browser=not args.no_browser,
             strict_port=getattr(args, 'strict_port', False))
    if rc:
        raise SystemExit(rc)


def main(argv=None):
    p = argparse.ArgumentParser(prog="doclib", description="个人 Word 资料库（零依赖版）")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("init", help="初始化数据库与知识树").set_defaults(func=cmd_init)
    sub.add_parser("seed", help="只创建知识树").set_defaults(func=cmd_seed)
    sub.add_parser("doctor", help="环境自检").set_defaults(func=cmd_doctor)
    sub.add_parser("stats", help="统计信息").set_defaults(func=cmd_stats)
    sub.add_parser("backup", help="立即备份").set_defaults(func=cmd_backup)

    pi = sub.add_parser("import", help="导入 Word")
    pi.add_argument("path")
    pi.add_argument("--mount", choices=["auto", "none", "uncategorized"], default="auto")
    pi.set_defaults(func=cmd_import)

    pm = sub.add_parser("mount", help="把文档挂到节点")
    pm.add_argument("doc_id", type=int)
    pm.add_argument("node_id", type=int)
    pm.set_defaults(func=cmd_mount)

    sub.add_parser("tree", help="打印节点树").set_defaults(func=cmd_tree)

    pd = sub.add_parser("docs", help="列出节点范围内的文档")
    pd.add_argument("node_id", type=int, nargs="?", default=None)
    pd.add_argument("--scope", choices=["self", "subtree", "all"], default="subtree")
    pd.set_defaults(func=cmd_docs)

    ps = sub.add_parser("search", help="检索")
    ps.add_argument("query")
    ps.add_argument("--node", type=int, default=None)
    ps.add_argument("--scope", choices=["self", "subtree", "all"], default="subtree")
    ps.set_defaults(func=cmd_search)

    pv = sub.add_parser("serve", help="启动本地网页界面")
    pv.add_argument("--port", type=int, default=config.PORT)
    pv.add_argument("--strict-port", action="store_true",
                    help="只用指定端口，不自动避让")
    pv.add_argument("--window", action="store_true",
                    help="用原生窗口打开（不依赖浏览器）")
    pv.add_argument("--no-browser", action="store_true")
    pv.set_defaults(func=cmd_serve)

    # ---------- A1：按解析版本重建 ----------
    pr = sub.add_parser("rebuild", help="按解析版本重建索引")
    pr.add_argument("--limit", type=int, default=0, help="最多重建几份（0=全部）")
    pr.add_argument("--dry-run", action="store_true", help="只看有哪些要重建")
    pr.set_defaults(func=cmd_rebuild)

    # ---------- A4：密钥 / 供应商 ----------
    pk = sub.add_parser("key", help="管理本地加密密钥")
    pk.add_argument("action", choices=["list", "set", "delete"])
    pk.add_argument("name", nargs="?", default="")
    pk.set_defaults(func=cmd_key)

    sub.add_parser("providers", help="列出 AI 供应商配置").set_defaults(func=cmd_providers)

    pa = sub.add_parser("ai-test", help="测试 AI 模型连通性（真发一次请求）")
    pa.add_argument("name", nargs="?", default="", help="模型配置名，省略则用第一个启用中的")
    pa.set_defaults(func=cmd_ai_test)

    par = sub.add_parser("ai-runs", help="查看最近 AI 调用记录")
    par.add_argument("--limit", type=int, default=10)
    par.set_defaults(func=cmd_ai_runs)

    pq = sub.add_parser("quality", help="列出识别质量低的文档")
    pq.add_argument("--threshold", type=float, default=0.6)
    pq.set_defaults(func=cmd_quality)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
