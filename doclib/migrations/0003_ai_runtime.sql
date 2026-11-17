-- 0003：AI 运行时
-- ai_runs：每一次模型调用都留痕（模型、耗时、token、成败、报错），用于排查与成本统计
-- ai_cache：同样的请求不重复花钱（后续问答/摘要复用）

CREATE TABLE IF NOT EXISTS ai_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id      TEXT    NOT NULL DEFAULT '',
    task_type     TEXT    NOT NULL DEFAULT 'chat',   -- test | chat | embed | rerank
    provider      TEXT    NOT NULL DEFAULT '',
    model         TEXT    NOT NULL DEFAULT '',
    prompt_digest TEXT    NOT NULL DEFAULT '',       -- 前 120 字，供审计（不含密钥）
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost_micro    INTEGER NOT NULL DEFAULT 0,        -- 微元，避免浮点
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL DEFAULT 1,
    error         TEXT    NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_air_time ON ai_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_air_type ON ai_runs(task_type, created_at);

CREATE TABLE IF NOT EXISTS ai_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type  TEXT    NOT NULL,
    cache_key  TEXT    NOT NULL,      -- sha256(task_type + model + 输入 + 版本)
    model      TEXT    NOT NULL DEFAULT '',
    content    TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (task_type, cache_key)
);
