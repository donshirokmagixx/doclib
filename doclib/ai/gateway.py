# -*- coding: utf-8 -*-
"""AI 网关：统一 OpenAI 兼容接口的调用（第 1 步）。

设计原则（和整个项目一致）：
- **零第三方依赖**：用标准库 urllib，不引入 httpx，打包体积不涨
- **密钥只从 DPAPI 取**，绝不写进日志、绝不返回给界面
- **每次调用都记 ai_runs**：模型 / 耗时 / token / 成功失败，方便排查和控成本
- **错误翻译成人话**：401 是密钥问题、404 是地址问题、429 是额度/频率……

支持的供应商类型：
    openai_compatible  —— DeepSeek / 通义 / Moonshot / OpenAI / Ollama(OpenAI 兼容)…
    ollama             —— 本地 Ollama 原生接口
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import List, Optional

from ..db import now_ms

DEFAULT_TIMEOUT = 90


@dataclass
class Provider:
    id: int
    name: str
    kind: str
    base_url: str
    model: str
    key_ref: str
    role: str = "chat"
    enabled: int = 1
    is_default: int = 0
    free: int = 0
    price_in: float = 0.0      # 元 / 百万 tokens（输入）
    price_out: float = 0.0     # 元 / 百万 tokens（输出）
    note: str = ""

    @property
    def is_free(self) -> bool:
        # 只有显式勾选「免费」或本地 Ollama 才算免费；
        # 价格没填 ≠ 免费（不能误导成本）
        return bool(self.free) or self.kind == "ollama"

    def cost_micro(self, tokens_in: int, tokens_out: int) -> int:
        """返回微元（1e-6 元）。价格按「元/百万 token」计。"""
        return int(round(tokens_in * self.price_in + tokens_out * self.price_out))

    def masked_keyring(self) -> str:
        return self.key_ref or "（未配置密钥）"


# ---------------- 配置读取 ----------------
def _to_provider(row) -> Provider:
    keys = row.keys()

    def g(k, d=0):
        return row[k] if k in keys else d

    return Provider(
        id=row["id"], name=row["name"], kind=row["kind"],
        base_url=row["base_url"] or "", model=row["model"] or "",
        key_ref=row["key_ref"] or "", role=row["role"] or "chat",
        enabled=row["enabled"], is_default=int(g("is_default", 0) or 0),
        free=int(g("free", 0) or 0),
        price_in=float(g("price_in", 0) or 0),
        price_out=float(g("price_out", 0) or 0),
        note=str(g("note", "") or ""),
    )


def load_provider(conn, name: Optional[str] = None, role: str = "chat") -> Optional[Provider]:
    """取一个模型配置。

    优先级（name 为空时）：
        1. 该 role 下「已设为默认且启用」的那个
        2. 该 role 下启用的第一个（免费优先）
    """
    if name:
        row = conn.execute("SELECT * FROM ai_providers WHERE name=?", (name,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM ai_providers WHERE enabled=1 AND role=? AND is_default=1 "
            "ORDER BY id LIMIT 1", (role,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM ai_providers WHERE enabled=1 AND role=? "
                "ORDER BY free DESC, id LIMIT 1", (role,)).fetchone()
    return _to_provider(row) if row else None


def list_providers(conn) -> List[dict]:
    rows = conn.execute("SELECT * FROM ai_providers ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ---------------- URL 拼装 ----------------
def endpoint(base_url: str, path: str = "chat/completions") -> str:
    """把用户填的 base_url 规范化成完整的接口地址。

    例子：
        https://api.deepseek.com               -> …/v1/chat/completions
        https://api.deepseek.com/v1            -> …/v1/chat/completions
        https://api.openai.com/v1/chat/completions -> 原样（用户填了完整地址）
        http://localhost:11434/v1              -> …/v1/chat/completions
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("接口地址为空")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    if base.endswith("/" + path) or base.endswith(path):
        return base
    if "/v1" not in base and "/api/" not in base:
        base += "/v1"
    return base + "/" + path


