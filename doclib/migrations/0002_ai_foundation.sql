-- 0002：接入 AI 之前的地基
-- A1 解析管线版本（可以随时重建索引）
-- A2 解析质量分（识别差的文档要能被看见/降权）
-- A3 对话与引用契约（引用存快照，不依赖 chunk_id）
-- A4 AI 供应商配置（密钥单独加密存，不进数据库）

-- ---------- A1 ----------
ALTER TABLE documents ADD COLUMN parse_version INTEGER NOT NULL DEFAULT 0;

-- ---------- A2 ----------
ALTER TABLE documents ADD COLUMN quality     REAL    NOT NULL DEFAULT 1.0;
ALTER TABLE documents ADD COLUMN quality_note TEXT   NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_doc_quality ON documents(quality);

-- ---------- A4：供应商配置（密钥只存引用名，密文在 data/secrets.bin）----------
CREATE TABLE IF NOT EXISTS ai_providers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    kind       TEXT    NOT NULL DEFAULT 'openai_compatible',  -- openai_compatible | ollama
    base_url   TEXT    NOT NULL DEFAULT '',
    model      TEXT    NOT NULL DEFAULT '',
    key_ref    TEXT    NOT NULL DEFAULT '',                   -- secrets 里的键名
    role       TEXT    NOT NULL DEFAULT 'chat',               -- chat | embed | rerank
    enabled    INTEGER NOT NULL DEFAULT 1,
    extra_json TEXT    NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- ---------- A3：对话与引用快照 ----------
-- 契约：引用只以 (doc_id + heading_path + 文本快照 + 文本哈希) 为准；
--       chunk_id 仅作调试线索，重新切块后历史引用依然成立。
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL DEFAULT '',
    node_id    INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT    NOT NULL,            -- user | assistant | system
    content         TEXT    NOT NULL,
    model           TEXT    NOT NULL DEFAULT '',
    trace_id        TEXT    NOT NULL DEFAULT '',
    created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS message_citations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    doc_id       INTEGER NOT NULL,                -- 故意不加外键：文档删了，历史引用也要留
    heading_path TEXT    NOT NULL DEFAULT '',
    snippet      TEXT    NOT NULL DEFAULT '',     -- 引用当时的正文快照（前 80 字）
    text_hash    TEXT    NOT NULL DEFAULT '',     -- 引用当时 chunk 文本 sha1
    score        REAL    NOT NULL DEFAULT 0,
    chunk_id     INTEGER,                         -- 仅调试线索，不作唯一标识
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cita_msg ON message_citations(message_id);
CREATE INDEX IF NOT EXISTS idx_cita_doc ON message_citations(doc_id);
