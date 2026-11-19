# -*- coding: utf-8 -*-
"""提示词仓库：正文放在 prompts/*.txt，改提示词不用改代码。

版本规则：改提示词 → 升 PROMPT_VERSION；rag 会把版本写进 ai_runs.prompt_digest
（格式 p<version>:<sha16>），便于按版本对比效果。
"""
import hashlib
import sys
from pathlib import Path

PROMPT_VERSION = "4"


def _candidates():
    yield Path(__file__).resolve().with_name("prompts") / "qa_v4.txt"
    base = getattr(sys, "_MEIPASS", "")
    if base:
        yield Path(base) / "ai" / "prompts" / "qa_v4.txt"
    # 回退：旧包/旧部署只有 v3
    yield Path(__file__).resolve().with_name("prompts") / "qa_v3.txt"
    if base:
        yield Path(base) / "ai" / "prompts" / "qa_v3.txt"


def load_qa_prompt() -> str:
    for p in _candidates():
        try:
            text = p.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            continue
    return DEFAULT_QA_PROMPT


def prompt_digest(prompt_version: str = None) -> str:
    """ai_runs.prompt_digest 用的版本化指纹（不落明文提示词）。"""
    v = prompt_version or PROMPT_VERSION
    h = hashlib.sha256(load_qa_prompt().encode("utf-8")).hexdigest()[:16]
    return f"p{v}:{h}"


DEFAULT_QA_PROMPT = """你是个人资料库的检索助手。规则：
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
11. 问"性质/定理/变换对"这类清单时，按片段表格逐条列出（一行一条：名称 → 时域 → 频域），不要遗漏片段里有的条目。
12. 每个结论都必须带 [n] 引用；如果没有任何片段可引用，直接回答「资料中没有找到相关内容」，不要编造编号或出处。"""