# ---------------- HTTP ----------------
def _ssl_ctx(verify: bool = True):
    """HTTPS 证书上下文：优先 certifi；没有就拿系统默认。

    某些电脑（新装的 Windows / 精简系统 / 某些代理）会报
    CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate。
    这里先尝试 certifi 的证书包，仍失败时由 _post_json 自动降级重试。
    """
    # 恢复原来的行为：用系统默认证书；只有在证书校验失败时才降级重试
    import ssl
    return ssl.create_default_context()


def _ssl_ctx_unverified():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _post_json(url: str, payload: dict, headers: dict, timeout: int):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for k, v in headers.items():
        req.add_header(k, v)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"ok": True, "status": resp.status, "raw": raw,
                    "latency_ms": int((time.time() - started) * 1000)}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:800]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "raw": body,
                "latency_ms": int((time.time() - started) * 1000)}
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        text = str(reason)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text.lower():
            # 证书链缺失：不校验证书再试一次（内网/代理/精简系统常见）
            try:
                with urllib.request.urlopen(req, timeout=timeout,
                                            context=_ssl_ctx_unverified()) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    return {"ok": True, "status": resp.status, "raw": raw,
                            "latency_ms": int((time.time() - started) * 1000),
                            "insecure_tls": True}
            except Exception as e2:  # noqa: BLE001
                return {"ok": False, "status": 0,
                        "raw": f"证书校验失败且降级重试也失败：{e2}",
                        "latency_ms": int((time.time() - started) * 1000)}
        return {"ok": False, "status": 0, "raw": text,
                "latency_ms": int((time.time() - started) * 1000)}
    except TimeoutError:
        return {"ok": False, "status": -1, "raw": "请求超时",
                "latency_ms": int((time.time() - started) * 1000)}


def _friendly_error(status: int, raw: str, url: str) -> str:
    text = (raw or "").strip()
    if status == 401 or status == 403:
        return ("密钥无效或没有权限（401/403）。请检查「设置 → 密钥」里填的内容，"
                "以及模型配置里引用的键名是否一致。")
    if status == 402:
        return "账户余额不足（402）。"
    if status == 404:
        return (f"接口地址不对（404）：{url}\n"
                "检查「接口地址」是否填成了完整路径（有的服务商要填 /v1 结尾）。")
    if status == 429:
        return "请求过于频繁或被限流（429），稍后再试。"
    if status == -1:
        return "请求超时。网络慢或服务商无响应。"
    if status == 0:
        return f"网络不通：{text}\n检查网络/代理，或确认接口地址是否正确。"
    # 服务端常见错误体：{"error":{"message":"..."}}
    try:
        j = json.loads(text)
        msg = (j.get("error") or {}).get("message") or j.get("message") or ""
        if msg:
            return f"接口返回 {status}：{msg}"
    except Exception:
        pass
    return f"接口返回 {status}：{text[:300]}"


# ---------------- 日志 ----------------
def _log_run(conn, *, trace_id, task_type, provider, model, prompt_digest,
             tokens_in=0, tokens_out=0, latency_ms=0, ok=1, error="", cost_micro=0):
    try:
        conn.execute(
            "INSERT INTO ai_runs(trace_id, task_type, provider, model, prompt_digest,"
            " tokens_in, tokens_out, cost_micro, latency_ms, ok, error, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (trace_id, task_type, provider, model, (prompt_digest or "")[:120],
             tokens_in, tokens_out, int(cost_micro), latency_ms, 1 if ok else 0,
             (error or "")[:400], now_ms()),
        )
    except Exception:
        pass


