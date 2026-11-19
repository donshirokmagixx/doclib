# -*- coding: utf-8 -*-
"""本地假模型（仅开发/E2E 用）：OpenAI 兼容 /v1/chat/completions。

不参与打包；用于验证 DocLib 的上下文传递、引用与 UI，不消耗真实 API。
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "DocLibFakeLLM/0.1"

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            req = {}
        system = ""
        user = ""
        for m in req.get("messages", []):
            if m.get("role") == "system":
                system = m.get("content") or ""
            if m.get("role") == "user":
                user = m.get("content") or ""
        answer = (
            "（本地假模型回答）我依据本次请求提供的资料范围作答。\n\n"
            "DFT 是定义在有限长离散序列上的变换，把 N 个时域样本映射为 N 个频域系数；"
            "FFT 是计算 DFT 的一类快速算法，把 O(N²) 降到 O(N log N) [1]。\n\n"
            "为避免误导：如果你切换了中央内容，请以右侧“范围”显示的实际检索范围为准；"
            "本轮回答只基于该范围的片段 [1]。\n\n"
            f"（调试：system={len(system)} 字，user={len(user)} 字）"
        )
        payload = {
            "id": "fake-chat",
            "object": "chat.completion",
            "model": req.get("model") or "fake-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8799), Handler).serve_forever()
