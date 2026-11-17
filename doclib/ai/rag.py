# -*- coding: utf-8 -*-
"""单次问答（RAG）：检索 top-k → 拼上下文 → 模型生成 → 引用快照入库 → 缓存。

设计要点：
- 默认用「当前默认模型」（你现在是免费的 glm-flash），可显式指定
- 只依据检索到的片段回答，强制编号引用 [1][2]，不用路径
- 引用按 A3 契约存快照（doc_id + heading_path + snippet + text_hash），重新切块后仍有效
- 相同问题+相同上下文命中 ai_cache，第二次 0 成本
"""
import hashlib
import json
from typing import Optional

from .. import citations
from ..db import now_ms
from .. import search as search_mod
from . import gateway

PROMPT_VERSION = 2
DEFAULT_TOP_K = 10
MAX_CHUNK_CHARS = 1200

SYSTEM_PROMPT = """你是个人资料库的检索助手。规则：
1. 只能依据用户提供的「资料片段」回答，不得使用片段以外的知识。
2. 回答用中文，简洁准确；先给结论，再给必要解释。
3. 每个关键结论后面用方括号标注来源编号，例如 [1]、[2][3]。
4. 如果片段不足以回答，直接说"资料中没有找到相关内容"，不要编造，也不要给出来源编号。
5. 不要输出文件路径、不要输出 Markdown 标题层级。
6. 如果问题前提不成立（例如把非周期信号说成"它的傅里叶级数"），先一句话指出前提问题，再给最接近的相关结论。
7. 资料片段若是表格或公式清单，必须逐行对照后再回答，不要凭印象补充；表里没有就明说没有。
8. 只说片段支持的内容；片段是符号写法（如 sinω0t）时，要转成中文概念（正弦）来表达。
9. 若问「某信号的傅里叶级数/展开」，而该信号在片段里属于非周期或奇异信号（如冲激、阶跃、符号函数、单边指数），
   先明确"不存在通常意义的傅里叶级数"，再给出片段中该信号的傅里叶变换或变换对表结论（若有）。
10. 若问题里的术语疑似笔误（如"矩形脉冲限号"），按最接近的正确术语（矩形脉冲信号）作答，并用一句话说明你的理解。
11. 问"性质/定理/变换对"这类清单时，按片段表格逐条列出（一行一条：名称 → 时域 → 频域），不要遗漏片段里有的条目。"""


def _cache_key(question: str, model: str, chunks) -> str:
    raw = {
        "q": question.strip(),
        "model": model,
        "pv": PROMPT_VERSION,
        "chunks": [(c["chunk_id"], citations.text_hash(c["text"])) for c in chunks],
    }
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False).encode()).hexdigest()


# 问句里的功能词/疑问词：去掉它们，剩下的才是检索词
_QUESTION_STOP = [
    "是什么", "是怎么", "怎么样", "怎么", "怎样", "如何", "为什么", "为何",
    "有哪些", "有什么", "什么样", "什么", "哪些", "哪个", "多少", "是否",
    "请告诉", "告诉我", "请", "帮我", "解释", "介绍", "说明", "描述", "讲一下",
    "讲", "一下", "关系", "区别", "联系", "区别是", "指的是", "叫做", "称为",
    "的", "了", "吗", "呢", "吧", "啊", "呀", "与", "和", "跟", "在", "里",
    "定义是", "内容是", "意思是", "证明", "推导", "举例", "例如",
    "求解", "计算", "应该", "需要", "可以", "能否", "会不会", "是否为", "怎么求",
]
_PUNCT_RE = __import__("re").compile(r"[\s，。？！、；：\"\'（）()《》<>\[\]{},.?!;:]+")


