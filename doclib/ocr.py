# -*- coding: utf-8 -*-
"""OCR：让图片和扫描版 PDF 也能被检索。

后端优先级：
1. Windows 系统自带 OCR（winsdk + Windows.Media.Ocr，中文环境开箱可用，不联网）
2. tesseract（如果本机装了 tesseract 命令行）
3. 都没有 → 明确告知，不影响其他格式

PDF 页面渲染依赖 pypdfium2。
"""
import asyncio
import tempfile
from pathlib import Path

_CACHE = {"winrt": None, "tesseract": None}


def _has(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def has_winsdk() -> bool:
    """Windows 自带 OCR（winrt 模块化包）。"""
    if _CACHE["winrt"] is None:
        _CACHE["winrt"] = _has("winrt.windows.media.ocr") and _has("winrt.windows.storage")
    return _CACHE["winrt"]


def has_tesseract() -> bool:
    if _CACHE["tesseract"] is None:
        from shutil import which
        _CACHE["tesseract"] = bool(which("tesseract"))
    return _CACHE["tesseract"]


def has_pdfium() -> bool:
    return _has("pypdfium2")


def available() -> dict:
    return {
        "windows_ocr": has_winsdk(),
        "tesseract": has_tesseract(),
        "pdf_render": has_pdfium(),
        "ok": has_winsdk() or has_tesseract(),
    }


# ---------------- Windows OCR ----------------
_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_GAP = __import__("re").compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")
_MULTI_SPACE = __import__("re").compile(r"[ \t]{2,}")


def normalize_ocr(text: str) -> str:
    """Windows OCR 会给每个汉字之间插空格（"卷 积 定 理"），这里还原成连续中文。

    只去掉「汉字-汉字」之间的空格，英文单词之间的空格保留。
    """
    if not text:
        return ""
    text = _CJK_GAP.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


async def _win_ocr_async(path: str):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile

    file = await StorageFile.get_file_from_path_async(str(path))
    stream = await file.open_async(FileAccessMode.READ)
    bitmap = None
    try:
        decoder = await BitmapDecoder.create_async(stream)
        # 无参版本返回解码器原生格式（照片通常是 BGRA8，OCR 引擎可直接接受）
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            from winrt.windows.globalization import Language
            engine = OcrEngine.try_create_from_language(Language("zh-Hans"))
        if engine is None:
            from winrt.windows.globalization import Language
            engine = OcrEngine.try_create_from_language(Language("en-US"))
        if engine is None:
            raise RuntimeError(
                "系统没有可用的 OCR 语言包。\n"
                "设置 → 时间和语言 → 语言和区域 → 中文/英文 → 语言选项 → "
                "添加「光学字符识别」可选功能")
        result = await engine.recognize_async(bitmap)
        return normalize_ocr("\n".join(line.text for line in result.lines))
    finally:
        try:
            if bitmap is not None:
                bitmap.close()
        except Exception:
            pass
        stream.close()


def _win_ocr(path: Path) -> str:
    return asyncio.run(_win_ocr_async(str(path)))


# ---------------- tesseract ----------------
def _tess_ocr(path: Path) -> str:
    import subprocess
    from shutil import which
    exe = which("tesseract")
    env_langs = ""
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=20)
        env_langs = (out.stdout or b"").decode("utf-8", "replace")
    except Exception:
        pass
    lang = "chi_sim+eng" if "chi_sim" in env_langs else "eng"
    proc = subprocess.run([exe, str(path), "stdout", "-l", lang, "--psm", "6"],
                          capture_output=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace")[:200])
    return (proc.stdout or b"").decode("utf-8", "replace")


# ---------------- 对外接口 ----------------
def ocr_image(path) -> str:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"图片不存在：{p}")
    if has_winsdk():
        try:
            return _win_ocr(p)
        except Exception:
            if not has_tesseract():
                raise
    if has_tesseract():
        return _tess_ocr(p)
    raise RuntimeError(
        "当前环境没有 OCR 能力。\n"
        "启用方法（任选其一）：\n"
        "  1) pip install winsdk   —— 使用 Windows 自带中文 OCR，不联网\n"
        "  2) 安装 tesseract-ocr 并加入 PATH")


def ocr_pdf_page(pdf_path, page_index: int, scale: float = 2.2) -> str:
    """把 PDF 第 page_index（0 起）页渲染成图片再 OCR。"""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[page_index]
    bitmap = page.render(scale=scale)
    pil = bitmap.to_pil()
    tmp = Path(tempfile.gettempdir()) / f"doclib_ocr_{abs(hash((str(pdf_path), page_index)))}.png"
    try:
        pil.save(tmp)
        return ocr_image(tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
