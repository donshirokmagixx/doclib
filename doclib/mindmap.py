# -*- coding: utf-8 -*-
"""知识导图：以「文件」形式存放在 data/mindmaps/*.json 的导图库。

设计要点：
- 一张导图 = 一个 json 文件，可直接拷贝/备份/换机
- 不建数据库表，避免再动 schema（导图属于派生数据，删了可重画）
- 文件名即导图名（净化非法字符），标题存在文件内
"""
import json
import re
import time
from pathlib import Path

from . import config

BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
DEFAULT_VIEW = {"x": 0, "y": 0, "k": 1}


def root_dir() -> Path:
    d = config.DATA_DIR / "mindmaps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    n = BAD.sub("", (name or "").strip()).strip(". ")
    n = re.sub(r"\s+", " ", n)[:60]
    return n or "未命名导图"


def _path(name: str) -> Path:
    return root_dir() / (safe_name(name) + ".json")


def empty_map(title: str) -> dict:
    ts = int(time.time() * 1000)
    return {
        "version": 1,
        "title": safe_name(title),
        "created_at": ts,
        "updated_at": ts,
        "view": dict(DEFAULT_VIEW),
        "items": [],
        "edges": [],
        "strokes": [],
    }


def list_maps() -> list:
    out = []
    for p in sorted(root_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "name": p.stem,
            "title": data.get("title") or p.stem,
            "updated_at": data.get("updated_at", 0),
            "items": len(data.get("items") or []),
            "edges": len(data.get("edges") or []),
        })
    out.sort(key=lambda x: -int(x.get("updated_at") or 0))
    return out


def load(name: str):
    p = _path(name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    data["name"] = p.stem
    for k, v in (("items", []), ("edges", []), ("strokes", [])):
        if not isinstance(data.get(k), list):
            data[k] = []
    if not isinstance(data.get("view"), dict):
        data["view"] = dict(DEFAULT_VIEW)
    return data


def save(name: str, data: dict) -> dict:
    p = _path(name)
    data = dict(data or {})
    data["title"] = data.get("title") or safe_name(name)
    data["updated_at"] = int(time.time() * 1000)
    if not data.get("created_at"):
        data["created_at"] = data["updated_at"]
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "name": p.stem, "updated_at": data["updated_at"]}


def create(name: str) -> dict:
    p = _path(name)
    if p.exists():
        return {"ok": False, "error": "同名导图已存在"}
    data = empty_map(name)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "name": p.stem, "data": data}


def rename(name: str, new_name: str) -> dict:
    src = _path(name)
    if not src.exists():
        return {"ok": False, "error": "导图不存在"}
    dst = _path(new_name)
    if dst.exists() and dst != src:
        return {"ok": False, "error": "目标名称已存在"}
    data = load(name) or empty_map(name)
    data["title"] = safe_name(new_name)
    data.pop("name", None)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if dst != src:
        src.unlink(missing_ok=True)
    return {"ok": True, "name": dst.stem}


def delete(name: str) -> dict:
    p = _path(name)
    if not p.exists():
        return {"ok": False, "error": "导图不存在"}
    p.unlink()
    return {"ok": True}
