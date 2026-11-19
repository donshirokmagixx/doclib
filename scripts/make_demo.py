# -*- coding: utf-8 -*-
"""生成 v2 演示数据（只写 DOCLIB_DATA 指定的临时目录，不碰真实库）。

用法：
  set DOCLIB_DATA=%TEMP%\doclib-v2-demo
  .venv\Scripts\python.exe scripts\make_demo.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from doclib import db, seed, importer, tree, notebook, links  # noqa: E402


def main():
    data = os.environ.get("DOCLIB_DATA")
    if not data:
        data = str(Path(tempfile.gettempdir()) / "doclib-v2-demo")
        os.environ["DOCLIB_DATA"] = data
    Path(data).mkdir(parents=True, exist_ok=True)
    conn = db.open_db()
    seed.seed(conn)
    parts = tree.list_partitions(conn)
    sig = next((p for p in parts if p["name"] == "信号分析与处理"), parts[0] if parts else None)
    root = tree.get_node(conn, sig["id"]) if sig else None
    nodes = conn.execute("SELECT id, name FROM nodes WHERE deleted_at IS NULL").fetchall()
    by_name = {r["name"]: r["id"] for r in nodes}
    conv = by_name.get("卷积") or (sig["id"] if sig else None)
    ft = by_name.get("傅里叶变换") or (sig["id"] if sig else None)

    src = Path(data) / "demo_src"
    src.mkdir(parents=True, exist_ok=True)
    docs = [
        ("信号的卷积.pdf.md", "# 信号的卷积：原理、性质与变换域分析\n\n"
         "## 2.1 从叠加到卷积\n\n"
         "设系统的输入为 x(t)，冲激响应为 h(t)。把输入分解成一串加权冲激，"
         "对线性时不变系统，每个冲激产生一个平移后的 h(t - τ)，叠加即得输出。\n\n"
         "因此，系统的零状态响应可以写成卷积积分：\n\n"
         "y(t) = x(t) * h(t) = ∫ x(τ) h(t − τ) dτ\n\n"
         "这个式子的直观含义是：输出在某一时刻的值，等于输入在过去所有时刻的贡献之和。\n\n"
         "## 2.2 三个可以直接手算的性质\n\n"
         "卷积的交换律、分配律和结合律，使我们可以先算最简单的部分，再把结果搬回原来的问题。"
         "与冲激函数卷积不改变波形，与阶跃函数卷积则相当于积分。\n\n"
         "## 2.3 什么时候不该直接算卷积\n\n"
         "当信号长度达到 10^5 量级时，直接做离散卷积的代价是 O(N²)。"
         "这时应当转到频域，用 FFT 计算乘积再变换回来；代价变成 O(N log N)。\n", conv),
        ("傅里叶变换.pdf.md", "# 傅里叶变换：从级数到 DFT\n\n"
         "## 1. 傅里叶级数与傅里叶变换\n\n"
         "周期信号可以展开为傅里叶级数；非周期信号则用傅里叶变换表示其频谱。\n\n"
         "## 2. DFT 与 FFT\n\n"
         "DFT 是定义在有限长离散序列上的变换，把 N 个时域样本映射成 N 个频域系数。"
         "FFT 不是另一种变换，而是计算 DFT 的一类快速算法，利用旋转因子的周期性和对称性，"
         "把 O(N²) 的运算量降到 O(N log N)。\n\n"
         "## 3. 常见变换对\n\n"
         "矩形脉冲的傅里叶变换是 sinc 函数；冲激函数的变换是常数；阶跃函数的变换包含 1/(jω) 与冲激项。\n", ft),
        ("离散时间信号分析.pdf.md", "# 离散时间信号分析\n\n"
         "## 1. 采样与奈奎斯特频率\n\n"
         "连续信号经过理想采样后，频谱会周期延拓；当采样频率低于两倍最高频率时会发生混叠。\n\n"
         "## 2. DTFT 与 z 变换\n\n"
         "DTFT 给出离散时间信号的连续频谱；z 变换把差分方程变成代数方程，便于分析系统稳定性。\n", by_name.get("离散时间信号分析") or (sig["id"] if sig else None)),
    ]
    imported = []
    for name, text, node_id in docs:
        p = src / name
        p.write_text(text, encoding="utf-8")
        rep = importer.import_path(conn, str(p), mount_mode="auto")
        for it in rep.get("items", []):
            did = it.get("doc_id")
            if did and node_id:
                importer.set_doc_nodes(conn, int(did), [int(node_id)])
                imported.append((did, name))

    # 让图谱/文件树在演示时更接近真实课程规模（约 25 个实体）
    extra = [
        ("信号与系统", "线性时不变系统、稳定性与因果性的判据。"),
        ("冲激响应", "冲激响应完全描述 LTI 系统；卷积给出任意输入响应。"),
        ("阶跃响应", "阶跃响应是冲激响应的积分，用于观察系统瞬态。"),
        ("傅里叶级数", "周期信号展开为正弦/余弦的加权和。"),
        ("频谱", "幅度谱与相位谱共同描述信号的频域结构。"),
        ("采样定理", "采样频率必须大于两倍最高频率，否则发生混叠。"),
        ("z 变换", "把差分方程化为代数方程，收敛域决定稳定性。"),
        ("拉普拉斯变换", "连续时间系统的复频域分析工具。"),
        ("系统函数", "零极点分布决定系统的频率响应与稳定性。"),
        ("卷积定理", "时域卷积对应频域相乘，是快速卷积的基础。"),
        ("相关函数", "自相关与互相关用于检测周期性与时延。"),
        ("功率谱", "功率谱密度描述随机信号的频域能量分布。"),
        ("滤波器", "低通、高通、带通与带阻滤波器的设计。"),
        ("调制与解调", "把基带信号搬移到载频，实现频谱搬移。"),
    ]
    extra_nodes = {}
    for i, (name, desc) in enumerate(extra):
        nid = tree.create_node(conn, name, sig["id"])
        extra_nodes[name] = nid
        if i < 5:
            p = src / f"{name}.pdf.md"
            p.write_text(f"# {name}\n\n## 概念\n\n{desc}\n\n## 与课程的关系\n\n{desc} 这一节和信号与系统的整体框架相连。\n",
                         encoding="utf-8")
            rep = importer.import_path(conn, str(p), mount_mode="auto")
            for it in rep.get("items", []):
                did = it.get("doc_id")
                if did:
                    importer.set_doc_nodes(conn, int(did), [int(nid)])
    # 重新读取节点 id（演示笔记挂到具体主题）
    ft = conn.execute("SELECT id FROM nodes WHERE name='傅里叶变换' AND deleted_at IS NULL LIMIT 1").fetchone()["id"]
    conv = conn.execute("SELECT id FROM nodes WHERE name='卷积' AND deleted_at IS NULL LIMIT 1").fetchone()["id"]
    note_body = (
        "# DFT 与 FFT 的关系\n\n"
        "DFT 回答“变换是什么”，FFT 回答“怎么算得快”。两者结果相同，差别在复杂度与适用规模。\n\n"
        f"关联资料：[[doc:{imported[1][0] if len(imported) > 1 else 0}|傅里叶变换]]\n\n"
        f"关联节点：[[node:{ft}|傅里叶变换]]\n"
    )
    n = notebook.save_note(conn, title="DFT 与 FFT 的关系", body_md=note_body,
                           node_id=ft, partition_id=sig["id"])
    note_body2 = (
        "# 卷积定理的三种证明\n\n"
        "1. 从定义直接换元；2. 用傅里叶变换的乘性；3. 用冲激响应与 LTI 的频域表示。\n\n"
        f"参见 [[note:{n['id']}|DFT 与 FFT 的关系]]。\n"
    )
    notebook.save_note(conn, title="卷积定理的三种证明", body_md=note_body2,
                       node_id=conv, partition_id=sig["id"])
    print("demo data:", data)
    print("docs:", conn.execute("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL").fetchone()[0])
    print("chunks:", conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0])
    print("notes:", conn.execute("SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
