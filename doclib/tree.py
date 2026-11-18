# -*- coding: utf-8 -*-
"""节点树：增删改、物化路径维护、作用域求解、软删除。"""
import json
from typing import List, Optional

from .db import now_ms, bump_library_version

UNCATEGORIZED = "未分类"


def _log(conn, op, entity, entity_id, payload=None, inverse=None):
    conn.execute(
        "INSERT INTO op_log(op,entity,entity_id,payload,inverse,created_at) VALUES(?,?,?,?,?,?)",
        (op, entity, entity_id,
         json.dumps(payload or {}, ensure_ascii=False),
         json.dumps(inverse or {}, ensure_ascii=False),
         now_ms()),
    )


def get_node(conn, node_id: int):
    return conn.execute(
        "SELECT * FROM nodes WHERE id=? AND deleted_at IS NULL", (node_id,)
    ).fetchone()


def children(conn, parent_id: Optional[int]):
    if parent_id is None:
        return conn.execute(
            "SELECT * FROM nodes WHERE parent_id IS NULL AND deleted_at IS NULL "
            "ORDER BY is_system ASC, sort_order, id"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM nodes WHERE parent_id=? AND deleted_at IS NULL "
        "ORDER BY is_system ASC, sort_order, id",
        (parent_id,),
    ).fetchall()


def create_node(conn, name: str, parent_id: Optional[int] = None,
                description: str = "", keywords: Optional[List[str]] = None,
                is_system: int = 0) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("节点名不能为空")
    parent = get_node(conn, parent_id) if parent_id else None
    if parent_id and parent is None:
        raise ValueError("父节点不存在")
    depth = (parent["depth"] + 1) if parent else 0
    sort_row = conn.execute(
        "SELECT COALESCE(MAX(sort_order),0)+10 FROM nodes WHERE parent_id IS ?",
        (parent_id,),
    ).fetchone()
    sort_order = sort_row[0] if sort_row else 10
    ts = now_ms()
    cur = conn.execute(
        "INSERT INTO nodes(parent_id,name,description,keywords,sort_order,path,depth,"
        "created_at,updated_at,is_system) VALUES(?,?,?,?,?,'',?,?,?,?)",
        (parent_id, name, description, json.dumps(keywords or [], ensure_ascii=False),
         sort_order, depth, ts, ts, is_system),
    )
    nid = cur.lastrowid
    path = (parent["path"] if parent else "/") + f"{nid}/"
    conn.execute("UPDATE nodes SET path=? WHERE id=?", (path, nid))
    _log(conn, "node.create", "node", nid, {"name": name, "parent_id": parent_id})
    return nid


def ensure_uncategorized(conn) -> int:
    row = conn.execute(
        "SELECT id FROM nodes WHERE is_system=1 AND name=? AND deleted_at IS NULL",
        (UNCATEGORIZED,),
    ).fetchone()
    if row:
        return row["id"]
    return create_node(conn, UNCATEGORIZED, None, "还没挂到任何节点下的资料",
                       ["未分类"], is_system=1)


def rename_node(conn, node_id: int, new_name: str) -> None:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("节点名不能为空")
    row = get_node(conn, node_id)
    if row is None:
        raise ValueError("节点不存在")
    conn.execute("UPDATE nodes SET name=?, updated_at=? WHERE id=?",
                 (new_name, now_ms(), node_id))
    _log(conn, "node.rename", "node", node_id,
         {"from": row["name"], "to": new_name},
         {"op": "node.rename", "node_id": node_id, "name": row["name"]})


def set_keywords(conn, node_id: int, keywords: List[str]) -> None:
    conn.execute("UPDATE nodes SET keywords=?, updated_at=? WHERE id=?",
                 (json.dumps(list(keywords), ensure_ascii=False), now_ms(), node_id))


def get_keywords(row) -> List[str]:
    try:
        v = json.loads(row["keywords"] or "[]")
        return [str(x) for x in v if str(x).strip()]
    except Exception:
        return []


def subtree_rows(conn, node_id: int):
    """含自身在内的整棵子树（未删除）。"""
    node = get_node(conn, node_id)
    if node is None:
        return []
    return conn.execute(
        "SELECT * FROM nodes WHERE path LIKE ? AND deleted_at IS NULL",
        (node["path"] + "%",),
    ).fetchall()


def subtree_ids(conn, node_id: int) -> List[int]:
    return [r["id"] for r in subtree_rows(conn, node_id)]