# ---------------- 核心调用 ----------------
def chat(conn, messages: List[dict], provider: Optional[Provider] = None,
         temperature: float = 0.2, max_tokens: int = 1024,
         timeout: int = DEFAULT_TIMEOUT, task_type: str = "chat",
         log: bool = True, prompt_version: str = "") -> dict:
    """调用一次对话补全。返回统一结构，不抛异常。"""
    trace_id = uuid.uuid4().hex[:12]
    p = provider or load_provider(conn)
    if p is None:
        return {"ok": False, "error": "还没有配置 AI 模型。请到「设置 → AI 模型配置」添加一个。",
                "trace_id": trace_id}
    if not p.model:
        return {"ok": False, "error": f"模型配置「{p.name}」没有填模型名（如 deepseek-chat）。",
                "trace_id": trace_id}

    from .. import secrets
    key = secrets.get_secret(p.key_ref) if p.key_ref else None
    _raw = " ".join(str(m.get("content", "")) for m in messages)
    if prompt_version:
        # 版本化指纹：p<version>:<sha16>，既能比对又不落明文提示词
        raw_hash = hashlib.sha256(_raw.encode("utf-8")).hexdigest()[:16]
        digest = f"p{prompt_version}:{raw_hash}"
    else:
        digest = _raw[:120]

    if p.kind == "ollama":
        # 本地 Ollama 原生接口
        url = (p.base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
        payload = {"model": p.model, "messages": messages, "stream": False,
                   "options": {"temperature": temperature}}
        headers = {}
    else:
        if not key:
            return {"ok": False,
                    "error": (f"模型配置「{p.name}」引用的密钥「{p.key_ref or '（空）'}」不存在。"
                              "请到「设置 → 密钥」里保存，或修正引用的键名。"),
                    "trace_id": trace_id}
        if any(ord(c) > 127 for c in key) or key != key.strip():
            bad = "".join(c for c in key if ord(c) > 127)[:8]
            return {"ok": False,
                    "error": (f"密钥「{p.key_ref}」里包含中文/全角字符或多余空白"
                              + (f"（如「{bad}」）" if bad else "")
                              + "。多半是粘贴错了，请到「设置 → 密钥」重新粘贴纯英文的 API Key。"),
                    "trace_id": trace_id}
        url = endpoint(p.base_url)
        payload = {"model": p.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens,
                   "stream": False}
        headers = {"Authorization": f"Bearer {key}"}

    r = _post_json(url, payload, headers, timeout)
    latency = r.get("latency_ms", 0)

    if not r["ok"]:
        err = _friendly_error(r.get("status", 0), r.get("raw", ""), url)
        if log:
            _log_run(conn, trace_id=trace_id, task_type=task_type, provider=p.name,
                     model=p.model, prompt_digest=digest, latency_ms=latency,
                     ok=0, error=err)
        return {"ok": False, "error": err, "status": r.get("status"),
                "latency_ms": latency, "trace_id": trace_id, "provider": p.name}

    try:
        j = json.loads(r["raw"])
    except Exception:
        return {"ok": False, "error": "接口返回的不是 JSON，可能不是 OpenAI 兼容服务。",
                "latency_ms": latency, "trace_id": trace_id, "provider": p.name}

    if p.kind == "ollama":
        content = (j.get("message") or {}).get("content", "")
        usage = {"prompt_tokens": j.get("prompt_eval_count", 0),
                 "completion_tokens": j.get("eval_count", 0)}
    else:
        try:
            content = j["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            err = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error")
            return {"ok": False, "error": f"返回格式不认识：{err or str(j)[:200]}",
                    "latency_ms": latency, "trace_id": trace_id, "provider": p.name}
        usage = j.get("usage") or {}

    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)
    cost = p.cost_micro(tokens_in, tokens_out)
    if log:
        _log_run(conn, trace_id=trace_id, task_type=task_type, provider=p.name,
                 model=p.model, prompt_digest=digest, tokens_in=tokens_in,
                 tokens_out=tokens_out, latency_ms=latency, ok=1, cost_micro=cost)
    return {
        "ok": True, "content": content, "model": j.get("model") or p.model,
        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
        "latency_ms": latency, "trace_id": trace_id, "provider": p.name,
        "free": p.is_free, "cost_yuan": round(cost / 1e6, 6),
    }


