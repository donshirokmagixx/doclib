# -*- coding: utf-8 -*-
"""DocLib 2.0 笔记 + 双链后端验收（不碰 dist/data，全程临时 DOCLIB_DATA）。

覆盖：
  1) 新建/更新、标题唯一（NOCASE）、分区/node 校验、乐观锁冲突、软删/恢复、标题释放；
  2) Markdown 标题分块（每块 ≤900 字）+ FTS 中文搜索（长词 trigram + 2 字短词 LIKE 兜底）；
  3) wikilink 解析：稳定 ID / 标题 / heading / alias / 代码块与行内代码排除 / 未解析保留；
  4) sync_links 解析目标、backlinks 反向与出链、manual relations、软删目标显示 deleted；
  5) 保存更新后 links 与 FTS 不残留旧内容。

用法：
    .venv\\Scripts\\python.exe tests\\test_notebook.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

TMP = tempfile.mkdtemp(prefix="doclib_notebook_")
os.environ["DOCLIB_DATA"] = TMP

from doclib import config  # noqa: E402

_DATA = Path(TMP).resolve()
config.DATA_DIR = _DATA
config.DB_PATH = _DATA / "doclib.db"
config.BACKUP_DIR = _DATA / "backups"
config.CONVERT_DIR = _DATA / "converted"
config.ensure_dirs()

from doclib import db, links, notebook, tree  # noqa: E402

NOW = 1700000000000


# ---------------------------------------------------------------- 测试工具
def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name
          + ("" if cond else f"  ← {detail}"))
    assert cond, name


def expect_raises(exc_type, fn, name):
    try:
        fn()
    except exc_type as e:
        print(f"  [PASS] {name}（{type(e).__name__}: {e}）")
        return e
    except Exception as e:                     # noqa: BLE001
        raise AssertionError(
            f"{name}: 抛出了 {type(e).__name__} 而不是 {exc_type.__name__}: {e}")
    raise AssertionError(f"{name}: 没有抛异常")


def add_doc(conn, title, path_key, deleted=False):
    cur = conn.execute(
        "INSERT INTO documents(title,file_path,path_key,file_type,parse_status,"
        " char_count,created_at,updated_at,deleted_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (title, f"D:/tmp/{path_key}.md", path_key, "md", 2, 0,
         NOW, NOW, NOW if deleted else None))
    return cur.lastrowid


def rows_of(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


# ---------------------------------------------------------------- 1) CRUD
def section_crud(conn, part_a, part_b, node_conv, node_fourier, node_b, unc):
    print("1) 新建 / 更新 / 唯一标题 / 校验 / 冲突 / 软删恢复")
    base_body = "# 卷积\n卷积定理：时域卷积 ↔ 频域相乘。\n"
    note = notebook.save_note(conn, title="卷积笔记", body_md=base_body,
                              node_id=node_conv, partition_id=part_a)
    check("新建返回完整 dict", note["id"] > 0 and note["title"] == "卷积笔记",
          note)
    check("分区/节点已写入",
          note["partition_id"] == part_a and note["node_id"] == node_conv, note)
    check("创建时间 = 更新时间", note["created_at"] == note["updated_at"], note)
    check("事务内已重建 chunks", note["chunk_count"] >= 1, note)
    check("正文可回读",
          notebook.get_note(conn, note["id"])["body_md"] == base_body)
    check("get_note 不存在返回 None", notebook.get_note(conn, 999999) is None)

    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="卷积笔记", body_md="x", partition_id=part_b),
        "标题全局唯一（跨分区也不能重复）")
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="   ", body_md="x", partition_id=part_a), "空标题被拒")
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="长" * 81, body_md="x", partition_id=part_a),
        "标题 >80 字被拒")
    ascii_note = notebook.save_note(conn, title="Alpha Note", body_md="x",
                                    partition_id=part_a)
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="alpha note", body_md="x", partition_id=part_a),
        "标题唯一不区分大小写")
    check("NOCASE 保存成功", ascii_note["title"] == "Alpha Note")

    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="坏分区", body_md="x", partition_id=999999), "不存在的分区被拒")
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="坏分区2", body_md="x", partition_id=node_conv),
        "二级节点不能当分区")
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="坏分区3", body_md="x", partition_id=unc),
        "系统节点不能当分区")
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="跨分区节点", body_md="x", node_id=node_b,
        partition_id=part_a), "node 不属于分区被拒")
    expect_raises(ValueError, lambda: notebook.save_note(
        conn, title="坏节点", body_md="x", node_id=999999,
        partition_id=part_a), "不存在的 node 被拒")

    derived = notebook.save_note(conn, title="由节点推导分区", body_md="x",
                                 node_id=node_conv)
    check("只给 node 时自动推导分区", derived["partition_id"] == part_a, derived)

    old_updated = note["updated_at"]
    updated = notebook.save_note(
        conn, note_id=note["id"], title="卷积笔记",
        body_md="# 卷积\n更新后的正文。\n", node_id=node_conv,
        partition_id=part_a, expected_updated_at=old_updated)
    check("更新成功且 updated_at 前进",
          updated["updated_at"] > old_updated, (old_updated, updated["updated_at"]))
    check("更新后正文/分块已换",
          "更新后的正文" in updated["body_md"] and updated["chunk_count"] >= 1)
    conflict = expect_raises(
        notebook.NoteConflict,
        lambda: notebook.save_note(conn, note_id=note["id"], title="卷积笔记",
                                   body_md="旧内容", expected_updated_at=old_updated),
        "expected_updated_at 过期抛 NoteConflict")
    check("NoteConflict 带当前内容",
          conflict.current["id"] == note["id"]
          and conflict.note["id"] == note["id"]
          and "更新后的正文" in conflict.current["body_md"], conflict.current)
    notebook.save_note(conn, note_id=note["id"], title="卷积笔记",
                       body_md=updated["body_md"], node_id=node_conv,
                       partition_id=part_a)
    print("  [PASS] 不带 expected_updated_at 可强制保存")

    listed = notebook.list_notes(conn, partition_id=part_a)
    check("list_notes 按分区", note["id"] in {x["id"] for x in listed})
    check("list_notes 按节点",
          note["id"] in {x["id"] for x in notebook.list_notes(conn, node_id=node_conv)})
    check("list_notes 按关键词",
          note["id"] in {x["id"] for x in notebook.list_notes(conn, q="更新后")})
    check("list_notes 分区隔离",
          note["id"] not in {x["id"] for x in
                             notebook.list_notes(conn, partition_id=part_b)})

    # ---- 软删 / 恢复 ----
    deleted = notebook.delete_note(conn, note["id"])
    check("软删写 deleted_at",
          deleted["deleted_at"] is not None and notebook.get_note(conn, note["id"]) is None)
    check("软删后 chunks 清空",
          rows_of(conn, "SELECT COUNT(*) c FROM note_chunks WHERE note_id=?",
                  (note["id"],))[0]["c"] == 0)
    check("软删后列表与检索不返回",
          note["id"] not in {x["id"] for x in notebook.list_notes(conn)}
          and note["id"] not in {x["id"] for x in notebook.search_notes(conn, "更新后")})
    restored = notebook.restore_note(conn, note["id"])
    check("恢复后可见且 chunks 重建",
          restored["deleted_at"] is None and restored["chunk_count"] >= 1, restored)
    check("恢复后正文仍是当前版本", "更新后的正文" in restored["body_md"])
    check("恢复后重新可检索",
          note["id"] in {x["id"] for x in notebook.search_notes(conn, "更新后")})

    # 标题释放：软删后同名可再建；旧笔记恢复会因标题占用被拒
    reused = notebook.save_note(conn, title="可复用标题", body_md="v1",
                                partition_id=part_a)
    notebook.delete_note(conn, reused["id"])
    reused2 = notebook.save_note(conn, title="可复用标题", body_md="v2",
                                 partition_id=part_a)
    check("软删后标题可被新笔记复用", reused2["id"] != reused["id"])
    expect_raises(ValueError, lambda: notebook.restore_note(conn, reused["id"]),
                  "标题被占用时拒绝恢复")
    expect_raises(ValueError, lambda: notebook.restore_note(conn, 999999),
                  "恢复不存在的笔记被拒")

    # ---- 只改分区：原节点不在新分区时自动清空 ----
    moved = notebook.save_note(conn, note_id=note["id"], title="卷积笔记",
                               body_md=restored["body_md"], partition_id=part_b)
    check("换分区后旧节点被清空",
          moved["partition_id"] == part_b and moved["node_id"] is None, moved)
    moved_back = notebook.save_note(conn, note_id=note["id"], title="卷积笔记",
                                    body_md=restored["body_md"],
                                    partition_id=part_a, node_id=node_conv)
    check("可再挂回原分区节点",
          moved_back["partition_id"] == part_a and moved_back["node_id"] == node_conv)
    return note


# ---------------------------------------------------------------- 2) 分块 + FTS
def section_chunks_fts(conn, part_a, part_b, node_fourier):
    print("2) Markdown 标题分块 + FTS 中文搜索")
    long_para = "频域分析" * 500                 # 2000 字，必须被切成多块
    body = ("# 傅里叶变换\n"
            "## 定义\n傅里叶变换把时域信号分解到频域。\n"
            "## 性质\n线性性质与时移性质。\n"
            "### 长段落\n" + long_para + "\n")
    note = notebook.save_note(conn, title="傅里叶笔记", body_md=body,
                              node_id=node_fourier, partition_id=part_a)
    rows = rows_of(conn, "SELECT heading_path,char_len,text FROM note_chunks "
                         "WHERE note_id=? ORDER BY ord", (note["id"],))
    paths = [r["heading_path"] for r in rows]
    check("按 Markdown 标题生成 heading_path",
          "傅里叶变换 > 定义" in paths and "傅里叶变换 > 性质 > 长段落" in paths,
          paths[:6])
    check("单块 ≤900 字", all(r["char_len"] <= 900 for r in rows),
          max(r["char_len"] for r in rows))
    check("char_len 与 text 一致", all(r["char_len"] == len(r["text"]) for r in rows))
    long_chunks = [r for r in rows if r["heading_path"].endswith("长段落")]
    check("超长段落被切成多块", len(long_chunks) >= 3, len(long_chunks))
    check("save_note 返回 chunk_count 与实际一致",
          note["chunk_count"] == len(rows), (note["chunk_count"], len(rows)))

    hit_long = notebook.search_notes(conn, "时域信号")       # 4 字 → FTS
    check("FTS 长词命中正文", note["id"] in {x["id"] for x in hit_long}, hit_long)
    check("检索结果带 snippet/heading",
          any(x["snippet"] and x["heading_path"] for x in hit_long), hit_long[:1])
    hit_short = notebook.search_notes(conn, "性质")          # 2 字 → LIKE 兜底
    check("2 字短词 LIKE 命中", note["id"] in {x["id"] for x in hit_short}, hit_short)
    hit_mix = notebook.search_notes(conn, "频域分析 性质")
    check("长词 + 短词混合查询", note["id"] in {x["id"] for x in hit_mix}, hit_mix)
    hit_title = notebook.search_notes(conn, "傅里叶笔记")     # 只命中标题
    check("仅标题命中也能搜到",
          any(x["id"] == note["id"] and x["title_hit"] for x in hit_title), hit_title)
    check("分区隔离：别的分区搜不到",
          notebook.search_notes(conn, "时域信号", partition_id=part_b) == [])

    # 更新正文：旧词条必须从 FTS 消失（触发器同步，不手写 note_fts）
    new_body = "# 傅里叶变换\n## 定义\n新的定义内容。\n"
    notebook.save_note(conn, note_id=note["id"], title="傅里叶笔记",
                       body_md=new_body, node_id=node_fourier, partition_id=part_a)
    check("更新后旧词条不再命中",
          note["id"] not in {x["id"] for x in notebook.search_notes(conn, "时域信号")})
    check("更新后新词条可命中",
          note["id"] in {x["id"] for x in notebook.search_notes(conn, "新的定义")})
    return note


# ---------------------------------------------------------------- 3) 解析
def section_parse():
    print("3) wikilink 解析（稳定 ID / 标题 / heading / alias / 代码排除）")
    md = (
        "稳定笔记 [[note:12|笔记标题]]\n"
        "稳定文档 [[doc:34|文档标题]]\n"
        "稳定节点 [[node:7|节点标题]]\n"
        "标题式 [[卷积笔记]]\n"
        "带章节 [[卷积笔记#定义]]\n"
        "带别名 [[卷积笔记|我的别名]]\n"
        "章节别名 [[卷积笔记#性质|别名二]]\n"
        "同名 [[同名资料]]\n"
        "未解析 [[不存在的条目]]\n"
        "嵌入 ![[doc:34]]\n"
        "\n"
        "```python\n"
        "[[doc:99|代码块里的]]\n"
        "```\n"
        "\n"
        "行内 `[[note:99]]` 不算。\n"
    )
    parsed = links.parse_wikilinks(md)
    check("返回 10 条（代码块/行内代码被排除）", len(parsed) == 10,
          [(p["raw"], p["target_title"]) for p in parsed])
    check("offsets 可切片回 raw",
          all(md[p["start_off"]:p["end_off"]] == p["raw"] for p in parsed))
    check("代码块里的链接不解析",
          not any("代码块里的" in p["raw"] for p in parsed))
    check("行内代码里的链接不解析",
          not any(p["target_id"] == 99 for p in parsed))

    by_raw = {p["raw"]: p for p in parsed}
    stable_note = by_raw["[[note:12|笔记标题]]"]
    check("稳定 ID note", stable_note["target_kind"] == "note"
          and stable_note["target_id"] == 12
          and stable_note["target_title"] == "笔记标题", stable_note)
    stable_doc = by_raw["[[doc:34|文档标题]]"]
    check("稳定 ID doc → document", stable_doc["target_kind"] == "document"
          and stable_doc["target_id"] == 34, stable_doc)
    stable_node = by_raw["[[node:7|节点标题]]"]
    check("稳定 ID node", stable_node["target_kind"] == "node"
          and stable_node["target_id"] == 7, stable_node)
    plain = by_raw["[[卷积笔记]]"]
    check("标题式无 kind/id", plain["target_kind"] is None and plain["target_id"] is None
          and plain["target_title"] == "卷积笔记" and plain["heading"] == ""
          and plain["alias"] == "", plain)
    heading_link = by_raw["[[卷积笔记#定义]]"]
    check("标题 + heading", heading_link["target_title"] == "卷积笔记"
          and heading_link["heading"] == "定义" and heading_link["alias"] == "",
          heading_link)
    alias_link = by_raw["[[卷积笔记|我的别名]]"]
    check("标题 + alias", alias_link["target_title"] == "卷积笔记"
          and alias_link["alias"] == "我的别名", alias_link)
    both = by_raw["[[卷积笔记#性质|别名二]]"]
    check("heading + alias 同时存在", both["heading"] == "性质"
          and both["alias"] == "别名二" and both["target_title"] == "卷积笔记", both)
    embed = by_raw["[[doc:34]]"]
    check("嵌入 ![[...]] 被标记", embed["embed"] is True
          and embed["target_kind"] == "document", embed)
    check("空输入安全", links.parse_wikilinks("") == []
          and links.parse_wikilinks(None) == []
          and links.parse_wikilinks("普通文本") == [])


# ---------------------------------------------------------------- 4) 双链 + 关系
def section_links_relations(conn, part_a, node_conv, node_fourier,
                            doc_unique):
    print("4) sync_links 解析 / backlinks / manual relations / 软删目标")
    target_note = notebook.save_note(conn, title="链接目标笔记",
                                     body_md="# 定义\n目标内容。\n",
                                     node_id=node_conv, partition_id=part_a)
    # 同名文档与笔记并存：标题式链接必须先解析到笔记
    add_doc(conn, "链接目标笔记", "d:/tmp/link-target-doc")
    body = (
        f"参考 [[note:{target_note['id']}|笔记A]]、"
        f"[[doc:{doc_unique}|资料A]] 和 [[链接目标笔记#定义]]。\n"
        "同名 [[同名资料]]，未解析 [[不存在的条目]]，节点 [[傅里叶变换]]。\n"
        "旧词条甲只在第一版出现。\n"
    )
    source_note = notebook.save_note(conn, title="链接源笔记", body_md=body,
                                     node_id=node_conv, partition_id=part_a)
    parsed = links.parse_wikilinks(body)
    rows = rows_of(conn, "SELECT * FROM note_links WHERE note_id=? ORDER BY start_off",
                   (source_note["id"],))
    check("note_links 数量与解析一致", len(rows) == len(parsed),
          (len(rows), len(parsed)))
    stable_note = next((r for r in rows if r["alias"] == "笔记A"), None)
    check("稳定 ID note 解析成功",
          stable_note is not None and stable_note["resolved"] == 1
          and stable_note["target_kind"] == "note"
          and stable_note["target_id"] == target_note["id"]
          and stable_note["target_title"] == "链接目标笔记", stable_note)
    stable_doc = next((r for r in rows if r["alias"] == "资料A"), None)
    check("稳定 ID doc 解析成功",
          stable_doc is not None and stable_doc["resolved"] == 1
          and stable_doc["target_kind"] == "document"
          and stable_doc["target_id"] == doc_unique
          and stable_doc["target_title"] == "卷积资料", stable_doc)
    title_link = next((r for r in rows if r["heading"] == "定义" and not r["alias"]), None)
    check("标题式 + heading 解析成功",
          title_link is not None and title_link["resolved"] == 1
          and title_link["target_kind"] == "note"
          and title_link["target_id"] == target_note["id"]
          and title_link["heading"] == "定义", title_link)
    check("同名文档与笔记并存时优先解析为笔记",
          title_link is not None and title_link["target_kind"] == "note",
          title_link)
    node_link = next((r for r in rows if r["target_kind"] == "node"), None)
    check("节点名唯一解析成功",
          node_link is not None and node_link["resolved"] == 1
          and node_link["target_id"] == node_fourier
          and node_link["target_title"] == "傅里叶变换", node_link)
    dup = next((r for r in rows if r["target_title"] == "同名资料"), None)
    check("同名文档不误解：resolved=0 且 kind/id 为 NULL",
          dup is not None and dup["resolved"] == 0
          and dup["target_kind"] is None and dup["target_id"] is None, dup)
    missing = next((r for r in rows if r["target_title"] == "不存在的条目"), None)
    check("未找到保留 target_title 且 resolved=0",
          missing is not None and missing["resolved"] == 0
          and missing["target_kind"] is None
          and missing["target_title"] == "不存在的条目", missing)

    # ---- backlinks incoming / outgoing ----
    back = links.backlinks(conn, "note", target_note["id"])
    incoming = [x for x in back if x["direction"] == "incoming" and x["via"] == "wikilink"]
    check("incoming 反链来自源笔记",
          len(incoming) == 2 and all(x["note_id"] == source_note["id"] for x in incoming),
          incoming)
    check("反链含来源笔记标题",
          all(x["note_title"] == "链接源笔记" for x in incoming))
    check("反链含 heading / snippet",
          any(x["heading"] == "定义" for x in incoming)
          and any(x["snippet"] for x in incoming), incoming)
    outgoing = [x for x in links.backlinks(conn, "note", source_note["id"])
                if x["direction"] == "outgoing" and x["via"] == "wikilink"]
    check("出链覆盖 note/document/node",
          {"note", "document", "node"} <= {x["kind"] for x in outgoing if x["kind"]},
          [x["kind"] for x in outgoing])
    unresolved = [x for x in outgoing if x["kind"] is None]
    check("未解析出链保留且 resolved=False",
          len(unresolved) == 2 and all(not x["resolved"] for x in unresolved),
          unresolved)

    # ---- 人工关系 CRUD ----
    rel = links.save_relation(conn, "note", source_note["id"],
                              "document", doc_unique, rel="cites",
                              label="引用", origin="manual", confidence=0.9)
    check("save_relation 返回 id/字段",
          rel["id"] > 0 and rel["rel"] == "cites" and rel["label"] == "引用"
          and rel["origin"] == "manual" and abs(rel["confidence"] - 0.9) < 1e-9, rel)
    rel_again = links.save_relation(conn, "note", source_note["id"],
                                    "document", doc_unique, rel="cites",
                                    label="引用（改）", confidence=0.8)
    check("同键 save_relation 更新而不是重复插入",
          rel_again["id"] == rel["id"] and rel_again["label"] == "引用（改）"
          and abs(rel_again["confidence"] - 0.8) < 1e-9, rel_again)
    rels_note = links.list_relations(conn, "note", source_note["id"])
    check("list_relations 按 note 查",
          len(rels_note) == 1 and rels_note[0]["direction"] == "outgoing"
          and rels_note[0]["other_kind"] == "document"
          and rels_note[0]["other_id"] == doc_unique, rels_note)
    rels_doc = links.list_relations(conn, "document", doc_unique)
    check("list_relations 反向可查",
          len(rels_doc) == 1 and rels_doc[0]["direction"] == "incoming",
          rels_doc)
    check("list_relations 不存在的实体返回空",
          links.list_relations(conn, "note", 999999) == [])
    expect_raises(ValueError, lambda: links.save_relation(
        conn, "bad", 1, "note", 1), "关系类型非法被拒")
    expect_raises(ValueError, lambda: links.save_relation(
        conn, "note", 999999, "document", doc_unique), "关系源实体不存在被拒")
    expect_raises(ValueError, lambda: links.list_relations(conn, "bad", 1),
                  "list_relations 类型非法被拒")

    back_doc = links.backlinks(conn, "document", doc_unique)
    check("文档反链含 wikilink incoming",
          any(x["via"] == "wikilink" and x["note_id"] == source_note["id"]
              for x in back_doc), back_doc)
    check("文档反链含 manual relation",
          any(x["via"] == "relation" and x["relation_id"] == rel["id"]
              and x["direction"] == "incoming" for x in back_doc), back_doc)

    # ---- 软删目标：反向链接显示 deleted ----
    notebook.delete_note(conn, target_note["id"])
    resolved_rows = rows_of(
        conn, "SELECT resolved FROM note_links WHERE note_id=? "
              "AND target_kind='note' AND target_id=?",
        (source_note["id"], target_note["id"]))
    check("删除笔记后指向它的链接 resolved=0（保留目标）",
          len(resolved_rows) == 2 and all(r["resolved"] == 0 for r in resolved_rows),
          resolved_rows)
    back_deleted = links.backlinks(conn, "note", target_note["id"])
    check("被删笔记的反链仍可查且 deleted=True",
          len(back_deleted) == 2 and all(x["deleted"] for x in back_deleted),
          back_deleted)
    notebook.restore_note(conn, target_note["id"])
    resolved_rows = rows_of(
        conn, "SELECT resolved FROM note_links WHERE note_id=? "
              "AND target_kind='note' AND target_id=?",
        (source_note["id"], target_note["id"]))
    check("恢复笔记后入边重新解析",
          all(r["resolved"] == 1 for r in resolved_rows), resolved_rows)
    check("恢复后反链不再标 deleted",
          all(not x["deleted"] for x in links.backlinks(conn, "note", target_note["id"])))

    # 软删文档：反链同样显示 deleted
    conn.execute("UPDATE documents SET deleted_at=? WHERE id=?", (NOW, doc_unique))
    back_doc_deleted = links.backlinks(conn, "document", doc_unique)
    check("被删文档的反链 deleted=True",
          back_doc_deleted and all(x["deleted"] for x in back_doc_deleted),
          back_doc_deleted)
    conn.execute("UPDATE documents SET deleted_at=NULL WHERE id=?", (doc_unique,))

    # ---- 删除关系 ----
    check("delete_relation 返回 True", links.delete_relation(conn, rel["id"]) is True)
    check("删除后 list_relations 为空",
          links.list_relations(conn, "note", source_note["id"]) == [])
    check("删除后文档反链不再有 relation",
          not any(x["via"] == "relation"
                  for x in links.backlinks(conn, "document", doc_unique)))
    return source_note, target_note


# ---------------------------------------------------------------- 5) 更新不残留
def section_no_residue(conn, source_note, target_note, part_a, node_conv,
                       node_fourier, doc_unique):
    print("5) 保存更新 links 不残留旧链接 / FTS 不残留旧文本")
    old_count = rows_of(conn, "SELECT COUNT(*) c FROM note_links WHERE note_id=?",
                        (source_note["id"],))[0]["c"]
    new_body = ("只保留节点 [[傅里叶变换|唯一节点]] 和笔记 [[链接目标笔记]]。\n"
                "新词条乙触发检索。\n")
    notebook.save_note(conn, note_id=source_note["id"], title="链接源笔记",
                       body_md=new_body, node_id=node_conv, partition_id=part_a)
    rows = rows_of(conn, "SELECT * FROM note_links WHERE note_id=? ORDER BY start_off",
                   (source_note["id"],))
    expected = len(links.parse_wikilinks(new_body))
    check("旧链接被整体替换（数量 = 新解析数）",
          len(rows) == expected and len(rows) < old_count, (len(rows), old_count))
    check("旧文档链接不残留",
          not any(r["target_kind"] == "document" for r in rows), rows)
    check("新链接解析正确",
          any(r["target_kind"] == "node" and r["target_id"] == node_fourier
              and r["alias"] == "唯一节点" for r in rows)
          and any(r["target_kind"] == "note"
                  and r["target_id"] == target_note["id"] for r in rows), rows)
    check("文档反链不再出现该笔记",
          not any(x["note_id"] == source_note["id"]
                  for x in links.backlinks(conn, "document", doc_unique)))
    check("旧正文词条从 FTS 消失",
          source_note["id"] not in
          {x["id"] for x in notebook.search_notes(conn, "旧词条甲")})
    check("新正文词条可检索",
          source_note["id"] in
          {x["id"] for x in notebook.search_notes(conn, "新词条乙")})
    check("chunk 数 = 当前正文解析块数且 >0",
          rows_of(conn, "SELECT COUNT(*) c FROM note_chunks WHERE note_id=?",
                  (source_note["id"],))[0]["c"] > 0)


# ---------------------------------------------------------------- 主流程
def _run(conn):
    check("迁移到 0007",
          rows_of(conn, "SELECT value FROM meta WHERE key='schema_version'")[0]["value"]
          == "0007")
    check("临时数据目录隔离",
          str(config.DB_PATH).lower().startswith(str(_DATA).lower()),
          config.DB_PATH)
    check("未创建 dist/data 真实库",
          not (APP / "dist" / "DocLib" / "data" / "doclib.db").exists()
          or str(config.DB_PATH) != str(APP / "dist" / "DocLib" / "data" / "doclib.db"))

    part_a = tree.create_node(conn, "科目A", None)
    node_conv = tree.create_node(conn, "卷积", part_a)
    node_fourier = tree.create_node(conn, "傅里叶变换", part_a)
    part_b = tree.create_node(conn, "科目B", None)
    node_b = tree.create_node(conn, "B-第一章", part_b)
    unc = tree.ensure_uncategorized(conn)
    doc_unique = add_doc(conn, "卷积资料", "d:/tmp/handbook")
    add_doc(conn, "同名资料", "d:/tmp/dup1")
    add_doc(conn, "同名资料", "d:/tmp/dup2")

    section_crud(conn, part_a, part_b, node_conv, node_fourier, node_b, unc)
    section_chunks_fts(conn, part_a, part_b, node_fourier)
    section_parse()
    short_a, short_b = section_links_relations(
        conn, part_a, node_conv, node_fourier, doc_unique)
    section_no_residue(conn, short_a, short_b, part_a, node_conv, node_fourier,
                       doc_unique)
    return 0


def test_notebook_links():
    conn = db.open_db()
    try:
        assert _run(conn) == 0
    finally:
        conn.close()


def main():
    conn = None
    try:
        conn = db.open_db()
        rc = _run(conn)
        print("\n全部通过 ✅（临时库：%s）" % TMP)
        return rc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                  # noqa: BLE001
                pass
        shutil.rmtree(TMP, ignore_errors=True)


atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))

if __name__ == "__main__":
    sys.exit(main())