# ---------------- 科目分区（REV-101） ----------------
# 约定：分区 = parent_id 为空且 is_system=0 的节点（一级节点）。
# 系统节点「未分类」不算分区；二级以下节点归属其一级祖先。
# scope=all 在带 partition_id 时表示「当前分区全范围」；
# 不带 partition_id 时保留旧语义「全库」，供旧调用/测试兼容。


def list_partitions(conn) -> List[dict]:
    counts = doc_counts(conn)
    rows = conn.execute(
        "SELECT id, name, path FROM nodes "
        "WHERE parent_id IS NULL AND is_system=0 AND deleted_at IS NULL "
        "ORDER BY sort_order, id"
    ).fetchall()
    out = []
    seen = set()
    for r in rows:
        seen.add(r["id"])
        ids = node_doc_ids(conn, r["id"], "subtree")
        out.append({
            "id": r["id"], "name": r["name"],
            "doc_count": len(ids or set()),
            "direct_count": counts.get(r["id"], 0),
        })
    # 兜底：没有任何一级节点时，把「未分类」当临时分区（只用于展示）
    if not out:
        unc = conn.execute(
            "SELECT id, name FROM nodes WHERE is_system=1 AND deleted_at IS NULL LIMIT 1"
        ).fetchone()
        if unc:
            out.append({"id": unc["id"], "name": unc["name"],
                        "doc_count": counts.get(unc["id"], 0),
                        "direct_count": counts.get(unc["id"], 0), "is_system": 1})
    return out


def partition_of_node(conn, node_id: Optional[int]):
    """返回节点所属分区（一级非系统节点）id；系统节点/不存在 → None。"""
    node = get_node(conn, node_id) if node_id is not None else None
    if node is None:
        return None
    cur, guard = node, set()
    while cur["parent_id"] is not None and cur["id"] not in guard:
        guard.add(cur["id"])
        parent = get_node(conn, cur["parent_id"])
        if parent is None:
            return None
        cur = parent
    if cur["is_system"]:
        return None
    return cur["id"]


def partition_doc_ids(conn, partition_id: Optional[int]) -> set:
    """分区内全部文档（含下级节点挂载）。partition 非法 → 空集。"""
    if partition_id is None:
        return set()
    root = get_node(conn, partition_id)
    if root is None or root["parent_id"] is not None or root["is_system"]:
        return set()
    rows = conn.execute(
        "SELECT DISTINCT nd.document_id FROM node_documents nd "
        "JOIN nodes n ON n.id = nd.node_id "
        "JOIN documents d ON d.id = nd.document_id "
        "WHERE n.path LIKE ? AND n.deleted_at IS NULL AND d.deleted_at IS NULL",
        (root["path"] + "%",),
    ).fetchall()
    return {r[0] for r in rows}


def _scope_doc_ids(conn, node_id: int, scope: str) -> set:
    node = get_node(conn, node_id)
    if node is None:
        return set()
    if scope == "self":
        rows = conn.execute(
            "SELECT nd.document_id FROM node_documents nd "
            "JOIN documents d ON d.id = nd.document_id "
            "WHERE nd.node_id=? AND d.deleted_at IS NULL", (node_id,)
        ).fetchall()
    else:  # subtree
        rows = conn.execute(
            "SELECT DISTINCT nd.document_id FROM node_documents nd "
            "JOIN nodes n ON n.id = nd.node_id "
            "JOIN documents d ON d.id = nd.document_id "
            "WHERE n.path LIKE ? AND n.deleted_at IS NULL AND d.deleted_at IS NULL",
            (node["path"] + "%",),
        ).fetchall()
    return {r[0] for r in rows}


def node_doc_ids(conn, node_id: Optional[int], scope: str,
                 partition_id: Optional[int] = None) -> Optional[set]:
    """返回范围内 doc_id 集合；None 表示「全库，不加限制」。

    partition_id 不为 None 时：
      · scope=all → 该分区全部文档
      · scope=self/subtree → 节点范围 ∩ 分区
      · node 不属于该分区 → 空集（跨分区默认拒绝）
    partition_id 为 None → 保持旧行为（all=全库）。
    """
    if partition_id is not None:
        part = partition_doc_ids(conn, partition_id)
        if node_id is None:
            return part if scope == "all" else set()
        node = get_node(conn, node_id)
        if node is None:
            return set()
        root = get_node(conn, partition_id)
        if root is None or not node["path"].startswith(root["path"]):
            return set()
        if scope == "all":
            return part
        return _scope_doc_ids(conn, node_id, scope) & part

    if scope == "all" or node_id is None:
        return None
    return _scope_doc_ids(conn, node_id, scope)