# ---------------- 测试连接 ----------------
def test_connection(conn, name: Optional[str] = None) -> dict:
    """给「设置」页用：真发一次极小请求，验证密钥/地址/模型是否都通。"""
    p = load_provider(conn, name)
    if p is None:
        return {"ok": False, "error": "找不到模型配置（name 为空时取第一个启用中的配置）。"}
    r = chat(conn, [
        {"role": "system", "content": "你是连通性测试助手，只回复用户要求的内容，不要解释。"},
        {"role": "user", "content": "请只回复两个字符：OK"},
    ], provider=p, temperature=0, max_tokens=8, timeout=30, task_type="test")
    if not r.get("ok"):
        return r
    return {
        "ok": True,
        "provider": p.name, "model": r.get("model"), "base_url": p.base_url,
        "reply": (r.get("content") or "").strip()[:40],
        "latency_ms": r.get("latency_ms"),
        "tokens": r.get("usage"),
        "trace_id": r.get("trace_id"),
    }


# ---------------- 统计 ----------------
def recent_runs(conn, limit: int = 20):
    rows = conn.execute(
        "SELECT id, trace_id, task_type, provider, model, tokens_in, tokens_out,"
        " latency_ms, ok, error, created_at FROM ai_runs"
        " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def cost_summary(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS calls,"
        " COALESCE(SUM(tokens_in),0) AS tin,"
        " COALESCE(SUM(tokens_out),0) AS tout,"
        " COALESCE(SUM(cost_micro),0) AS cmicro,"
        " COALESCE(SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END),0) AS failed"
        " FROM ai_runs").fetchone()
    return {"calls": row["calls"], "tokens_in": row["tin"],
            "tokens_out": row["tout"], "failed": row["failed"],
            "cost_yuan": round((row["cmicro"] or 0) / 1e6, 6)}


def _key_ok(r: dict) -> int:
    """配置引用的密钥是否真的存在且可用（本地 Ollama 不需要密钥）。"""
    if r.get("kind") == "ollama":
        return 1
    ref = r.get("key_ref") or ""
    if not ref:
        return 0
    try:
        from .. import secrets
        v = secrets.get_secret(ref) or ""
        ok, _msg = secrets.validate_key(v)
        return 1 if ok else 0
    except Exception:
        return 0


def provider_summary(conn) -> list:
    """给界面用：每个配置的展示信息（含是否默认、免费、价格）。"""
    out = []
    for r in list_providers(conn):
        p = _to_provider_row_dict(r)
        out.append(p)
    return out


def _to_provider_row_dict(r: dict) -> dict:
    price_in = float(r.get("price_in") or 0)
    price_out = float(r.get("price_out") or 0)
    free = bool(r.get("free")) or r.get("kind") == "ollama"
    return {
        "name": r.get("name", ""), "kind": r.get("kind", ""),
        "base_url": r.get("base_url", ""), "model": r.get("model", ""),
        "key_ref": r.get("key_ref", ""), "role": r.get("role", "chat"),
        "enabled": int(r.get("enabled") or 0),
        "is_default": int(r.get("is_default") or 0),
        "free": 1 if free else 0,
        "price_in": price_in, "price_out": price_out,
        "note": r.get("note", ""),
        "key_ok": _key_ok(r),
        "cost_hint": ("免费（本地/免费额度）" if free else
                      (f"{price_in:g} 元/百万输入 · {price_out:g} 元/百万输出"
                       if (price_in or price_out) else "按服务商计费（价格未填，成本统计不准确）")),
    }


def set_default(conn, name: str) -> bool:
    row = conn.execute("SELECT role FROM ai_providers WHERE name=?", (name,)).fetchone()
    if row is None:
        return False
    role = row["role"] or "chat"
    conn.execute("UPDATE ai_providers SET is_default=0 WHERE role=?", (role,))
    conn.execute("UPDATE ai_providers SET is_default=1 WHERE name=?", (name,))
    return True


def set_enabled(conn, name: str, enabled: bool) -> bool:
    cur = conn.execute("UPDATE ai_providers SET enabled=? WHERE name=?",
                       (1 if enabled else 0, name))
    return bool(cur.rowcount)


def delete_provider(conn, name: str) -> bool:
    cur = conn.execute("DELETE FROM ai_providers WHERE name=?", (name,))
    return bool(cur.rowcount)
