# -*- coding: utf-8 -*-
"""旧版 .doc → .docx 转换。

优先顺序：
1. 找本机 LibreOffice（soffice）—— 无声、稳定；
2. 用已安装的 Microsoft Word（COM 自动化）—— 你机器上已装 Word；
3. 都没有则抛出明确错误。

转换结果缓存在 data/converted/ 下，按源文件的「路径+大小+修改时间」做键，
同一份 .doc 只会转换一次。
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from . import config
from .docx_reader import DocxError

_SOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$src = $env:DOCLIB_SRC
$dst = $env:DOCLIB_DST
$word = $null
try {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  try { $word.DisplayAlerts = 0 } catch {}
  $doc = $word.Documents.Open($src, $false, $true)
  $doc.SaveAs2($dst, 16)
  $doc.Close($false)
  Write-Output 'OK'
} finally {
  if ($word) { try { $word.Quit() } catch {} }
}
"""


def _cache_key(path: Path) -> str:
    from .versioning import PARSE_VERSION
    st = path.stat()
    # 把解析管线版本放进键里：升级解析器后，旧的 .doc 转换缓存会自动失效
    raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|v{PARSE_VERSION}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _find_soffice():
    for p in _SOFFICE_CANDIDATES:
        if os.path.exists(p):
            return p
    from shutil import which
    return which("soffice") or which("soffice.exe")


def _convert_with_soffice(soffice: str, src: Path, out_dir: Path) -> Path:
    profile = out_dir / "lo-profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [soffice, "--headless", "--norestore",
           f"-env:UserInstallation=file:///{profile.as_posix().lstrip('/')}",
           "--convert-to", "docx", "--outdir", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, timeout=180,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = out_dir / (src.stem + ".docx")
    if proc.returncode != 0 or not out.exists():
        err = (proc.stderr or b"").decode("utf-8", "replace")[:300]
        raise DocxError(f"LibreOffice 转换失败：{err or proc.returncode}")
    return out


def _convert_with_word(src: Path, dst: Path) -> Path:
    if sys.platform != "win32":
        raise DocxError("只有 Windows 上才能用 Word 转换 .doc")
    env = dict(os.environ)
    env["DOCLIB_SRC"] = str(src)
    env["DOCLIB_DST"] = str(dst)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            capture_output=True, timeout=240, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise DocxError("Word 转换超时（可能弹了对话框）。请先用 Word 手动另存为 .docx") from e
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    if proc.returncode != 0 or "OK" not in out:
        raise DocxError(
            "转换 .doc 失败：本机没有 LibreOffice，且用 Word 自动转换没成功。\n"
            "解决办法：用 Word 打开这个文件，另存为 .docx 再导入。\n"
            f"（详情：{(err or out).strip()[:200]}）")
    if not dst.exists():
        raise DocxError("转换 .doc 后没有生成文件")
    return dst


def convert_doc(path) -> Path:
    """把 .doc 转成 .docx，返回可解析的路径（带缓存）。"""
    src = Path(path)
    config.ensure_dirs()
    out_dir = config.CONVERT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"doc_{_cache_key(src)}.docx"
    if dst.exists() and dst.stat().st_size > 0:
        return dst

    soffice = _find_soffice()
    if soffice:
        tmp_dir = out_dir / f"tmp_{_cache_key(src)}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        produced = _convert_with_soffice(soffice, src, tmp_dir)
        produced.replace(dst)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
        return dst

    return _convert_with_word(src, dst)


def available() -> dict:
    """给界面/诊断用：本机支持哪种 .doc 转换。"""
    soffice = _find_soffice()
    return {"soffice": soffice, "word": sys.platform == "win32"}
