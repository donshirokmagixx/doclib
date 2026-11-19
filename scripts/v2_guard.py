# -*- coding: utf-8 -*-
"""v2 开发安全护栏（只读检查，不写任何数据）。

用途：
  python scripts/v2_guard.py              # 打印数据目录/真实库/测试隔离状态
  python scripts/v2_guard.py --for-test   # 测试前检查：必须用临时 DOCLIB_DATA
  python scripts/v2_guard.py --for-package# 打包前检查：必须没有进程占用/真实库风险

退出码：0 安全；1 不安全（调用方应中止）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _norm(p) -> str:
    try:
        return str(Path(p).resolve()).lower()
    except Exception:
        return str(p).lower()


def main() -> int:
    mode = ""
    for arg in sys.argv[1:]:
        if arg in ("--for-test", "--for-package"):
            mode = arg

    print(f"[guard] repo={ROOT}")
    env = os.environ.get("DOCLIB_DATA")
    print(f"[guard] DOCLIB_DATA={env or '(unset)'}")

    from doclib import config  # 仅导入路径配置；不会创建数据库
    print(f"[guard] config.DATA_DIR={config.DATA_DIR}")
    print(f"[guard] DB_PATH={config.DB_PATH} exists={Path(config.DB_PATH).exists()}")

    real_dirs = [
        ROOT / "dist" / "DocLib" / "data",
        ROOT / "data",
    ]
    existing = [p for p in real_dirs if p.exists()]
    for p in existing:
        print(f"[guard] real data dir exists: {p}")

    if mode == "--for-test":
        if not env:
            print("[guard] REFUSE: 测试必须设置 DOCLIB_DATA 指向临时目录")
            return 1
        tmp = _norm(env)
        for p in real_dirs:
            if tmp == _norm(p) or tmp.startswith(_norm(p) + os.sep):
                print(f"[guard] REFUSE: DOCLIB_DATA 指向真实数据目录 {p}")
                return 1
        print("[guard] OK: 测试数据目录隔离")
        return 0

    if mode == "--for-package":
        # 打包前只做静态检查；真正的备份/进程检查由打包脚本执行
        for p in existing:
            print(f"[guard] WARN: 打包前请确认 {p} 已备份，且 DocLib.exe 未运行")
        print("[guard] OK: 静态检查完成（打包脚本必须再校验 move/copy 成败）")
        return 0

    print("[guard] OK: 只读检查完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
