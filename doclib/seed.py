# -*- coding: utf-8 -*-
"""初始知识树（信号分析与处理）。可重复执行，已存在则跳过。"""
import json

from . import tree
from .db import now_ms

SEED_TREE = [
    {
        "name": "信号分析与处理",
        "description": "学科总节点：信号、系统与各种变换",
        "keywords": ["信号", "系统", "线性时不变", "LTI", "频域", "变换域"],
        "children": [
            {
                "name": "卷积",
                "description": "卷积的定义、性质、几何图解与典型计算",
                "keywords": ["卷积", "卷积定理", "冲激响应", "LTI", "翻转", "平移",
                             "叠加", "时域", "阶跃响应", "RC 电路"],
            },
            {
                "name": "傅里叶变换",
                "description": "从傅里叶级数到傅里叶变换，频谱与性质",
                "keywords": ["傅里叶变换", "频谱", "正交投影", "吉布斯", "对偶",
                             "时移", "频移", "DTFT", "CTFT"],
            },
            {
                "name": "常见傅里叶变换的函数",
                "description": "常见信号（矩形脉冲、sinc、冲激、阶跃、复指数等）的变换对",
                "keywords": ["傅里叶级数", "三角形式", "指数形式", "sinc", "矩形脉冲",
                             "门函数", "周期信号", "冲激", "阶跃", "变换对",
                             "拉普拉斯变换"],
            },
        ],
    }
]


def seed(conn) -> dict:
    existing = conn.execute(
        "SELECT id, name FROM nodes WHERE parent_id IS NULL AND deleted_at IS NULL"
    ).fetchall()
    names = {r["name"] for r in existing}
    created = 0
    for root in SEED_TREE:
        if root["name"] in names:
            continue
        created += tree.create_seed_tree(conn, [root])
    unc = tree.ensure_uncategorized(conn)
    conn.execute("INSERT INTO meta(key,value) VALUES('seeded',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now_ms()),))
    return {"created_nodes": created, "uncategorized_node": unc}