def delete_node(conn, node_id: int) -> int:
    """软删除整棵子树，返回影响的节点数。文档与挂载关系保留（挂载随节点恢复）。"""
    node = get_node(conn, node_id)
    if node is None:
        raise ValueError("节点不存在")
    if node["is_system"]:
        raise ValueError("系统节点（未分类）不能删除")
    rows = subtree_rows(conn, node_id)
    ids = [r["id"] for r in rows]
    ts = now_ms()
    qs = ",".join("?" * len(ids))
    conn.execute(f"UPDATE nodes SET deleted_at=?, updated_at=? WHERE id IN ({qs})",
                 [ts, ts, *ids])

    # 删除后，只挂在这些节点上的文档必须回到「未分类」，否则会变成
    # 「全库能搜到、但任何节点都点不到」的孤儿文档。
    orphans = conn.execute(
        f"SELECT DISTINCT nd.document_id FROM node_documents nd "
        f"WHERE nd.node_id IN ({qs}) AND nd.document_id NOT IN ("
        f"  SELECT nd2.document_id FROM node_documents nd2 "
        f"  JOIN nodes n2 ON n2.id = nd2.node_id "
        f"  WHERE n2.deleted_at IS NULL)",
        ids,
    ).fetchall()
    orphan_ids = [r[0] for r in orphans]
    if orphan_ids:
        unc = ensure_uncategorized(conn)
        for did in orphan_ids:
            conn.execute(
                "INSERT INTO node_documents(node_id,document_id,created_at) VALUES(?,?,?) "
                "ON CONFLICT(node_id,document_id) DO NOTHING",
                (unc, did, ts),
            )

    _log(conn, "node.delete", "node", node_id,
         {"ids": ids, "orphans": orphan_ids}, {"op": "node.restore", "ids": ids})
    bump_library_version(conn)
    return len(ids)


def restore_nodes(conn, ids: List[int]) -> None:
    if not ids:
        return
    qs = ",".join("?" * len(ids))
    conn.execute(f"UPDATE nodes SET deleted_at=NULL, updated_at=? WHERE id IN ({qs})",
                 [now_ms(), *ids])
    # 恢复后这些文档已经有正式挂载，从「未分类」移出
    docs = conn.execute(
        f"SELECT DISTINCT nd.document_id FROM node_documents nd WHERE nd.node_id IN ({qs})",
        ids,
    ).fetchall()
    for r in docs:
        conn.execute(
            "DELETE FROM node_documents WHERE document_id=? AND node_id IN "
            "(SELECT id FROM nodes WHERE is_system=1)",
            (r[0],),
        )
    _log(conn, "node.restore", "node", ids[0], {"ids": ids})


def reorder(conn, node_id: int, delta: int) -> bool:
    """同父节点内上移/下移（delta = -1 / +1）。"""
    node = get_node(conn, node_id)
    if node is None or node["is_system"]:
        return False
    sibs = children(conn, node["parent_id"])
    ids = [s["id"] for s in sibs]
    if node_id not in ids:
        return False
    i = ids.index(node_id)
    j = i + delta
    if j < 0 or j >= len(ids):
        return False
    ids[i], ids[j] = ids[j], ids[i]
    ts = now_ms()
    for k, nid in enumerate(ids):
        conn.execute("UPDATE nodes SET sort_order=?, updated_at=? WHERE id=?",
                     ((k + 1) * 10, ts, nid))
    _log(conn, "node.reorder", "node", node_id, {"order": ids})
    return True


