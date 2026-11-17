# -*- coding: utf-8 -*-
"""冒烟测试：不依赖任何第三方库，直接 python tests/smoke.py 运行。

覆盖：迁移建表 / trigram 可用 / 树操作 / 软删除 / 分块 / 检索（长词+短词）/ 范围过滤 / 备份
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="doclib-smoke-"))
os.environ["DOCLIB_DATA"] = str(TMP)

from doclib import chunker, db, importer, search, seed, system, tree  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    if cond:
        print(f"  [OK]   {name}")
    else:
        print(f"  [FAIL] {name}  {extra}")
        FAILED.append(name)


def insert_doc(conn, title, text, node_id=None):
    import hashlib
    ts = db.now_ms()
    p = TMP / (hashlib.md5(title.encode()).hexdigest() + ".docx")
    p.write_text("fake", encoding="utf-8")
    cur = conn.execute(
        "INSERT INTO documents(title,file_path,path_key,file_hash,file_type,parse_status,"
        "char_count,created_at,updated_at) VALUES(?,?,?,?,'docx',2,?,?,?)",
        (title, str(p), str(p).lower(), "h", len(text), ts, ts),
    )
    did = cur.lastrowid
    chunk = {"ord": 0, "heading_path": "第 1 章 测试", "text": text,
             "char_len": len(text), "is_table": 0}
    conn.execute(
        "INSERT INTO doc_chunks(doc_id,ord,heading_path,text,char_len,is_table) "
        "VALUES(?,?,?,?,?,?)",
        (did, chunk["ord"], chunk["heading_path"], chunk["text"],
         chunk["char_len"], chunk["is_table"]),
    )
    if node_id:
        importer.mount(conn, did, node_id)
    return did


def main():
    print("== 环境 ==")
    conn = db.open_db()
    checks = system.health(conn)
    check("trigram 可用", checks.get("trigram") is True)
    print(f"  python={checks['python']} sqlite={checks['sqlite']}")

    print("== 建表与种子 ==")
    info = seed.seed(conn)
    check("知识树已创建", info["created_nodes"] >= 4, info)
    roots = tree.tree_json(conn)
    check("根节点存在", len(roots) >= 1)
    sig = [r for r in roots if r["name"] == "信号分析与处理"]
    check("信号分析与处理为根", len(sig) == 1)
    kids = [c["name"] for c in sig[0]["children"]] if sig else []
    for k in ("卷积", "傅里叶变换", "常见傅里叶变换的函数"):
        check(f"二级节点 {k}", k in kids, kids)

    conv = [c for c in sig[0]["children"] if c["name"] == "卷积"][0]
    ft = [c for c in sig[0]["children"] if c["name"] == "傅里叶变换"][0]

    print("== 分块 ==")
    blocks = [
        {"kind": "p", "text": "第 1 章 卷积", "level": 1, "style": "Heading 1"},
        {"kind": "p", "text": "卷积的定义是把一个函数翻转平移后相乘积分。", "level": None, "style": ""},
        {"kind": "p", "text": "1.1 卷积定理", "level": 2, "style": "Heading 2"},
        {"kind": "p", "text": "时域卷积对应频域相乘，这就是卷积定理。", "level": None, "style": ""},
    ]
    cs = chunker.chunk_blocks(blocks, "测试文档")
    check("切出 2 块", len(cs) == 2, len(cs))
    check("章节路径带层级", cs[1]["heading_path"].endswith("卷积定理"), cs[1]["heading_path"])

    print("== 导入与挂载 ==")
    d1 = insert_doc(conn, "卷积笔记", "卷积定理告诉我们时域卷积等于频域相乘。卷积在很多地方用到。", conv["id"])
    d2 = insert_doc(conn, "傅里叶变换提纲", "傅里叶变换把时域信号分解成正弦分量，吉布斯现象来自截断。", ft["id"])
    d3 = insert_doc(conn, "未挂载的资料", "这是一份关于抽样定理的笔记，奈奎斯特频率。")
    check("文档入库", conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3)
    check("FTS 已同步", conn.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0] == 3)

    print("== 检索 ==")
    r = search.search(conn, "卷积定理", None, "all")
    check("长词命中(4字)", r["total"] >= 1 and "卷积笔记" in [x["title"] for x in r["results"]],
          r["total"])
    r2 = search.search(conn, "卷积", None, "all")
    check("短词命中(2字,LIKE兜底)", r2["total"] >= 1, r2["total"])
    r3 = search.search(conn, "吉布斯", None, "all")
    check("只命中相关文档", [x["title"] for x in r3["results"]] == ["傅里叶变换提纲"],
          [x["title"] for x in r3["results"]])
    r4 = search.search(conn, "卷积", conv["id"], "self")
    check("范围=本节点", r4["total"] == 1, r4["total"])
    r5 = search.search(conn, "卷积", ft["id"], "self")
    check("范围外不返回", r5["total"] == 0, r5["total"])
    r6 = search.search(conn, "卷积 吉布斯", None, "all")
    check("多词 OR 召回", r6["total"] == 2, r6["total"])
    check("结果带章节路径", bool(r6["results"][0]["heading_path"]))

    print("== 节点范围 ==")
    docs = search.docs_in_scope(conn, sig[0]["id"], "subtree")
    check("含下级=2 份", docs["total"] == 2, docs["total"])
    docs2 = search.docs_in_scope(conn, sig[0]["id"], "self")
    check("本节点=0 份", docs2["total"] == 0, docs2["total"])
    docs3 = search.docs_in_scope(conn, None, "all")
    check("全库=3 份", docs3["total"] == 3, docs3["total"])

    print("== 软删除与恢复 ==")
    def unc():
        row = conn.execute("SELECT id FROM nodes WHERE is_system=1 AND deleted_at IS NULL").fetchone()
        return row["id"] if row else None

    def mounts_of(doc_id):
        return {r[0] for r in conn.execute(
            "SELECT node_id FROM node_documents WHERE document_id=?", (doc_id,))}

    n = tree.delete_node(conn, conv["id"])
    check("删除子树节点数", n == 1, n)

    def root_sig():
        return [r for r in tree.tree_json(conn) if r["name"] == "信号分析与处理"][0]

    check("删除后不再出现在树里",
          "卷积" not in [c["name"] for c in root_sig()["children"]])
    check("文档仍在", conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3)
    check("删除后文档回到未分类", unc() in mounts_of(d1), mounts_of(d1))
    check("挂在其他节点的文档不受影响", mounts_of(d2) == {ft["id"]}, mounts_of(d2))

    row = tree.recent_deletions(conn, 1)
    ids = __import__("json").loads(row[0]["payload"])["ids"]
    tree.restore_nodes(conn, ids)
    check("恢复后回到树里",
          "卷积" in [c["name"] for c in root_sig()["children"]])
    check("恢复后移出未分类", unc() not in mounts_of(d1), mounts_of(d1))

    print("== 同级排序 ==")
    before = [c["name"] for c in root_sig()["children"]]
    ok = tree.reorder(conn, ft["id"], -1)
    after = [c["name"] for c in root_sig()["children"]]
    check("上移生效", ok and after[0] == "傅里叶变换", (before, after))
    tree.reorder(conn, ft["id"], 1)
    check("下移复原", [c["name"] for c in root_sig()["children"]] == before)
    check("越界不移动", tree.reorder(conn, root_sig()["children"][0]["id"], -1) is False)

    print("== 升级 / 降级 / 跨父移动 ==")
    def kids():
        return {c["name"]: c for c in root_sig()["children"]}

    conv_id = kids()["卷积"]["id"]
    ft_id = kids()["傅里叶变换"]["id"]
    cm_id = kids()["常见傅里叶变换的函数"]["id"]

    tree.indent_node(conn, ft_id)
    k = kids()
    check("降级后从父级消失", "傅里叶变换" not in k, list(k))
    check("降级后成为上个兄弟的子节点",
          "傅里叶变换" in [c["name"] for c in k["卷积"]["children"]])
    node_ft = tree.get_node(conn, ft_id)
    check("降级后 path 同步更新",
          node_ft["path"] == k["卷积"]["path"] + f"{ft_id}/", node_ft["path"])
    check("降级后 depth 加一", node_ft["depth"] == 2, node_ft["depth"])

    tree.outdent_node(conn, ft_id)
    check("升级后回到父级", "傅里叶变换" in kids(), list(kids()))
    check("升级后 depth 复原", tree.get_node(conn, ft_id)["depth"] == 1)

    tree.move_node(conn, cm_id, conv_id)
    k = kids()
    check("跨父移动：从顶层消失", "常见傅里叶变换的函数" not in k, list(k))
    check("跨父移动：成为目标子节点",
          "常见傅里叶变换的函数" in [c["name"] for c in k["卷积"]["children"]])

    try:
        tree.move_node(conn, conv_id, cm_id)
        cycle_blocked = False
    except ValueError:
        cycle_blocked = True
    check("禁止移动到自己的子节点下", cycle_blocked)

    try:
        tree.move_node(conn, conv_id, conv_id)
        self_blocked = False
    except ValueError:
        self_blocked = True
    check("禁止移动到自己下面", self_blocked)

    tree.move_node(conn, cm_id, root_sig()["id"])
    check("移回顶层", "常见傅里叶变换的函数" in kids())

    print("== 回收站 ==")
    tmp_id = tree.create_node(conn, "临时节点", root_sig()["id"])
    tree.delete_node(conn, tmp_id)
    items = tree.list_deleted(conn)
    check("回收站里能找到被删节点", any(i["id"] == tmp_id for i in items),
          [i["name"] for i in items])
    restored = tree.restore_node(conn, tmp_id)
    check("恢复返回节点数", restored >= 1, restored)
    check("恢复后出现在树里", "临时节点" in kids(), list(kids()))

    print("== 文档删除 / 恢复 / 彻底删除 ==")
    n_docs = conn.execute("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL").fetchone()[0]
    importer.delete_document(conn, d1)
    check("删除后不在全库", search.docs_in_scope(conn, None, "all")["total"] == n_docs - 1,
          search.docs_in_scope(conn, None, "all")["total"])
    check("文档进了回收站",
          any(i["id"] == d1 for i in importer.list_deleted_documents(conn)))
    importer.restore_document(conn, d1)
    check("恢复后回到全库", search.docs_in_scope(conn, None, "all")["total"] == n_docs)
    importer.delete_document(conn, d1)
    importer.purge_document(conn, d1)
    check("彻底删除后不在回收站",
          all(i["id"] != d1 for i in importer.list_deleted_documents(conn)))

    print("== 备份 ==")
    b = system.backup(conn)
    check("备份文件存在", Path(b["file"]).exists())
    check("备份非空", b["size_kb"] > 0, b)

    conn.close()
    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：{FAILED}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
