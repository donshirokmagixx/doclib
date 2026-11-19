# -*- coding: utf-8 -*-
"""工作区布局持久化（data/workspace.json）。

只服务单机、单用户。所有输入都做结构/大小校验；损坏文件改名保留，不静默删除。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from . import config

MAX_BYTES = 256 * 1024
MAX_TABS_PER_PANE = 12
MAX_PANES = 2
ALLOWED_THEMES = {"system", "dark", "light"}
ALLOWED_TAB_KINDS = {"graph", "doc", "note", "mindmap", "search", "node", "settings", "welcome"}


def _now() -> int:
    return int(time.time() * 1000)


def _path() -> Path:
    return config.DATA_DIR / "workspace.json"


def _bak_path() -> Path:
    return config.DATA_DIR / "workspace.bak.json"


def _tab(kind: str = "graph", title: str = "关系图谱", params: dict | None = None) -> dict:
    return {
        "id": f"t{_now()}_{kind}",
        "kind": kind,
        "title": str(title)[:80],
        "params": params or {},
        "pinned": False,
    }


def default_workspace() -> dict:
    return {
        "version": 1,
        "updated_at": _now(),
        "theme": "dark",
        "active_pane": "p1",
        "layout": {
            "left_width": 268,
            "right_width": 374,
            "left_collapsed": False,
            "right_collapsed": False,
            "split": None,
        },
        "panes": [{
            "id": "p1",
            "active_tab": "t_graph",
            "tabs": [{
                "id": "t_graph", "kind": "graph", "title": "关系图谱",
                "params": {"scope": "global", "partitionId": None,
                           "center": None, "depth": 1},
                "pinned": False,
            }],
        }],
        "history": {"p1": {"entries": [], "index": -1}},
    }


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clean_params(kind: str, params: Any) -> dict:
    if not isinstance(params, dict):
        return {}
    out: dict = {}
    # 只保留允许的标量字段，避免把任意大对象塞进工作区
    allowed = {
        "docId", "noteId", "nodeId", "chunkId", "scrollTop", "scope",
        "partitionId", "center", "depth", "q", "kind", "mode", "mapName",
        "query", "filters",
    }
    for k, v in params.items():
        if k not in allowed:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            if isinstance(v, str):
                v = v[:500]
            out[k] = v
        elif k == "filters" and isinstance(v, dict):
            f = {}
            for fk in ("types", "rels", "q", "partitionId"):
                if fk in v and isinstance(v[fk], (str, list, int, type(None))):
                    f[fk] = v[fk] if not isinstance(v[fk], str) else v[fk][:200]
            out["filters"] = f
    return out


def validate(data: Any) -> dict:
    """把任意输入收敛成安全的工作区结构。"""
    base = default_workspace()
    if not isinstance(data, dict):
        return base
    out = copy.deepcopy(base)
    out["version"] = 1
    theme = str(data.get("theme") or "dark").lower()
    out["theme"] = theme if theme in ALLOWED_THEMES else "dark"
    layout = data.get("layout") if isinstance(data.get("layout"), dict) else {}
    out["layout"] = {
        "left_width": _clamp(layout.get("left_width"), 180, 420, 268),
        "right_width": _clamp(layout.get("right_width"), 300, 560, 374),
        "left_collapsed": bool(layout.get("left_collapsed")),
        "right_collapsed": bool(layout.get("right_collapsed")),
        "split": layout.get("split") if isinstance(layout.get("split"), dict) else None,
    }
    panes = data.get("panes")
    if not isinstance(panes, list) or not panes:
        panes = base["panes"]
    cleaned_panes = []
    used_ids = set()
    for i, p in enumerate(panes[:MAX_PANES]):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or f"p{i + 1}")[:20]
        if pid in used_ids:
            pid = f"p{i + 1}"
        used_ids.add(pid)
        tabs = []
        for t in (p.get("tabs") or [])[:MAX_TABS_PER_PANE]:
            if not isinstance(t, dict):
                continue
            kind = str(t.get("kind") or "")
            if kind not in ALLOWED_TAB_KINDS:
                continue
            tid = str(t.get("id") or f"t{i}_{len(tabs)}")[:40]
            tabs.append({
                "id": tid,
                "kind": kind,
                "title": str(t.get("title") or kind)[:80],
                "params": _clean_params(kind, t.get("params")),
                "pinned": bool(t.get("pinned")),
            })
        if not tabs:
            tabs = [{"id": f"t{i}_welcome", "kind": "welcome", "title": "欢迎",
                     "params": {}, "pinned": False}]
        active = str(p.get("active_tab") or tabs[0]["id"])
        if active not in {t["id"] for t in tabs}:
            active = tabs[0]["id"]
        cleaned_panes.append({"id": pid, "active_tab": active, "tabs": tabs})
    if not cleaned_panes:
        cleaned_panes = base["panes"]
    out["panes"] = cleaned_panes
    out["active_pane"] = str(data.get("active_pane") or cleaned_panes[0]["id"])
    if out["active_pane"] not in {p["id"] for p in cleaned_panes}:
        out["active_pane"] = cleaned_panes[0]["id"]
    # 历史只保留最近的 doc/anchor 结构；不信任任意 JSON
    hist = {}
    h = data.get("history")
    if isinstance(h, dict):
        for pid, item in h.items():
            if not isinstance(item, dict):
                continue
            entries = []
            for e in (item.get("entries") or [])[:50]:
                if isinstance(e, dict):
                    entries.append({k: e[k] for k in ("kind", "id", "title", "anchor", "scrollTop")
                                    if k in e and isinstance(e[k], (str, int, float))})
            hist[str(pid)[:20]] = {"entries": entries,
                                   "index": _clamp(item.get("index"), -1, len(entries) - 1, -1)}
    out["history"] = hist
    out["updated_at"] = _now()
    # 大小兜底
    raw = json.dumps(out, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        return base
    return out


def load() -> dict:
    p = _path()
    if not p.exists():
        return default_workspace()
    try:
        raw = p.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError("workspace too large")
        data = json.loads(raw.decode("utf-8"))
        return validate(data)
    except Exception:
        # 保留损坏文件，便于排查；返回默认布局
        try:
            bad = config.DATA_DIR / f"workspace.corrupt-{_now()}.json"
            shutil.copy2(p, bad)
        except Exception:
            pass
        return default_workspace()


def save(data: Any) -> dict:
    config.ensure_dirs()
    clean = validate(data)
    raw = json.dumps(clean, ensure_ascii=False, indent=1).encode("utf-8")
    if len(raw) > MAX_BYTES:
        return {"ok": False, "error": "工作区状态过大，请关闭一些标签"}
    p = _path()
    tmp = p.with_suffix(".tmp")
    if p.exists():
        try:
            shutil.copy2(p, _bak_path())
        except Exception:
            pass
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return {"ok": True, "workspace": clean}


def reset() -> dict:
    return save(default_workspace())