def recent_deletions(conn, limit: int = 20):
    return conn.execute(
        "SELECT * FROM op_log WHERE op='node.delete' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def _renumber(conn, parent_id, ts=None):
    """把某个父节点下的兄弟按当前顺序重新编号为 10,20,30…"""
    ts = ts or now_ms()
    rows = children(conn, parent_id)
    for i, r in enumerate(rows):
        conn.execute("UPDATE nodes SET sort_order=?, updated_at=? WHERE id=?",
                     ((i + 1) * 10, ts, r["id"]))


def move_node(conn, node_id: int, new_parent_id=None, before_id=None) -> bool:
    """把节点（连同整棵子树）挂到新的父节点下；before_id 指定插到哪个兄弟之前。

    这是「跨父节点移动 / 拖拽 / 升级 / 降级」共用的唯一底层操作。
    """
    node = get_node(conn, node_id)
    if node is None:
        raise ValueError("节点不存在")
    if node["is_system"]:
        raise ValueError("系统节点不能移动")

    parent = None
    if new_parent_id is not None:
        if new_parent_id == node_id:
            raise ValueError("不能移动到自己下面")
        parent = get_node(conn, new_parent_id)
        if parent is None:
            raise ValueError("目标父节点不存在")
        if parent["is_system"]:
            raise ValueError("不能把节点移动到「未分类」下面")
        if parent["path"].startswith(node["path"]):
            raise ValueError("不能移动到自己或自己的子节点下面")

    old_depth = node["depth"]
    new_depth = 0 if parent is None else parent["depth"] + 1
    parent_path = "/" if parent is None else parent["path"]
    new_path = parent_path + f"{node_id}/"
    delta = new_depth - old_depth
    ts = now_ms()

    # 1) 整棵子树重写 path / depth（一次 SQL 前缀替换）
    rows = conn.execute(
        "SELECT id, path FROM nodes WHERE path LIKE ?", (node["path"] + "%",)
    ).fetchall()
    for r in rows:
        tail = r["path"][len(node["path"]):]
        conn.execute(
            "UPDATE nodes SET path=?, depth=depth+?, updated_at=? WHERE id=?",
            (new_path + tail, delta, ts, r["id"]),
        )

    # 2) 挂到新父节点
    conn.execute("UPDATE nodes SET parent_id=?, updated_at=? WHERE id=?",
                 (new_parent_id, ts, node_id))

    # 3) 重新排兄弟顺序
    ids = [r["id"] for r in children(conn, new_parent_id) if r["id"] != node_id]
    if before_id is not None and before_id in ids:
        ids.insert(ids.index(before_id), node_id)
    else:
        ids.append(node_id)
    for i, nid in enumerate(ids):
        conn.execute("UPDATE nodes SET sort_order=?, updated_at=? WHERE id=?",
                     ((i + 1) * 10, ts, nid))
    if node["parent_id"] != new_parent_id:
        _renumber(conn, node["parent_id"], ts)

    _log(conn, "node.move", "node", node_id,
         {"from": node["parent_id"], "to": new_parent_id, "before": before_id})
    bump_library_version(conn)
    return True


def indent_node(conn, node_id: int) -> bool:
    """降级：变成前一个兄弟节点的子节点。"""
    node = get_node(conn, node_id)
    if node is None or node["is_system"]:
        raise ValueError("该节点不能降级")
    sibs = children(conn, node["parent_id"])
    ids = [s["id"] for s in sibs]
    i = ids.index(node_id)
    if i == 0:
        raise ValueError("前面没有同级节点，无法降级（只能变成上一个兄弟的子节点）")
    return move_node(conn, node_id, ids[i - 1])


def outdent_node(conn, node_id: int) -> bool:
    """升级：变成父节点的同级节点，插在父节点后面。"""
    node = get_node(conn, node_id)
    if node is None or node["is_system"]:
        raise ValueError("该节点不能升级")
    if node["parent_id"] is None:
        raise ValueError("已经是顶层节点，无法继续升级")
    parent = get_node(conn, node["parent_id"])
    gp_id = parent["parent_id"]
    sibs = [r["id"] for r in children(conn, gp_id)]
    idx = sibs.index(parent["id"])
    before = sibs[idx + 1] if idx + 1 < len(sibs) else None
    return move_node(conn, node_id, gp_id, before)


def list_deleted(conn):
    """回收站列表。"""
    rows = conn.execute(
        "SELECT n.id, n.name, n.path, n.deleted_at, n.parent_id, "
        "       (SELECT name FROM nodes p WHERE p.id = n.parent_id) AS parent_name, "
        "       (SELECT COUNT(*) FROM node_documents nd WHERE nd.node_id = n.id) AS doc_count "
        "FROM nodes n WHERE n.deleted_at IS NOT NULL "
        "ORDER BY n.deleted_at DESC, n.id"
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "name": r["name"],
            "path": r["path"],
            "parent_name": r["parent_name"] or "",
            "doc_count": r["doc_count"],
            "deleted_at": r["deleted_at"],
            "depth": r["path"].count("/") - 2,
        })
    return out


