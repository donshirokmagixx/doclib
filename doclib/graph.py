# -*- coding: utf-8 -*-
"""v2.0 图谱投影：把真值层（nodes / documents / notes）投影成前端可渲染的实体图。

设计要点（与 docs/v2/ARCHITECTURE.md §5 一致）：

- 只读投影：树层级与文档挂载不复制进 relations，构图时联查
  ``nodes.parent_id`` / ``node_documents``，避免双写不一致。
- 实体 ID 统一为 ``kind:id``（如 ``node:12`` / ``document:34`` / ``note:56``）；
  边 ID 稳定且可去重（见下）。
- 只包含未删除实体；软删除的节点/文档/笔记及其边不会出现。
- 查询按批 ``IN`` 组织，避免 N+1。
- ``scope="global"``：全库或单个一级分区；按度数截断到 ``limit``，
  ``stats.total_nodes`` 记录截断前规模，``truncated`` 明示是否截断。
- ``scope="local"``：从 ``center`` 做无向 BFS（depth 1–3），最多返回 800 个节点；
  center 一定包含在结果中。
- AI 关系（``relations.origin='ai'``）默认隐藏，``rels`` 显式包含 ``"ai"`` 才返回。

边类型：

============  ==========================================  =================
rel           来源                                        方向
============  ==========================================  =================
hierarchy     nodes.parent_id，父节点→子节点              有向
mount         node_documents，节点→文档                   有向
manual        relations(origin=manual 或 import)          无向展示
ai            relations(origin=ai)                        无向展示（默认隐藏）
wikilink      note_links(resolved=1)，笔记→目标实体       有向
============  ==========================================  =================

``relations`` 的 ``origin`` 原样保留在边的 ``origin`` 字段；``rel`` 只做
manual/ai 两类投影，便于前端按类别画线。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

ENTITY_KINDS: Tuple[str, ...] = ("node", "document", "note")
ALL_RELS: Tuple[str, ...] = ("hierarchy", "mount", "manual", "ai", "wikilink")
# 默认不含 ai：AI 推测关系要用户显式打开
DEFAULT_RELS: Tuple[str, ...] = ("hierarchy", "mount", "manual", "wikilink")
DEFAULT_LIMIT = 1500
LOCAL_MAX_NODES = 800
# 局部图发现阶段的硬上限：防止深度 3 + 高扇出在异常数据上无限扩张
LOCAL_DISCOVERY_CAP = 4000
_SQL_CHUNK = 400
_ENTITY_ORDER = {"node": 0, "document": 1, "note": 2}
_REL_ORDER = {name: i for i, name in enumerate(ALL_RELS)}
_ORIGIN_TO_REL = {"manual": "manual", "import": "manual", "ai": "ai"}

Ref = Tuple[str, int]


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _chunks(values: Sequence[int], size: int = _SQL_CHUNK):
    """把 id 列表切成小批，避免超出 SQLite 的变量上限。"""
    vals = list(values)
    for i in range(0, len(vals), size):
        yield vals[i:i + size]


def _marks(count: int) -> str:
    return ",".join("?" * count)


def _ref_key(ref: Ref) -> str:
    return f"{ref[0]}:{ref[1]}"


def _ref_of_key(key: str) -> Ref:
    kind, _, raw = key.partition(":")
    return kind, int(raw)


def _parse_ref(value) -> Optional[Ref]:
    """解析 ``node:12`` / ``document:34`` / ``note:56``；纯数字按 node 处理。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return ("node", value) if value > 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if ":" in text:
        kind, _, raw = text.partition(":")
        kind = kind.strip().lower()
        if kind not in ENTITY_KINDS:
            return None
        try:
            entity_id = int(raw)
        except (TypeError, ValueError):
            return None
        return (kind, entity_id) if entity_id > 0 else None
    try:
        entity_id = int(text)
    except (TypeError, ValueError):
        return None
    return ("node", entity_id) if entity_id > 0 else None


