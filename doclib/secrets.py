# -*- coding: utf-8 -*-
"""A4：本地密钥保管（Windows DPAPI 加密，零第三方依赖）。

设计：
- API Key **不进数据库**，只加密存放在 `data/secrets.bin`
- 加密用 Windows DPAPI（CurrentUser 范围）：换用户/换电脑解不开，天然安全
- 数据库里 `ai_providers.key_ref` 只存「键名」，不存密钥本身
- 界面上永远只显示掩码

非 Windows 环境会明确报错，而不是退化成明文保存。
"""
import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

from . import config

_FILE = "secrets.bin"
_ENTROPY = b"DocLib-secrets-v1"


class SecretsError(Exception):
    pass


# ---------------- DPAPI ----------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretsError("当前系统不支持 DPAPI 加密存储，请勿在此环境保存密钥")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, _b1 = _blob(data)
    blob_ent, _b2 = _blob(_ENTROPY)
    blob_out = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), "DocLib", ctypes.byref(blob_ent),
        None, None, 0x1, ctypes.byref(blob_out))   # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise SecretsError(f"加密失败（错误码 {kernel32.GetLastError()}）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretsError("当前系统不支持 DPAPI 解密")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, _b1 = _blob(data)
    blob_ent, _b2 = _blob(_ENTROPY)
    blob_out = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
        None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise SecretsError(f"解密失败（错误码 {kernel32.GetLastError()}）——"
                           "可能换了 Windows 用户或这台电脑")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


# ---------------- 存取 ----------------
def _path() -> Path:
    config.ensure_dirs()
    return config.DATA_DIR / _FILE


def _load_raw() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_raw(data: dict) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def validate_key(value: str):
    """返回 (ok, 提示语)。API Key 必须是纯 ASCII、不含空白、长度合理。"""
    v = (value or "").strip()
    if not v:
        return False, "密钥不能为空"
    if any(ord(c) > 127 for c in v):
        bad = "".join(c for c in v if ord(c) > 127)[:8]
        return False, (f"密钥里包含中文或全角字符（如「{bad}」），多半是粘贴错了。"
                       "API Key 只包含英文、数字和 . - _ 这类符号。")
    if any(c.isspace() for c in v):
        return False, "密钥里不能有空格或换行，请删掉多余的空白。"
    if len(v) < 12:
        return False, f"密钥看起来太短（{len(v)} 个字符），可能没复制完整。"
    if len(v) > 200:
        return False, f"密钥过长（{len(v)} 个字符），可能粘进了说明文字，请只保留 Key 本身。"
    return True, ""


def set_secret(name: str, value: str) -> None:
    name = (name or "").strip()
    if not name:
        raise SecretsError("键名不能为空")
    if not value:
        raise SecretsError("密钥不能为空")
    ok, msg = validate_key(value)
    if not ok:
        raise SecretsError(msg)
    value = value.strip()
    raw = _load_raw()
    raw[name] = base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")
    _save_raw(raw)


def get_secret(name: str):
    raw = _load_raw()
    blob = raw.get(name)
    if not blob:
        return None
    try:
        return _unprotect(base64.b64decode(blob)).decode("utf-8")
    except SecretsError:
        return None


def delete_secret(name: str) -> bool:
    raw = _load_raw()
    if name not in raw:
        return False
    del raw[name]
    _save_raw(raw)
    return True


def list_secrets() -> list:
    """只返回键名，永不返回内容。"""
    return sorted(_load_raw().keys())


def masked(name: str) -> str:
    v = get_secret(name)
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return v[:4] + "*" * 8 + v[-4:]


def status() -> dict:
    return {
        "file": str(_path()),
        "exists": _path().exists(),
        "count": len(_load_raw()),
        "dpapi": sys.platform == "win32",
    }

# ================= 便携密钥（换电脑也能用） =================
# DPAPI 只能本机本用户解密；复制到新电脑会失效。
# 若存在 data\secrets.portable.json，则作为回退：内容为明文键值（base64 包裹）。
# ⚠️ 安全提示：这个文件等同于明文密钥，只适合自己用的便携包，不要外传。

PORTABLE_NAME = "secrets.portable.json"


def portable_path():
    return _path().parent / PORTABLE_NAME


def _load_portable() -> dict:
    import json
    p = portable_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_secret(name: str):
    raw = _load_raw()
    if name in raw:
        try:
            return _unprotect(base64.b64decode(raw[name])).decode("utf-8")
        except Exception:
            pass
    val = _load_portable().get(name)
    return val or None


def list_secrets() -> list:
    names = set(_load_raw().keys()) | set(_load_portable().keys())
    return sorted(names)


def export_portable(dst=None) -> dict:
    """把当前所有密钥导出到便携文件（明文，含安全风险）。"""
    import json
    out = {}
    for n in list_secrets():
        v = get_secret(n)
        if v:
            out[n] = v
    target = dst or portable_path()
    from pathlib import Path
    Path(target).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"count": len(out), "path": str(target)}