def restore_node(conn, node_id: int) -> int:
    """恢复一个被删节点：连同被删的祖先一起恢复，并恢复其整棵子树。"""
    node = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if node is None:
        raise ValueError("节点不存在")
    ids = [node_id]
    # 祖先链上被删的一起恢复，避免出现「父节点不存在」的悬空结构
    cur = node
    while cur["parent_id"] is not None:
        p = conn.execute("SELECT * FROM nodes WHERE id=?", (cur["parent_id"],)).fetchone()
        if p is None:
            break
        if p["deleted_at"] is not None and p["id"] not in ids:
            ids.append(p["id"])
        cur = p
    # 子树
    for r in conn.execute("SELECT id FROM nodes WHERE path LIKE ?",
                          (node["path"] + "%",)).fetchall():
        if r["id"] not in ids:
            ids.append(r["id"])
    restore_nodes(conn, ids)
    bump_library_version(conn)
    return len(ids)


def purge_node(conn, node_id: int) -> int:
    """彻底删除（不可恢复）：只允许删回收站里的节点，连同子树一起物理删除。

    文档本身永远不动；节点上的挂载关系随节点一起消失。
    """
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if row is None:
        raise ValueError("节点不存在")
    if row["deleted_at"] is None:
        raise ValueError("只能彻底删除「回收站」里的节点；正在使用的节点请先删除")
    if row["is_system"]:
        raise ValueError("系统节点（未分类）不能彻底删除")
    cnt = conn.execute("SELECT COUNT(*) FROM nodes WHERE path LIKE ?",
                       (row["path"] + "%",)).fetchone()[0]
    conn.execute("DELETE FROM nodes WHERE path LIKE ?", (row["path"] + "%",))
    _log(conn, "node.purge", "node", node_id, {"name": row["name"], "count": cnt})
    bump_library_version(conn)
    return cnt


def purge_all_deleted(conn) -> int:
    """清空回收站（物理删除所有已删节点）。"""
    cur = conn.execute("DELETE FROM nodes WHERE deleted_at IS NOT NULL AND is_system=0")
    n = cur.rowcount or 0
    _log(conn, "node.purge_all", "node", None, {"count": n})
    bump_library_version(conn)
    return n


def doc_counts(conn):
    rows = conn.execute(
        "SELECT nd.node_id, COUNT(*) AS c FROM node_documents nd "
        "JOIN documents d ON d.id = nd.document_id "
        "WHERE d.deleted_at IS NULL GROUP BY nd.node_id"
    ).fetchall()
    return {r["node_id"]: r["c"] for r in rows}


def tree_json(conn, partition_id: Optional[int] = None) -> List[dict]:
    counts = doc_counts(conn)
    rows = conn.execute(
        "SELECT * FROM nodes WHERE deleted_at IS NULL ORDER BY is_system ASC, sort_order, id"
    ).fetchall()
    nodes = {}
    for r in rows:
        item = {
            "id": r["id"],
            "parent_id": r["parent_id"],
            "name": r["name"],
            "depth": r["depth"],
            "path": r["path"],
            "doc_count": counts.get(r["id"], 0),
            "is_system": r["is_system"],
            "keywords": get_keywords(r),
            "children": [],
            "_sub_count": 0,
        }
        nodes[r["id"]] = item

    roots = []
    for item in nodes.values():
        pid = item["parent_id"]
        if pid is not None and pid in nodes:
            nodes[pid]["children"].append(item)
        else:
            roots.append(item)

    # 子树文档数（用于树上显示「含下级共 N 份」）
    def walk(n, acc):
        total = n["doc_count"]
        for c in n["children"]:
            total += walk(c, acc)
        n["_sub_count"] = total
        return total

    for r in roots:
        walk(r, 0)
    if partition_id is not None:
        only = nodes.get(partition_id)
        return [only] if only is not None else []
    return roots


def create_seed_tree(conn, spec: List[dict]) -> int:
    """spec: [{"name":..., "keywords":[...], "children":[{"name":..,"keywords":[..]}]}]"""
    created = 0
    for root in spec:
        nid = create_node(conn, root["name"], None,
                          root.get("description", ""), root.get("keywords", []))
        created += 1
        for ch in root.get("children", []):
            create_node(conn, ch["name"], nid,
                        ch.get("description", ""), ch.get("keywords", []))
            created += 1
    return created
