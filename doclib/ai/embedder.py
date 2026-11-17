# -*- coding: utf-8 -*-
"""本地免费嵌入模型（BAAI bge-small-zh-v1.5，ONNX 量化版）。

- 完全离线、不花钱、不上传内容
- 依赖：onnxruntime + tokenizers + numpy（本机已装）
- 模型放在 data/models/bge-small-zh-v1.5/，缺失时自动降级为「仅关键词检索」
"""
import threading
from pathlib import Path
from typing import List, Optional

from .. import config

MODEL_NAME = "bge-small-zh-v1.5"
EMBED_VERSION = 1
DIM = 512
# bge 中文模型的检索式前缀（查询侧加，文档侧不加）
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_lock = threading.Lock()
_state = {"session": None, "tokenizer": None, "model_dir": None, "error": ""}


def model_dir() -> Path:
    """模型目录：优先当前数据目录；数据目录收归后，回退到旧的 APP_DIR/data/models。"""
    p = config.DATA_DIR / "models" / MODEL_NAME
    if (p / "model.onnx").exists():
        return p
    legacy = config.APP_DIR / "data" / "models" / MODEL_NAME
    if (legacy / "model.onnx").exists():
        return legacy
    return p


def _has(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def available() -> dict:
    """给界面/诊断用。"""
    d = model_dir()
    files_ok = all((d / f).exists() for f in ("model.onnx", "tokenizer.json"))
    deps_ok = _has("onnxruntime") and _has("tokenizers") and _has("numpy")
    loaded = _state["session"] is not None
    return {
        "name": MODEL_NAME,
        "dim": DIM,
        "model_dir": str(d),
        "files_ok": files_ok,
        "deps_ok": deps_ok,
        "loaded": loaded,
        "ok": bool(files_ok and deps_ok),
        "error": _state["error"],
    }


def _load():
    """懒加载模型（第一次调用会花 ~1 秒）。"""
    with _lock:
        if _state["session"] is not None:
            return _state["session"], _state["tokenizer"]
        d = model_dir()
        model_path = d / "model.onnx"
        tok_path = d / "tokenizer.json"
        if not model_path.exists() or not tok_path.exists():
            _state["error"] = (f"本地向量模型缺失：{d}\n"
                               "可重新运行 scripts/setup_embed.py 下载（约 23MB）")
            raise RuntimeError(_state["error"])
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as e:
            _state["error"] = f"缺少依赖：{e}（需要 onnxruntime / tokenizers / numpy）"
            raise RuntimeError(_state["error"]) from e
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(str(tok_path))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        _state.update(session=session, tokenizer=tokenizer, model_dir=d, error="")
        return session, tokenizer


def warmup() -> bool:
    try:
        _load()
        return True
    except Exception:
        return False


def embed_texts(texts: List[str], is_query: bool = False, batch_size: int = 16) -> List[List[float]]:
    """把文本编码成归一化向量（512 维）。"""
    import numpy as np
    session, tokenizer = _load()
    out: List[List[float]] = []
    inputs_meta = {i.name for i in session.get_inputs()}

    items = [(QUERY_PREFIX + t) if is_query else (t or "") for t in texts]
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        encs = tokenizer.encode_batch([b if b else " " for b in batch])
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in inputs_meta:
            feed["token_type_ids"] = np.zeros_like(ids)
        feas = session.run(None, feed)
        # 取 last_hidden_state（若模型输出含 pooler 也用不到）
        hidden = feas[0]
        cls = hidden[:, 0, :].astype(np.float32)
        norm = np.linalg.norm(cls, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        cls = cls / norm
        out.extend(cls.tolist())
    return out


def embed_query(text: str) -> Optional[List[float]]:
    try:
        return embed_texts([text], is_query=True)[0]
    except Exception:
        return None


def status() -> dict:
    st = available()
    st["version"] = EMBED_VERSION
    return st