def question_terms(question: str):
    """把自然语言问句拆成检索词；拆不出来时退回通用切词。"""
    q = (question or "").strip()
    if not q:
        return []
    work = q
    for w in sorted(_QUESTION_STOP, key=len, reverse=True):
        work = work.replace(w, " ")
    fragments = [x for x in _PUNCT_RE.split(work) if x]
    terms = [f for f in fragments if len(f) >= 2]
    if not terms:
        return search_mod.parse_terms(q)
    # 长句再补一层：4 字以上片段做整词，同时保留片段本身
    out = []
    for t in terms:
        out.append(t)
    return out


# 课程领域同义词：问法用词 ↔ 教材用词
SYNONYMS = {
    # 只用「指向明确」的技术别名，避免泛词引入噪声
    "导数": ["求导", "微分"],
    "求导": ["导数", "微分"],
    "微分": ["导数", "求导"],
    "冲激": ["冲激偶", "δ"],
    "阶跃": ["单位阶跃", "u(t)"],
    "采样": ["抽样"],
    "抽样": ["采样"],
    "奈奎斯特": ["2ωm", "奈奎斯特频率"],
    "拉普拉斯": ["拉氏"],
    "傅里叶": ["傅氏"],
    "混叠": ["混叠失真"],
    # —— 依据用户真实提问补充 ——
    "共轭": ["共轭对称", "conjugate", "f*"],
    "符号函数": ["sgn"],
    "单边指数": ["指数信号", "e-at", "e^{-at}", "e-at u(t)"],
    "双边": ["双边信号", "左边信号", "右边信号"],
    "性质": ["性质表", "基本性质", "运算性质"],
    "基本性质": ["性质表", "性质"],
    "反褶": ["时间反转", "翻转", "f(-t)", "尺度变换"],
    "翻转": ["时间反转", "反褶", "f(-t)"],
    "正负": ["时间反转", "反褶", "f(-t)"],
    "取负": ["时间反转", "反褶"],
    "起点": ["支撑区间", "t1+t2", "时移"],
    "起始": ["支撑区间", "t1+t2", "时移"],
    "范围": ["支撑区间", "取值区间"],
    "限号": ["信号"],          # 常见错别字：矩形脉冲限号 → 矩形脉冲信号
    "叶级数": ["傅里叶级数"],
    "叶变换": ["傅里叶变换"],
    "判断": ["判据"],
    "怎么判断": ["判据"],
    "容易出错": ["易错", "常见错误"],
    "出错": ["易错", "常见错误"],
    "踩坑": ["易错", "常见错误"],
    "因果性": ["因果系统", "causal"],
    "因果": ["因果系统", "非因果"],
    "稳定": ["稳定性", "稳定系统"],
    "收敛域": ["ROC", "收敛域"],
    # 公式/表格里只有符号，没有中文名，补上别名才能命中
    "正弦": ["sin"],
    "余弦": ["cos"],
    "指数": ["ej", "e(j", "e^"],
    "单位冲激": ["δ(t)"],
    "单位阶跃": ["u(t)"],
    "方波": ["矩形脉冲", "rect"],
    "矩形脉冲": ["rect", "Sa"],
    "傅里叶变换对": ["变换对", "F(ω)"],
    "傅里叶变换": ["变换对", "F(ω)"],
}


def expand_terms(terms):
    """给检索词补充领域同义词。

    两级：①整词命中  ②子串命中（「正弦信号」含「正弦」→ 补 sin）
    只用于关键词/标题通道，不改变原词。
    """
    out = list(terms)
    seen = set(out)
    for t in terms:
        for syn in SYNONYMS.get(t, []):          # ① 整词
            if syn and syn not in seen:
                seen.add(syn)
                out.append(syn)
        for key, syns in SYNONYMS.items():       # ② 子串
            if key != t and key in t:
                for syn in syns:
                    if syn and syn not in seen:
                        seen.add(syn)
                        out.append(syn)
                # ③ 错别字纠正：把 key 替换成规范词，得到整词（如 矩形脉冲限号 → 矩形脉冲信号）
                for syn in syns:
                    fixed = t.replace(key, syn)
                    if fixed and fixed != t and fixed not in seen:
                        seen.add(fixed)
                        out.append(fixed)
    return out