def _parse_filter(value, allowed: Sequence[str], default: Sequence[str]) -> Set[str]:
    """把 ``types`` / ``rels`` 统一成集合；支持逗号字符串或任意可迭代对象。

    - None / 空字符串 / 空集合 → 默认值
    - "all" → 该维度的全部合法值
    - 未知名称忽略（全部未知 → 空集，表示显式过滤掉所有该类）
    """
    if value is None:
        return set(default)
    if isinstance(value, str):
        raw: Iterable = value.split(",")
    else:
        try:
            raw = list(value)
        except TypeError:
            raw = [value]
    items: List[str] = []
    for item in raw:
        text = str(item).strip().lower()
        if text:
            items.append(text)
    if not items:
        return set(default)
    if "all" in items:
        return set(allowed)
    valid = set(allowed)
    return {item for item in items if item in valid}


def _norm_limit(limit) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return value if value > 0 else DEFAULT_LIMIT


def _root_id(path: str) -> Optional[int]:
    """物化路径 ``/1/7/`` 的一级节点 id。"""
    parts = [p for p in str(path or "").strip("/").split("/") if p]
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


def _system_roots(conn, root_ids: Iterable[int]) -> Set[int]:
    """返回其中是系统节点（未分类）的一级 id 集合。"""
    roots = sorted({int(x) for x in root_ids if x is not None})
    out: Set[int] = set()
    for chunk in _chunks(roots):
        rows = conn.execute(
            f"SELECT id, is_system FROM nodes WHERE id IN ({_marks(len(chunk))})",
            chunk,
        ).fetchall()
        out.update(r["id"] for r in rows if r["is_system"])
    return out


def _partition_of_root(root_id: Optional[int], system_roots: Set[int]):
    if root_id is None or root_id in system_roots:
        return None
    return root_id


def _split_refs(refs: Iterable[Ref]):
    node_ids: Set[int] = set()
    doc_ids: Set[int] = set()
    note_ids: Set[int] = set()
    for kind, entity_id in refs:
        if kind == "node":
            node_ids.add(entity_id)
        elif kind == "document":
            doc_ids.add(entity_id)
        elif kind == "note":
            note_ids.add(entity_id)
    return node_ids, doc_ids, note_ids


def _library_is_empty(conn) -> bool:
    """三张真值表都没有未删除实体时视为空库。"""
    for table in ("nodes", "documents", "notes"):
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE deleted_at IS NULL LIMIT 1"
        ).fetchone()
        if row:
            return False
    return True


