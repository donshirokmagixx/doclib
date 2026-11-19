# -*- coding: utf-8 -*-
"""DocLib 2.0 图谱模块自测（不碰正本数据）。

覆盖：
  1) seed + 临时建两分区/子节点/文档/多挂载/笔记/relations/note_links
  2) global 实体/边计数；hierarchy/mount/manual/wikilink 均出现；
     ai 默认隐藏，rels 显式包含才出现
  3) 分区隔离；local depth=1/2 节点集变化；center 文档能带出其挂载节点
  4) 软删除文档/节点/笔记后不再出现；limit 截断与 total_nodes；
     同名实体不合并、multi-mount 不重复边
  5) 空库、非法分区、非法 center 返回 ok=False + error

用法：
    E:\\user351282\\知序\\DocLib\\.venv\\Scripts\\python.exe tests\\test_graph.py
（测试内自建 tempfile 作为 DOCLIB_DATA，结束后删除）
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

# 必须在导入 doclib 之前指定临时数据目录，避免碰到 dist/data 或 data/
TMP = tempfile.mkdtemp(prefix="doclib_graph_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import db, seed, tree           # noqa: E402
from doclib.graph import build_graph        # noqa: E402

NOW = 1700000000000
_DOC_SEQ = [0]


# ---------------------------------------------------------------------------
# 造数工具
# ---------------------------------------------------------------------------

def add_doc(conn, title, node_ids=(), text="", file_type="md"):
    """插资料并按 node_ids 建立挂载；返回 doc_id。"""
    _DOC_SEQ[0] += 1
    path = f"D:/tmp/graph/d{_DOC_SEQ[0]}_{title}.{file_type}"
    cur = conn.execute(
        "INSERT INTO documents(title, file_path, path_key, file_type, parse_status,"
        " char_count, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (title, path, path.lower(), file_type, 2, len(text), NOW, NOW),
    )
    did = cur.lastrowid
    for node_id in node_ids:
        conn.execute(
            "INSERT INTO node_documents(node_id, document_id, weight, note, created_at)"
            " VALUES(?,?,?,?,?)",
            (node_id, did, 1.0, "", NOW),
        )
    return did


def add_note(conn, title, node_id, partition_id, body="笔记正文"):
    """插一条未删除笔记；返回 note_id。"""
    cur = conn.execute(
        "INSERT INTO notes(title, body_md, node_id, partition_id, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (title, body, node_id, partition_id, NOW, NOW),
    )
    return cur.lastrowid


def add_relation(conn, src, dst, origin="manual", rel="related",
                 confidence=1.0, label=""):
    """插一条人工/AI 关系（src/dst 为 (kind, id)）。"""
    conn.execute(
        "INSERT INTO relations(src_kind, src_id, dst_kind, dst_id, rel, label, origin,"
        " confidence, evidence_json, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (src[0], src[1], dst[0], dst[1], rel, label, origin, confidence, "{}", NOW, NOW),
    )


def add_link(conn, note_id, target, title="", resolved=1, start=0, end=0):
    """插一条 note_links；target=None 表示未解析链接。"""
    kind, entity_id = target if target else (None, None)
    conn.execute(
        "INSERT INTO note_links(note_id, target_kind, target_id, target_title, heading,"
        " alias, start_off, end_off, resolved, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (note_id, kind, entity_id, title, "", "", start, end, resolved, NOW),
    )


def check(name, condition, detail=""):
    print(("  [PASS] " if condition else "  [FAIL] ") + name
          + ("" if condition else f"  ← {detail}"))
    assert condition, name


def ids_of(result):
    return {node["id"] for node in result["nodes"]}


def rels_of(result):
    return {edge["rel"] for edge in result["edges"]}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    conn = db.open_db()
    try:
        # ---------------- 1. 造数 ----------------
        print("1) seed + 两分区/文档/笔记/关系/双链")
        seed.seed(conn)
        seed_root = conn.execute(
            "SELECT id FROM nodes WHERE parent_id IS NULL AND name='信号分析与处理'"
        ).fetchone()["id"]
        a = tree.create_node(conn, "科目A", None)
        a1 = tree.create_node(conn, "A-第一章", a)
        b = tree.create_node(conn, "科目B", None)

        # doc_a1 同时挂 a1 与 a（multi-mount）；doc_b 与 doc_dup 同名
        doc_a1 = add_doc(conn, "Alpha 资料", [a1, a], "alpha 内容")
        doc_a2 = add_doc(conn, "A 总论", [a], "A 总论内容")
        doc_b = add_doc(conn, "B 资料", [b], "B 内容")
        doc_dup = add_doc(conn, "Alpha 资料", [b], "同名不同资料")
        doc_free = add_doc(conn, "未挂载资料", [], "孤立资料")
        note_a = add_note(conn, "A 笔记", a1, a)
        note_b = add_note(conn, "B 笔记", b, b)
        doc_a1_path = conn.execute(
            "SELECT file_path FROM documents WHERE id=?", (doc_a1,)
        ).fetchone()["file_path"]

        add_relation(conn, ("node", a1), ("node", a), origin="manual",
                     confidence=0.9, label="人工关联")
        add_relation(conn, ("note", note_a), ("node", a1), origin="ai",
                     confidence=0.7)
        add_link(conn, note_a, ("document", doc_a1), "Alpha 资料", start=0, end=10)
        add_link(conn, note_a, ("document", doc_a1), "Alpha 资料", start=20, end=30)  # 重复提及
        add_link(conn, note_a, ("node", a1), "A-第一章")
        add_link(conn, note_b, ("note", note_a), "A 笔记")
        add_link(conn, note_a, None, "B 资料", resolved=0)                  # 未解析
        check("造数完成", all((seed_root, a, a1, b, doc_a1, note_a)))

        # ---------------- 2. global 投影 ----------------
        print("2) global 实体/边/元数据/关系过滤")
        g = build_graph(conn)
        check("global 返回 ok", g["ok"] is True and g["scope"] == "global")
        check("global center=None 且未截断",
              g["center"] is None and g["truncated"] is False)
        # 8 节点 + 5 文档 + 2 笔记 = 15；13 条默认边
        check("global 实体数 15", g["stats"]["nodes"] == 15 and len(g["nodes"]) == 15,
              g["stats"])
        check("global 边数 13", g["stats"]["edges"] == 13 and len(g["edges"]) == 13,
              (g["stats"], sorted(rels_of(g))))
        check("stats.total_nodes=15", g["stats"]["total_nodes"] == 15, g["stats"])

        all_ids = ids_of(g)
        check("实体 ID 命名空间",
              {f"node:{a}", f"node:{a1}", f"document:{doc_a1}",
               f"note:{note_a}"} <= all_ids)
        check("未挂载文档也在全库", f"document:{doc_free}" in all_ids)

        check("四类边齐全",
              rels_of(g) == {"hierarchy", "mount", "manual", "wikilink"}, rels_of(g))
        check("ai 默认隐藏", "ai" not in rels_of(g))
        check("派生边 origin=system",
              all(e["origin"] == "system" for e in g["edges"]
                  if e["rel"] in ("hierarchy", "mount")))

        node_a = next(n for n in g["nodes"] if n["id"] == f"node:{a}")
        check("节点 meta 含 path/doc_count",
              node_a["meta"] == {"path": f"/{a}/", "doc_count": 2}, node_a["meta"])
        check("节点 partition_id", node_a["partition_id"] == a, node_a)
        node_a1 = next(n for n in g["nodes"] if n["id"] == f"node:{a1}")
        check("子节点 doc_count=1", node_a1["meta"]["doc_count"] == 1, node_a1["meta"])

        doc_node = next(n for n in g["nodes"] if n["id"] == f"document:{doc_a1}")
        check("文档 meta 含 file_type/file_path",
              doc_node["meta"] == {"file_type": "md", "file_path": doc_a1_path},
              doc_node["meta"])
        check("文档 partition_id 随挂载节点", doc_node["partition_id"] == a, doc_node)

        note_node = next(n for n in g["nodes"] if n["id"] == f"note:{note_a}")
        check("笔记 meta 含 node_id/partition_id",
              note_node["meta"] == {"node_id": a1, "partition_id": a},
              note_node["meta"])

        # 边结构与去重
        required_edge_keys = {"id", "source", "target", "rel", "origin",
                              "weight", "directed"}
        check("边字段齐全",
              all(required_edge_keys <= set(e) for e in g["edges"]))
        check("边 ID 唯一",
              len({e["id"] for e in g["edges"]}) == len(g["edges"]))
        triples = [(e["source"], e["rel"], e["target"]) for e in g["edges"]]
        check("无重复边", len(triples) == len(set(triples)))
        check("无悬空边",
              all(e["source"] in all_ids and e["target"] in all_ids
                  for e in g["edges"]))
        check("无敏感字段",
              not any(k in json.dumps(g, ensure_ascii=False)
                      for k in ("file_hash", "body_md", "api_key", "evidence_json")))

        hier = [e for e in g["edges"]
                if e["rel"] == "hierarchy" and e["target"] == f"node:{a1}"]
        check("hierarchy 父→子",
              len(hier) == 1 and hier[0]["source"] == f"node:{a}"
              and hier[0]["directed"] is True, hier)

        mounts = [e for e in g["edges"]
                  if e["rel"] == "mount" and e["target"] == f"document:{doc_a1}"]
        check("multi-mount 两条不同边",
              {e["source"] for e in mounts} == {f"node:{a}", f"node:{a1}"}, mounts)
        check("multi-mount 无重复",
              len(mounts) == 2 and len({e["id"] for e in mounts}) == 2)

        wikis = [e for e in g["edges"]
                 if e["rel"] == "wikilink" and e["source"] == f"note:{note_a}"
                 and e["target"] == f"document:{doc_a1}"]
        check("重复提及只保留一条 wikilink", len(wikis) == 1, wikis)
        check("wikilink origin=wikilink", wikis[0]["origin"] == "wikilink")
        check("未解析 note_links 不出现",
              not any(e["target"] == f"document:{doc_b}" and e["rel"] == "wikilink"
                      for e in g["edges"]))

        # 同名实体按稳定 ID 分开
        alpha_nodes = [n for n in g["nodes"] if n["label"] == "Alpha 资料"]
        check("同名文档各自成节点",
              {n["id"] for n in alpha_nodes}
              == {f"document:{doc_a1}", f"document:{doc_dup}"}, alpha_nodes)
        dup_mounts = [e for e in g["edges"]
                      if e["target"] == f"document:{doc_dup}"]
        check("同名文档边不串",
              {e["source"] for e in dup_mounts} == {f"node:{b}"}, dup_mounts)

        # ai 边：默认隐藏，显式 rels 才出现
        g_ai = build_graph(conn, rels="hierarchy,mount,manual,wikilink,ai")
        ai_edges = [e for e in g_ai["edges"] if e["rel"] == "ai"]
        check("显式 rels 才出现 ai",
              len(ai_edges) == 1 and ai_edges[0]["origin"] == "ai"
              and ai_edges[0]["directed"] is False, ai_edges)
        check("含 ai 后边数 14", g_ai["stats"]["edges"] == 14, g_ai["stats"])

        # types / rels 过滤
        g_types = build_graph(conn, types="node")
        check("types=node 只含节点",
              {n["kind"] for n in g_types["nodes"]} == {"node"})
        check("types=node 计数 8/5",
              g_types["stats"]["nodes"] == 8 and g_types["stats"]["edges"] == 5,
              g_types["stats"])
        g_rels = build_graph(conn, rels={"manual"})
        check("rels 集合只留 manual",
              g_rels["stats"]["edges"] == 1
              and rels_of(g_rels) == {"manual"}, g_rels["stats"])

        # q 过滤（大小写不敏感；先过滤实体再算边）
        g_q = build_graph(conn, q="ALPHA")
        check("q 大小写不敏感且按 label 命中同名两条",
              ids_of(g_q) == {f"document:{doc_a1}", f"document:{doc_dup}"},
              ids_of(g_q))
        check("q 后无跨实体边",
              g_q["stats"]["edges"] == 0 and g_q["stats"]["total_nodes"] == 2,
              g_q["stats"])
        g_q0 = build_graph(conn, q="不存在xyz")
        check("q 无匹配仍 ok", g_q0["ok"] is True
              and g_q0["stats"]["nodes"] == 0, g_q0["stats"])

        # ---------------- 3. 分区隔离 ----------------
        print("3) 分区隔离")
        g_a = build_graph(conn, partition_id=a)
        check("分区A实体 5", g_a["stats"]["nodes"] == 5, g_a["stats"])
        check("分区A边 7", g_a["stats"]["edges"] == 7, g_a["stats"])
        check("分区A只含本分区实体",
              ids_of(g_a) == {f"node:{a}", f"node:{a1}", f"document:{doc_a1}",
                              f"document:{doc_a2}", f"note:{note_a}"}, ids_of(g_a))
        check("分区A隔离 B 文档/笔记",
              f"document:{doc_b}" not in ids_of(g_a)
              and f"note:{note_b}" not in ids_of(g_a))
        check("分区A内 multi-mount 两条",
              len([e for e in g_a["edges"]
                   if e["rel"] == "mount" and e["target"] == f"document:{doc_a1}"]) == 2)
        check("分区A实体 partition_id 统一",
              all(n["partition_id"] == a for n in g_a["nodes"]),
              [(n["id"], n["partition_id"]) for n in g_a["nodes"]])

        g_b = build_graph(conn, partition_id=b)
        check("分区B实体 4", g_b["stats"]["nodes"] == 4, g_b["stats"])
        check("分区B边 2", g_b["stats"]["edges"] == 2, g_b["stats"])
        check("分区B只含本分区",
              ids_of(g_b) == {f"node:{b}", f"document:{doc_b}",
                              f"document:{doc_dup}", f"note:{note_b}"}, ids_of(g_b))

        for bad_partition in (999999, a1):
            bad = build_graph(conn, partition_id=bad_partition)
            check(f"非法分区 {bad_partition} 报错",
                  bad["ok"] is False and "分区" in bad["error"], bad)

        # ---------------- 4. local 局部图 ----------------
        print("4) local depth 1/2 与 center 文档")
        l1 = build_graph(conn, scope="local", center=f"node:{a1}", depth=1)
        l1_ids = ids_of(l1)
        check("local depth1 节点集",
              l1_ids == {f"node:{a1}", f"node:{a}", f"document:{doc_a1}",
                         f"note:{note_a}"}, l1_ids)
        check("local depth1 边 6", l1["stats"]["edges"] == 6, l1["stats"])
        check("local 返回 center", l1["center"] == f"node:{a1}")

        l2 = build_graph(conn, scope="local", center=f"node:{a1}", depth=2)
        check("local depth2 扩出 doc_a2/note_b",
              ids_of(l2) == l1_ids | {f"document:{doc_a2}", f"note:{note_b}"},
              ids_of(l2))
        check("local depth2 边 8", l2["stats"]["edges"] == 8, l2["stats"])

        ld = build_graph(conn, scope="local", center=f"document:{doc_a1}", depth=1)
        check("center 文档带出其挂载节点",
              {f"node:{a}", f"node:{a1}"} <= ids_of(ld), ids_of(ld))
        check("center 文档局部图含双链笔记",
              f"note:{note_a}" in ids_of(ld), ids_of(ld))

        for bad_center in (f"node:999999", "bogus:1", "not-a-ref", None):
            bad = build_graph(conn, scope="local", center=bad_center)
            check(f"非法 center {bad_center!r} 报错",
                  bad["ok"] is False and bool(bad["error"]), bad)

        # ---------------- 5. limit 截断 ----------------
        print("5) limit 截断与度数重算")
        gl = build_graph(conn, limit=5)
        check("limit 截断标记", gl["truncated"] is True)
        check("截断后 nodes/total_nodes/edges",
              gl["stats"]["nodes"] == 5 and gl["stats"]["total_nodes"] == 15
              and gl["stats"]["edges"] == 6, gl["stats"])
        kept_expected = {f"node:{seed_root}", f"node:{a}", f"node:{a1}",
                         f"document:{doc_a1}", f"note:{note_a}"}
        check("按度数保留高连接节点", ids_of(gl) == kept_expected, ids_of(gl))
        check("截断后无悬空边",
              all(e["source"] in ids_of(gl) and e["target"] in ids_of(gl)
                  for e in gl["edges"]))
        degree_ok = all(
            n["degree"] == sum(1 for e in gl["edges"]
                               if n["id"] in (e["source"], e["target"]))
            for n in gl["nodes"]
        )
        check("截断后 degree 在子图内重算", degree_ok,
              [(n["id"], n["degree"]) for n in gl["nodes"]])

        # ---------------- 6. 软删除 ----------------
        print("6) 软删除文档/节点/笔记后不再出现")
        conn.execute("UPDATE documents SET deleted_at=?, updated_at=? WHERE id=?",
                     (NOW + 1, NOW + 1, doc_a2))
        g_del = build_graph(conn)
        check("软删文档不出现", f"document:{doc_a2}" not in ids_of(g_del))
        check("软删文档边消失",
              not any(e["target"] == f"document:{doc_a2}" for e in g_del["edges"]))
        node_a_after = next(n for n in g_del["nodes"] if n["id"] == f"node:{a}")
        check("节点 doc_count 随之减少", node_a_after["meta"]["doc_count"] == 1,
              node_a_after["meta"])
        check("删文档后计数 14/12",
              g_del["stats"]["nodes"] == 14 and g_del["stats"]["edges"] == 12,
              g_del["stats"])

        conn.execute("UPDATE notes SET deleted_at=?, updated_at=? WHERE id=?",
                     (NOW + 2, NOW + 2, note_b))
        g_del = build_graph(conn)
        check("软删笔记不出现", f"note:{note_b}" not in ids_of(g_del))
        check("软删笔记的双链边消失",
              not any(e["source"] == f"note:{note_b}" for e in g_del["edges"]))
        check("删笔记后计数 13/11",
              g_del["stats"]["nodes"] == 13 and g_del["stats"]["edges"] == 11,
              g_del["stats"])

        tree.delete_node(conn, a1)
        g_del = build_graph(conn)
        check("软删节点子树不出现", f"node:{a1}" not in ids_of(g_del))
        check("删节点后计数 12/7",
              g_del["stats"]["nodes"] == 12 and g_del["stats"]["edges"] == 7,
              g_del["stats"])
        check("文档仍有其他挂载所以保留",
              f"document:{doc_a1}" in ids_of(g_del))
        check("删节点后其边全部消失",
              not any(f"node:{a1}" in (e["source"], e["target"])
                      for e in g_del["edges"]))
        local_deleted = build_graph(conn, scope="local", center=f"node:{a1}")
        check("已删节点作 center 报错", local_deleted["ok"] is False)

        conn.execute("UPDATE documents SET deleted_at=?, updated_at=? WHERE id=?",
                     (NOW + 3, NOW + 3, doc_b))
        g_del = build_graph(conn)
        check("再删文档后计数 11/6",
              g_del["stats"]["nodes"] == 11 and g_del["stats"]["edges"] == 6,
              g_del["stats"])
        deleted_ids = {f"node:{a1}", f"document:{doc_a2}",
                       f"document:{doc_b}", f"note:{note_b}"}
        check("已删实体不出现在任何边的端点",
              not any(e["source"] in deleted_ids or e["target"] in deleted_ids
                      for e in g_del["edges"]))
        check("未删实体仍完整", f"note:{note_a}" in ids_of(g_del)
              and f"document:{doc_dup}" in ids_of(g_del))

        # ---------------- 7. 空库 ----------------
        print("7) 空库报错")
        mem = sqlite3.connect(":memory:")
        mem.row_factory = sqlite3.Row
        db.migrate(mem)
        empty = build_graph(mem)
        check("空库 global 报错",
              empty["ok"] is False and bool(empty["error"]), empty)
        empty_local = build_graph(mem, scope="local", center="node:1")
        check("空库 local 报错",
              empty_local["ok"] is False and bool(empty_local["error"]))
        mem.close()

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