def _maximal_terms(terms):
    """去掉是其它词子串的片段（"叶级数" 是 "傅里叶级数" 的子串 → 丢掉）。"""
    uniq = list(dict.fromkeys(t for t in terms if t))
    out = []
    for t in uniq:
        if any(t != u and t in u for u in uniq):
            continue
        out.append(t)
    return out


def _heading_vocab(conn) -> str:
    """所有章节标题拼成的大串（用于判断某个词/片段是否出现在标题里）。"""
    try:
        return " ".join((r[0] or "") for r in conn.execute(
            "SELECT heading_path FROM doc_chunks"))
    except Exception:
        return ""


def _head_terms(terms, vocab: str):
    """把中文长句切成能在标题里找到的 2~3 字片段。

    「系数衰减得快慢跟波形光不光滑」→ 系数衰减 / 波形 / 光滑 …
    """
    out = []
    for t in terms:
        if len(t) >= 2 and t in vocab:
            out.append(t)
        if len(t) >= 4:
            for n in (3, 2):
                for i in range(len(t) - n + 1):
                    g = t[i:i + n]
                    if g in vocab and g not in out:
                        out.append(g)
    return out


_TABLE_WORDS = ("性质", "变换对", "对偶", "共轭", "速查", "表", "定理", "公式", "对照")
_HINT_RULES = (
    # (问题里必须出现的词, 标题里出现的词, 加分)
    (("冲激",), ("周期信号的傅里叶变换", "典型信号三种变换结果对照"), 0.16),
    (("符号函数", "阶跃"), ("阶跃信号与符号函数", "典型信号三种变换结果对照"), 0.10),
    (("对称性",), ("对称性判据", "波形对称性与谐波"), 0.12),
    (("易错", "常见错误", "出错", "踩坑"), ("易错", "常见错误", "注意"), 0.12),
)
_GENERIC_TERMS = ("基本性质", "性质表", "运算性质", "性质", "变换对", "定理", "公式",
                  "表", "影响", "结果", "范围", "对照", "关系")
_TRANSFORM_NAMES = ("傅里叶变换", "傅里叶级数", "拉普拉斯变换", "拉普拉斯", "z变换", "Z变换",
                    "傅氏", "拉氏", "叶级数", "叶变换")


def _wants_table(terms, query: str) -> bool:
    """问的是"性质/变换对/速查/定理"这类条目 → 表格块更有价值。"""
    q = query or ""
    if any(w in q for w in _TABLE_WORDS):
        return True
    return any(w in t for t in terms for w in _TABLE_WORDS)


def _is_tableish(text: str) -> bool:
    """粗判表格：出现 ≥3 个 ' | ' 分隔或 ≥3 行含竖线。"""
    if not text:
        return False
    if text.count(" | ") >= 3:
        return True
    return sum(1 for ln in text.splitlines() if "|" in ln) >= 3