def _live_refs(conn, refs: Iterable[Ref]) -> Set[Ref]:
    """批量过滤：只保留仍存在且未软删除的实体。"""
    wanted: Dict[str, Set[int]] = {kind: set() for kind in ENTITY_KINDS}
    for kind, entity_id in refs:
        if kind in wanted:
            wanted[kind].add(entity_id)
    tables = {"node": "nodes", "document": "documents", "note": "notes"}
    out: Set[Ref] = set()
    for kind in ENTITY_KINDS:
        ids = sorted(wanted[kind])
        if not ids:
            continue
        for chunk in _chunks(ids):
            rows = conn.execute(
                f"SELECT id FROM {tables[kind]} "
                f"WHERE deleted_at IS NULL AND id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall()
            out.update((kind, r["id"]) for r in rows)
    return out


def _empty_error(scope: str, center, message: str) -> dict:
    return {
        "ok": False,
        "error": message,
        "scope": scope,
        "center": center,
        "truncated": False,
        "stats": {"nodes": 0, "edges": 0, "total_nodes": 0},
        "nodes": [],
        "edges": [],
    }


# ---------------------------------------------------------------------------
# 实体详情（标签 / 分区 / meta）
# ---------------------------------------------------------------------------

def _load_details(conn, refs: Iterable[Ref],
                  forced_document_partition=None) -> Dict[str, Dict[int, dict]]:
    """批量装载实体展示字段与 meta；只取白名单列，不泄露正文/哈希/密钥。

    ``forced_document_partition`` 用于分区图谱：分区范围内的文档统一归属该分区，
    避免多挂载（跨分区）时取到别的一级节点。
    """
    node_ids, doc_ids, note_ids = _split_refs(refs)
    details: Dict[str, Dict[int, dict]] = {"node": {}, "document": {}, "note": {}}

    if node_ids:
        rows: List = []
        for chunk in _chunks(sorted(node_ids)):
            rows.extend(conn.execute(
                "SELECT id, name, path, is_system FROM nodes "
                f"WHERE deleted_at IS NULL AND id IN ({_marks(len(chunk))}) ORDER BY id",
                chunk,
            ).fetchall())
        roots = _system_roots(conn, (_root_id(r["path"]) for r in rows))
        counts: Dict[int, int] = {}
        for chunk in _chunks(sorted(node_ids)):
            for r in conn.execute(
                "SELECT nd.node_id, COUNT(*) AS c FROM node_documents nd "
                "JOIN documents d ON d.id = nd.document_id AND d.deleted_at IS NULL "
                f"WHERE nd.node_id IN ({_marks(len(chunk))}) GROUP BY nd.node_id",
                chunk,
            ).fetchall():
                counts[r["node_id"]] = int(r["c"])
        for row in rows:
            details["node"][row["id"]] = {
                "label": row["name"],
                "path": row["path"],
                "partition_id": _partition_of_root(_root_id(row["path"]), roots),
                "doc_count": counts.get(row["id"], 0),
            }

    if doc_ids:
        rows = []
        for chunk in _chunks(sorted(doc_ids)):
            rows.extend(conn.execute(
                "SELECT id, title, file_type, file_path FROM documents "
                f"WHERE deleted_at IS NULL AND id IN ({_marks(len(chunk))}) ORDER BY id",
                chunk,
            ).fetchall())
        # 文档挂在哪些节点下，用一级祖先决定所属分区（多挂载取最小编号）
        mount_paths: Dict[int, List[str]] = {}
        for chunk in _chunks(sorted(doc_ids)):
            for r in conn.execute(
                "SELECT nd.document_id AS did, n.path AS path FROM node_documents nd "
                "JOIN nodes n ON n.id = nd.node_id AND n.deleted_at IS NULL "
                f"WHERE nd.document_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall():
                mount_paths.setdefault(r["did"], []).append(r["path"])
        all_paths = [p for paths in mount_paths.values() for p in paths]
        roots = _system_roots(conn, (_root_id(p) for p in all_paths))
        for row in rows:
            parts = [
                _partition_of_root(_root_id(p), roots)
                for p in mount_paths.get(row["id"], [])
            ]
            parts = [p for p in parts if p is not None]
            details["document"][row["id"]] = {
                "label": row["title"],
                "file_type": row["file_type"],
                "file_path": row["file_path"],
                "partition_id": (forced_document_partition if forced_document_partition
                                 is not None else (min(parts) if parts else None)),
            }

    if note_ids:
        rows = []
        for chunk in _chunks(sorted(note_ids)):
            rows.extend(conn.execute(
                "SELECT id, title, node_id, partition_id FROM notes "
                f"WHERE deleted_at IS NULL AND id IN ({_marks(len(chunk))}) ORDER BY id",
                chunk,
            ).fetchall())
        # partition_id 缺失时，退回挂载节点的分区（节点可能不在当前子图里）
        need_nodes = {
            r["node_id"] for r in rows
            if r["partition_id"] is None and r["node_id"] is not None
        }
        node_paths: Dict[int, str] = {}
        if need_nodes:
            for chunk in _chunks(sorted(need_nodes)):
                for r in conn.execute(
                    "SELECT id, path FROM nodes "
                    f"WHERE deleted_at IS NULL AND id IN ({_marks(len(chunk))})",
                    chunk,
                ).fetchall():
                    node_paths[r["id"]] = r["path"]
        roots = _system_roots(conn, (_root_id(p) for p in node_paths.values()))
        for row in rows:
            partition_id = row["partition_id"]
            if partition_id is None and row["node_id"] in node_paths:
                partition_id = _partition_of_root(
                    _root_id(node_paths[row["node_id"]]), roots
                )
            details["note"][row["id"]] = {
                "label": row["title"],
                "node_id": row["node_id"],
                "partition_id": partition_id,
            }

    return details


def _details_refs(details: Dict[str, Dict[int, dict]]) -> Set[Ref]:
    return {
        (kind, entity_id)
        for kind, items in details.items()
        for entity_id in items
    }


def _label_of(details: Dict[str, Dict[int, dict]], ref: Ref) -> str:
    item = details.get(ref[0], {}).get(ref[1]) or {}
    return str(item.get("label") or "")


def _matches_q(details: Dict[str, Dict[int, dict]], ref: Ref, q: str) -> bool:
    return q in _label_of(details, ref).lower()


# ---------------------------------------------------------------------------
# 边投影
# ---------------------------------------------------------------------------

def _collect_edges(conn, refs: Set[Ref], rels: Set[str]) -> List[dict]:
    """收集由 refs 诱导出的全部边（两端都必须在 refs 内）。

    所有查询都用批量 IN；返回的边按 id 去重，且保证不会出现悬空端点。
    """
    node_ids, doc_ids, note_ids = _split_refs(refs)
    edges: List[dict] = []

    # hierarchy：父节点 → 子节点
    if "hierarchy" in rels and node_ids:
        for chunk in _chunks(sorted(node_ids)):
            rows = conn.execute(
                "SELECT id, parent_id FROM nodes "
                f"WHERE deleted_at IS NULL AND id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall()
            for row in rows:
                parent_id = row["parent_id"]
                if parent_id is not None and parent_id in node_ids:
                    edges.append({
                        "id": f"e:hierarchy:{parent_id}:{row['id']}",
                        "source": _ref_key(("node", parent_id)),
                        "target": _ref_key(("node", row["id"])),
                        "rel": "hierarchy",
                        "origin": "system",
                        "weight": 1.0,
                        "directed": True,
                    })

    # mount：节点 → 文档（node_documents 有主键，天然不会重复）
    if "mount" in rels and node_ids and doc_ids:
        for chunk in _chunks(sorted(node_ids)):
            rows = conn.execute(
                "SELECT node_id, document_id, weight FROM node_documents "
                f"WHERE node_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall()
            for row in rows:
                if row["document_id"] not in doc_ids:
                    continue
                edges.append({
                    "id": f"e:mount:{row['node_id']}:{row['document_id']}",
                    "source": _ref_key(("node", row["node_id"])),
                    "target": _ref_key(("document", row["document_id"])),
                    "rel": "mount",
                    "origin": "system",
                    "weight": float(row["weight"]),
                    "directed": True,
                })

    # relations：按 origin 投影为 manual / ai；origin 原样保留
    if "manual" in rels or "ai" in rels:
        for kind in ENTITY_KINDS:
            ids = sorted(entity_id for k, entity_id in refs if k == kind)
            for chunk in _chunks(ids):
                rows = conn.execute(
                    "SELECT id, src_kind, src_id, dst_kind, dst_id, origin, confidence "
                    "FROM relations WHERE deleted_at IS NULL "
                    f"AND src_kind=? AND src_id IN ({_marks(len(chunk))})",
                    [kind, *chunk],
                ).fetchall()
                for row in rows:
                    rel = _ORIGIN_TO_REL.get(row["origin"])
                    if rel is None or rel not in rels:
                        continue
                    target = (row["dst_kind"], row["dst_id"])
                    if target not in refs:
                        continue
                    edges.append({
                        "id": f"e:rel:{row['id']}",
                        "source": _ref_key((row["src_kind"], row["src_id"])),
                        "target": _ref_key(target),
                        "rel": rel,
                        "origin": row["origin"],
                        "weight": float(row["confidence"]),
                        "directed": False,
                    })

    # wikilink：笔记 → 目标；同一对 note/target 多次提及只保留一条边
    if "wikilink" in rels and note_ids:
        best: Dict[Tuple[int, str, int], int] = {}
        for chunk in _chunks(sorted(note_ids)):
            rows = conn.execute(
                "SELECT id, note_id, target_kind, target_id FROM note_links "
                f"WHERE resolved=1 AND note_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall()
            for row in rows:
                kind = row["target_kind"]
                if kind not in ENTITY_KINDS or row["target_id"] is None:
                    continue
                target = (kind, int(row["target_id"]))
                if target not in refs:
                    continue
                pair = (int(row["note_id"]), kind, int(row["target_id"]))
                if pair not in best or row["id"] < best[pair]:
                    best[pair] = int(row["id"])
        for (note_id, kind, target_id), link_id in sorted(best.items()):
            edges.append({
                "id": f"e:wikilink:{link_id}",
                "source": _ref_key(("note", note_id)),
                "target": _ref_key((kind, target_id)),
                "rel": "wikilink",
                "origin": "wikilink",
                "weight": 1.0,
                "directed": True,
            })

    # 稳定排序：先按关系类别，再按 id
    edges.sort(key=lambda e: (_REL_ORDER.get(e["rel"], 99), e["id"]))
    return edges


def _degree_map(refs: Set[Ref], edges: Sequence[dict]) -> Dict[Ref, int]:
    degrees: Dict[Ref, int] = {ref: 0 for ref in refs}
    for edge in edges:
        source = _ref_of_key(edge["source"])
        target = _ref_of_key(edge["target"])
        if source in degrees:
            degrees[source] += 1
        if target in degrees:
            degrees[target] += 1
    return degrees


def _truncate(refs: Set[Ref], edges: List[dict], degrees: Dict[Ref, int],
              limit: int, center: Optional[Ref] = None):
    """按度数保留前 limit 个节点，再重算保留子图的边与度数。

    center（局部图）永远保留。返回 (kept, edges, degrees, truncated, total)。
    """
    total = len(refs)
    if total <= limit:
        return refs, edges, degrees, False, total

    def rank(ref: Ref):
        return (
            0 if ref == center else 1,
            -degrees.get(ref, 0),
            _ENTITY_ORDER.get(ref[0], 9),
            ref[1],
        )

    kept = set(sorted(refs, key=rank)[:limit])
    kept_edges = [
        edge for edge in edges
        if _ref_of_key(edge["source"]) in kept
        and _ref_of_key(edge["target"]) in kept
    ]
    return kept, kept_edges, _degree_map(kept, kept_edges), True, total


def _node_payload(ref: Ref, details: Dict[str, Dict[int, dict]],
                  degrees: Dict[Ref, int]) -> dict:
    kind, entity_id = ref
    item = details[kind][entity_id]
    if kind == "node":
        partition_id = item["partition_id"]
        meta = {"path": item["path"], "doc_count": item["doc_count"]}
    elif kind == "document":
        partition_id = item["partition_id"]
        meta = {"file_type": item["file_type"], "file_path": item["file_path"]}
    else:
        partition_id = item["partition_id"]
        meta = {"node_id": item["node_id"], "partition_id": item["partition_id"]}
    return {
        "id": _ref_key(ref),
        "kind": kind,
        "entity_id": entity_id,
        "label": item["label"],
        "partition_id": partition_id,
        "degree": degrees.get(ref, 0),
        "meta": meta,
    }


def _render(scope: str, center: Optional[Ref], refs: Set[Ref],
            edges: List[dict], degrees: Dict[Ref, int], truncated: bool,
            total_nodes: int, details: Dict[str, Dict[int, dict]]) -> dict:
    nodes = [
        _node_payload(ref, details, degrees)
        for ref in sorted(refs, key=lambda r: (_ENTITY_ORDER.get(r[0], 9), r[1]))
        if ref[0] in details and ref[1] in details[ref[0]]
    ]
    return {
        "ok": True,
        "scope": scope,
        "center": _ref_key(center) if center else None,
        "truncated": bool(truncated),
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "total_nodes": int(total_nodes),
        },
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# global / partition
# ---------------------------------------------------------------------------

def _get_partition(conn, partition_id):
    """校验分区：必须是存在、未删除、非系统的一级节点。"""
    if partition_id is None or partition_id == "":
        raise ValueError("分区范围需要 partition_id")
    try:
        pid = int(partition_id)
    except (TypeError, ValueError):
        raise ValueError(f"分区 ID 无效：{partition_id!r}")
    row = conn.execute(
        "SELECT id, name, path, parent_id, is_system FROM nodes "
        "WHERE id=? AND deleted_at IS NULL",
        (pid,),
    ).fetchone()
    if row is None:
        raise ValueError(f"分区不存在或已删除：{pid}")
    if row["parent_id"] is not None:
        raise ValueError(f"节点 {pid} 不是一级分区")
    if row["is_system"]:
        raise ValueError(f"系统节点「{row['name']}」不能作为分区")
    return row


def _scope_refs(conn, partition) -> Set[Ref]:
    """按全库或一级分区子树取实体 ID 集合（不装载详情）。"""
    refs: Set[Ref] = set()
    if partition is not None:
        pattern = partition["path"] + "%"
        for row in conn.execute(
            "SELECT id FROM nodes WHERE deleted_at IS NULL AND path LIKE ?", (pattern,)
        ).fetchall():
            refs.add(("node", row["id"]))
        for row in conn.execute(
            "SELECT DISTINCT nd.document_id FROM node_documents nd "
            "JOIN nodes n ON n.id = nd.node_id "
            "JOIN documents d ON d.id = nd.document_id AND d.deleted_at IS NULL "
            "WHERE n.deleted_at IS NULL AND n.path LIKE ?",
            (pattern,),
        ).fetchall():
            refs.add(("document", row["document_id"]))
        for row in conn.execute(
            "SELECT id FROM notes WHERE deleted_at IS NULL AND ("
            "  partition_id=? OR (partition_id IS NULL AND node_id IN ("
            "    SELECT id FROM nodes WHERE deleted_at IS NULL AND path LIKE ?)))",
            (partition["id"], pattern),
        ).fetchall():
            refs.add(("note", row["id"]))
    else:
        for row in conn.execute(
            "SELECT id FROM nodes WHERE deleted_at IS NULL"
        ).fetchall():
            refs.add(("node", row["id"]))
        for row in conn.execute(
            "SELECT id FROM documents WHERE deleted_at IS NULL"
        ).fetchall():
            refs.add(("document", row["id"]))
        for row in conn.execute(
            "SELECT id FROM notes WHERE deleted_at IS NULL"
        ).fetchall():
            refs.add(("note", row["id"]))
    return refs


def _build_global(conn, scope: str, partition_id, types: Set[str],
                  rels: Set[str], q: str, limit: int) -> dict:
    partition = _get_partition(conn, partition_id) if partition_id is not None else None
    if _library_is_empty(conn):
        return _empty_error(scope, None, "知识库为空：还没有可显示的节点、资料或笔记")

    refs = {ref for ref in _scope_refs(conn, partition) if ref[0] in types}
    details = _load_details(
        conn, refs,
        forced_document_partition=partition["id"] if partition is not None else None,
    )
    refs &= _details_refs(details)
    if q:
        refs = {ref for ref in refs if _matches_q(details, ref, q)}

    edges = _collect_edges(conn, refs, rels)
    degrees = _degree_map(refs, edges)
    kept, edges, degrees, truncated, total = _truncate(
        refs, edges, degrees, _norm_limit(limit)
    )
    return _render(scope, None, kept, edges, degrees, truncated, total, details)


# ---------------------------------------------------------------------------
# local（BFS）
# ---------------------------------------------------------------------------

def _neighbors(conn, frontier: Set[Ref], rels: Set[str]) -> Set[Ref]:
    """一层邻居（不校验存活，由调用方批量过滤）；边按 rels 限制，双向遍历。"""
    node_ids, doc_ids, note_ids = _split_refs(frontier)
    found: Set[Ref] = set()

    if "hierarchy" in rels and node_ids:
        for chunk in _chunks(sorted(node_ids)):
            # 子节点
            for row in conn.execute(
                "SELECT id FROM nodes WHERE deleted_at IS NULL "
                f"AND parent_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall():
                found.add(("node", row["id"]))
            # 父节点
            for row in conn.execute(
                "SELECT p.id AS pid FROM nodes n "
                "JOIN nodes p ON p.id = n.parent_id AND p.deleted_at IS NULL "
                f"WHERE n.deleted_at IS NULL AND n.id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall():
                found.add(("node", row["pid"]))

    if "mount" in rels:
        for chunk in _chunks(sorted(node_ids)):
            for row in conn.execute(
                "SELECT nd.document_id AS did FROM node_documents nd "
                "JOIN documents d ON d.id = nd.document_id AND d.deleted_at IS NULL "
                f"WHERE nd.node_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall():
                found.add(("document", row["did"]))
        for chunk in _chunks(sorted(doc_ids)):
            for row in conn.execute(
                "SELECT nd.node_id AS nid FROM node_documents nd "
                "JOIN nodes n ON n.id = nd.node_id AND n.deleted_at IS NULL "
                f"WHERE nd.document_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall():
                found.add(("node", row["nid"]))

    wanted_origins = [
        origin for origin, rel in _ORIGIN_TO_REL.items() if rel in rels
    ]
    if wanted_origins:
        placeholders = _marks(len(wanted_origins))
        for kind in ENTITY_KINDS:
            ids = sorted(entity_id for k, entity_id in frontier if k == kind)
            for chunk in _chunks(ids):
                # 当前节点是源：带出目标
                for row in conn.execute(
                    "SELECT dst_kind, dst_id, origin FROM relations "
                    f"WHERE deleted_at IS NULL AND src_kind=? "
                    f"AND src_id IN ({_marks(len(chunk))}) "
                    f"AND origin IN ({placeholders})",
                    [kind, *chunk, *wanted_origins],
                ).fetchall():
                    if row["dst_kind"] in ENTITY_KINDS:
                        found.add((row["dst_kind"], int(row["dst_id"])))
                # 当前节点是目标：带出来源（关系按无向遍历）
                for row in conn.execute(
                    "SELECT src_kind, src_id, origin FROM relations "
                    f"WHERE deleted_at IS NULL AND dst_kind=? "
                    f"AND dst_id IN ({_marks(len(chunk))}) "
                    f"AND origin IN ({placeholders})",
                    [kind, *chunk, *wanted_origins],
                ).fetchall():
                    if row["src_kind"] in ENTITY_KINDS:
                        found.add((row["src_kind"], int(row["src_id"])))

    if "wikilink" in rels:
        # 出链：当前笔记 → 目标
        for chunk in _chunks(sorted(note_ids)):
            for row in conn.execute(
                "SELECT target_kind, target_id FROM note_links "
                f"WHERE resolved=1 AND note_id IN ({_marks(len(chunk))})",
                chunk,
            ).fetchall():
                if row["target_kind"] in ENTITY_KINDS and row["target_id"] is not None:
                    found.add((row["target_kind"], int(row["target_id"])))
        # 反链：别的笔记指向当前笔记/节点/文档
        for kind in ENTITY_KINDS:
            ids = sorted(entity_id for k, entity_id in frontier if k == kind)
            for chunk in _chunks(ids):
                for row in conn.execute(
                    "SELECT note_id FROM note_links WHERE resolved=1 "
                    f"AND target_kind=? AND target_id IN ({_marks(len(chunk))})",
                    [kind, *chunk],
                ).fetchall():
                    found.add(("note", row["note_id"]))

    return found


def _build_local(conn, scope: str, center, depth, types: Set[str],
                 rels: Set[str], q: str, limit: int) -> dict:
    center_ref = _parse_ref(center)
    if center_ref is None:
        return _empty_error(
            scope, center,
            "center 无效，应为 node:12 / document:34 / note:56",
        )
    if not _live_refs(conn, {center_ref}):
        return _empty_error(scope, _ref_key(center_ref), "中心实体不存在或已删除")

    try:
        hops = int(depth)
    except (TypeError, ValueError):
        hops = 1
    hops = max(1, min(3, hops))

    visited: Set[Ref] = {center_ref}
    frontier: Set[Ref] = {center_ref}
    discovery_truncated = False
    for _ in range(hops):
        if not frontier:
            break
        candidates = _neighbors(conn, frontier, rels)
        candidates = {
            ref for ref in candidates
            if ref not in visited and ref[0] in types
        }
        if candidates:
            candidates &= _live_refs(conn, candidates)
        next_frontier: Set[Ref] = set()
        for ref in sorted(candidates, key=lambda r: (_ENTITY_ORDER.get(r[0], 9), r[1])):
            if len(visited) >= LOCAL_DISCOVERY_CAP:
                discovery_truncated = True
                break
            visited.add(ref)
            next_frontier.add(ref)
        frontier = next_frontier
        if discovery_truncated:
            break

    refs = visited
    details = _load_details(conn, refs)
    refs = {ref for ref in refs if ref in _details_refs(details)}
    if q:
        # center 始终保留；其余实体按 label 子串过滤
        refs = {
            ref for ref in refs
            if ref == center_ref or _matches_q(details, ref, q)
        }

    edges = _collect_edges(conn, refs, rels)
    degrees = _degree_map(refs, edges)
    cap = min(_norm_limit(limit), LOCAL_MAX_NODES)
    kept, edges, degrees, truncated, total = _truncate(
        refs, edges, degrees, cap, center=center_ref
    )
    return _render(
        scope, center_ref, kept, edges, degrees,
        truncated or discovery_truncated, total, details,
    )


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def build_graph(conn, scope: str = "global", partition_id=None, center=None,
                depth: int = 1, types=None, rels=None, q: str = "",
                limit: int = DEFAULT_LIMIT) -> dict:
    """构建图谱投影，返回给前端/API 的纯 JSON 字典。

    参数：
        conn          sqlite3 连接（``row_factory=sqlite3.Row``，由 db.open_db 建立）
        scope         ``global``（全库/分区）或 ``local``（中心局部图）；
                      ``partition`` 作为 global 的别名（需 partition_id）
        partition_id  一级分区节点 id；global 下只投影该分区子树、其文档与该分区笔记
        center        局部图中心：``node:12`` / ``document:34`` / ``note:56``，
                      也接受纯数字（按 node 处理）
        depth         局部图跳数，自动收敛到 1–3
        types         实体类型过滤，逗号字符串或集合（node,document,note）
        rels          边类型过滤，逗号字符串或集合；默认不含 ai
        q             label 子串过滤，不区分大小写
        limit         全局图节点上限（默认 1500）；局部图再受 800 硬上限约束

    返回：
        {"ok", "scope", "center", "truncated", "stats", "nodes", "edges"}

    出错（分区不存在、中心不存在、空库等）返回 ``ok=False`` 与 ``error``，
    不抛异常，便于 HTTP 层直接序列化。
    """
    scope_text = str(scope or "global").strip().lower()
    allowed_types = _parse_filter(types, ENTITY_KINDS, ENTITY_KINDS)
    allowed_rels = _parse_filter(rels, ALL_RELS, DEFAULT_RELS)
    query = str(q or "").strip().lower()

    try:
        if scope_text == "local":
            return _build_local(
                conn, scope_text, center, depth, allowed_types,
                allowed_rels, query, limit,
            )
        if scope_text in ("global", "partition"):
            if scope_text == "partition" and partition_id is None:
                return _empty_error(scope_text, None, "分区范围需要 partition_id")
            return _build_global(
                conn, scope_text, partition_id, allowed_types,
                allowed_rels, query, limit,
            )
        return _empty_error(
            scope_text, center, "scope 只能是 global / partition / local"
        )
    except ValueError as exc:
        # 参数校验类错误：按 API 约定转成 ok=False，而不是 500
        return _empty_error(scope_text, center, str(exc))