def _chunk_candidates(conn, query: str, node_id=None, scope: str = "subtree",
                      limit: int = 5):
    """块级混合检索：关键词 + 语义，RRF 融合，返回块列表（同一文档可有多个块）。

    这是问答质量的关键：按文档去重会把「3.1 卷积定理」这类小块挤掉。
    """
    terms = question_terms(query)
    if not terms:
        return []
    kw_terms = expand_terms(terms)          # 领域同义词扩展
    vocab = _heading_vocab(conn)
    h_terms = _head_terms(kw_terms, vocab) or kw_terms
    h_long = _maximal_terms([t for t in h_terms if len(t) >= 3])   # 只保留最长片段
    scope_ids = search_mod.tree.node_doc_ids(conn, node_id, scope)

    # 关键词通道
    kw_order = []
    long_terms = [t for t in kw_terms if len(t) >= 3]
    short_terms = [t for t in kw_terms if len(t) < 3]
    if long_terms:
        fts_q = " OR ".join('"%s"' % t.replace('"', '""') for t in long_terms)
        try:
            kw_order += [r[0] for r in conn.execute(
                "SELECT dc.id FROM chunk_fts JOIN doc_chunks dc ON dc.id = chunk_fts.rowid "
                "WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts) LIMIT 300",
                (fts_q,)).fetchall()]
        except Exception:
            pass
    for t in short_terms:
        pat = f"%{search_mod._like_escape(t)}%"
        try:
            kw_order += [r[0] for r in conn.execute(
                "SELECT id FROM doc_chunks WHERE (text LIKE ? ESCAPE '\\' "
                "OR heading_path LIKE ? ESCAPE '\\') LIMIT 200", (pat, pat)).fetchall()]
        except Exception:
            pass

    # 语义通道
    sem_order = []
    try:
        from . import embedder, vectors
        if embedder.available()["ok"] and vectors.available(conn) and vectors.count(conn) > 0:
            qv = embedder.embed_query(query)
            if qv:
                sem_order = [cid for cid, _d in vectors.search(conn, qv, k=60)]
    except Exception:
        pass

    # RRF（与 search() 同口径）
    K = 60
    fused = {}
    for rank, cid in enumerate(dict.fromkeys(kw_order)):
        fused[cid] = fused.get(cid, 0.0) + 0.7 / (K + rank + 1)
    for rank, cid in enumerate(sem_order):
        fused[cid] = fused.get(cid, 0.0) + 0.3 / (K + rank + 1)
    if not fused:
        return []

    # 标题稀有度加分（与 search() 一致）
    ordered = sorted(fused.items(), key=lambda x: -x[1])[:200]
    ids = [cid for cid, _ in ordered]
    qs = ",".join("?" * len(ids))
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT c.id, c.doc_id, c.heading_path, c.text, d.title, d.quality, "
        f"d.deleted_at FROM doc_chunks c JOIN documents d ON d.id=c.doc_id "
        f"WHERE c.id IN ({qs})", ids)}
    scored = []
    for cid, sc in ordered:
        r = rows.get(cid)
        if r is None or r["deleted_at"] is not None:
            continue
        if scope_ids is not None and r["doc_id"] not in scope_ids:
            continue
        rarity = search_mod.heading_rarity(conn, kw_terms, r["heading_path"])
        boost = 60.0 * rarity / 1000.0 if rarity else 0.0
        # 标题命中多个查询词 → 更贴题（如「傅里叶变换」+「性质」）
        hp = (r["heading_path"] or "").lower()
        matched = sum(1 for t in h_long if t and t.lower() in hp)
        if matched >= 2:
            boost += 0.02 * min(matched, 4)
        # 表格块加分（性质表/变换对/速查表）
        if _wants_table(h_terms, query) and _is_tableish(r["text"]):
            boost += 0.035
        # 实义词（如「符号函数」「矩形脉冲」）出现在标题里 → 强加分
        _ent = [t for t in h_long
                if t not in _TRANSFORM_NAMES and t not in _GENERIC_TERMS]
        _ent_hits = sum(1 for t in _ent if t in hp)
        if _ent_hits:
            boost += min(0.15 * _ent_hits, 0.30)
        # 领域提示规则（例：冲激函数的"级数"其实问的是周期信号的变换/对照表）
        for _qk, _hk, _bonus in _HINT_RULES:
            if all(w in (query or "") for w in _qk):
                if any(w in (r["heading_path"] or "") for w in _hk):
                    boost += _bonus
                    break
        # 查询指定的变换名出现在标题里 → 强加分
        _q_tn = [tn for tn in _TRANSFORM_NAMES if tn in (query or "")]
        _h_hit = [tn for tn in _q_tn if tn in (r["heading_path"] or "")]
        if _h_hit:
            boost += 0.03
        # 标题讲的是"另一个变换/别的东西"（如问傅里叶、标题是卷积）→ 降权
        _other = [w for w in ("卷积", "拉普拉斯", "z变换", "Z变换") if w in (r["heading_path"] or "")]
        if _q_tn and _other and not any(w in (query or "") for w in _other):
            boost -= 0.08
        total = sc + boost
        total *= (0.75 + 0.25 * max(0.0, min(1.0, float(r["quality"] or 1.0))))
        scored.append((total, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for total, r in scored[:limit]:
        out.append({
            "chunk_id": r["id"], "doc_id": r["doc_id"], "title": r["title"],
            "heading_path": r["heading_path"], "text": r["text"],
            "score": round(total * 1000, 2),
        })
    return out


def _build_context(rows):
    parts = []
    for i, r in enumerate(rows, 1):
        head = f"《{r['title']}》"
        if r.get("heading_path"):
            head += f" › {r['heading_path']}"
        text = (r["text"] or "")[:MAX_CHUNK_CHARS]
        parts.append(f"[{i}] {head}\n{text}")
    return "\n\n".join(parts)


def _get_or_create_conversation(conn, title: str, node_id=None) -> int:
    row = conn.execute(
        "SELECT id FROM conversations WHERE title=? ORDER BY id DESC LIMIT 1",
        (title,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO conversations(title, node_id, created_at, updated_at) VALUES(?,?,?,?)",
        (title, node_id, now_ms(), now_ms()))
    return cur.lastrowid


def ask(conn, question: str, node_id: Optional[int] = None, scope: str = "subtree",
        provider_name: Optional[str] = None, top_k: int = DEFAULT_TOP_K,
        max_tokens: int = 900, timeout: int = 60,
        conversation_id: Optional[int] = None) -> dict:
    """问答主入口。返回统一结构，不抛异常。"""
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error": "问题不能为空"}

    # 1) 检索：追问时把上一轮问题也拼进去，让「那余弦呢」这类省略句也能搜到料
    retrieval_query = question
    if conversation_id:
        try:
            prev = conn.execute(
                "SELECT content FROM messages WHERE conversation_id=? AND role='user' "
                "ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
            if prev and prev["content"]:
                retrieval_query = prev["content"][:80] + " " + question
        except Exception:
            pass
    chunks = _chunk_candidates(conn, retrieval_query, node_id, scope, top_k)
    r = {"mode": "chunk-hybrid"}

    # 1b) 兜底：块级没结果时退回文档级检索
    if not chunks:
        rd = search_mod.search(conn, question, node_id, scope, limit=top_k)
        r["mode"] = rd.get("mode")
        for h in rd["results"][:top_k]:
            c = search_mod.chunk_text(conn, h["chunk_id"]) if h.get("chunk_id") else None
            if c:
                chunks.append({
                    "chunk_id": c["id"], "doc_id": c["doc_id"], "title": c["doc_title"],
                    "heading_path": c["heading_path"], "text": c["text"],
                    "score": h.get("score", 0), "semantic": h.get("semantic", False),
                })
    if not chunks:
        return {"ok": False, "error": "资料库里没有检索到相关内容，换个说法或扩大范围试试。",
                "mode": r.get("mode")}

    # 3) 模型
    prov = gateway.load_provider(conn, provider_name or None)
    if prov is None:
        return {"ok": False, "error": "还没有配置 AI 模型，请到「设置 → AI 模型配置」添加。"}

    # 4) 缓存
    key = _cache_key(question, f"{prov.name}:{prov.model}", chunks)
    cached = conn.execute(
        "SELECT content FROM ai_cache WHERE task_type='qa' AND cache_key=?",
        (key,)).fetchone()

    if cached:
        payload = json.loads(cached["content"])
        payload["cached"] = True
    else:
        user_msg = f"问题：{question}\n\n资料片段：\n{_build_context(chunks)}"
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if conversation_id:
            try:
                hist = conn.execute(
                    "SELECT role, content FROM messages WHERE conversation_id=? "
                    "ORDER BY id DESC LIMIT 6", (conversation_id,)).fetchall()
                for h in reversed(hist):
                    if h["content"]:
                        msgs.append({"role": h["role"], "content": h["content"][:1500]})
            except Exception:
                pass
        msgs.append({"role": "user", "content": user_msg})
        res = gateway.chat(conn, msgs, provider=prov, temperature=0.2,
                           max_tokens=max_tokens, timeout=timeout, task_type="qa")
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error", "模型调用失败"),
                    "provider": prov.name}
        payload = {
            "answer": res.get("content", ""),
            "model": res.get("model"),
            "provider": prov.name,
            "usage": res.get("usage", {}),
            "cost_yuan": res.get("cost_yuan", 0),
            "latency_ms": res.get("latency_ms", 0),
            "trace_id": res.get("trace_id"),
        }
        try:
            conn.execute(
                "INSERT INTO ai_cache(task_type, cache_key, model, content, created_at) "
                "VALUES('qa',?,?,?,?) ON CONFLICT(task_type, cache_key) DO NOTHING",
                (key, f"{prov.name}:{prov.model}",
                 json.dumps(payload, ensure_ascii=False), now_ms()))
        except Exception:
            pass
        payload["cached"] = False

    # 5) 引用：只保存回答里真正引用到的编号
    answer = payload.get("answer") or ""
    cited_idx = sorted({int(x) for x in __import__("re").findall(r"\[(\d+)\]", answer)
                        if 1 <= int(x) <= len(chunks)})
    use_idx = cited_idx or list(range(1, min(3, len(chunks)) + 1))

    if conversation_id:
        conv_id = int(conversation_id)
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?",
                     (now_ms(), conv_id))
    else:
        conv_id = _get_or_create_conversation(conn, question[:24] or "新对话", node_id)
    try:
        n_msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conv_id,)).fetchone()[0]
        if n_msgs == 0:
            conn.execute("UPDATE conversations SET title=? WHERE id=?",
                         (question[:24], conv_id))
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, model, trace_id, created_at)"
            " VALUES(?,'user',?,'','',?)", (conv_id, question, now_ms()))
    except Exception:
        pass
    msg_id = conn.execute(
        "INSERT INTO messages(conversation_id, role, content, model, trace_id, created_at) "
        "VALUES(?,'assistant',?,?,?,?)",
        (conv_id, answer, payload.get("model") or prov.model,
         payload.get("trace_id") or "", now_ms())).lastrowid

    snaps, scores = [], []
    for i in use_idx:
        c = chunks[i - 1]
        snaps.append({
            "doc_id": c["doc_id"], "doc_title": c["title"],
            "heading_path": c["heading_path"],
            "snippet": (c["text"] or "")[:citations.SNIPPET_LEN].replace("\n", " "),
            "text_hash": citations.text_hash(c["text"]),
            "chunk_id": c["chunk_id"],
        })
        scores.append(c.get("score", 0))
    citations.save_citations(conn, msg_id, snaps, scores)

    sources = []
    for i in use_idx:
        c = chunks[i - 1]
        sources.append({
            "index": i, "doc_id": c["doc_id"], "title": c["title"],
            "heading_path": c["heading_path"],
            "snippet": (c["text"] or "")[:160].replace("\n", " "),
            "score": c.get("score", 0), "chunk_id": c["chunk_id"],
        })

    return {
        "ok": True,
        "answer": answer,
        "sources": sources,
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "usage": payload.get("usage", {}),
        "cost_yuan": payload.get("cost_yuan", 0),
        "latency_ms": payload.get("latency_ms", 0),
        "cached": payload.get("cached", False),
        "mode": r.get("mode"),
        "message_id": msg_id,
        "conversation_id": conv_id,
        "trace_id": payload.get("trace_id"),
    }
