-- DocLib v0.1 schema
-- 设计原则：真值层（nodes / documents / node_documents）与派生层（doc_chunks / 联想）分离，
--          所有删除为软删除，所有写操作可追溯。

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ============ 真值层 ============
CREATE TABLE IF NOT EXISTS nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id       INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    keywords        TEXT    NOT NULL DEFAULT '[]',   -- JSON 数组
    color           TEXT    NOT NULL DEFAULT '',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    path            TEXT    NOT NULL,                -- 物化路径 '/1/7/23/'
    depth           INTEGER NOT NULL DEFAULT 0,
    search_scope    TEXT    NOT NULL DEFAULT 'subtree'
                            CHECK (search_scope IN ('self','subtree','all')),
    association_on  INTEGER NOT NULL DEFAULT 0,      -- 联想开关（v0.3 使用）
    derived_version INTEGER NOT NULL DEFAULT 0,      -- 派生结果对应的 library_version
    is_system       INTEGER NOT NULL DEFAULT 0,      -- 1 = 未分类
    is_expanded     INTEGER NOT NULL DEFAULT 1,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    deleted_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_nodes_path   ON nodes(path)       WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    file_path     TEXT    NOT NULL,
    path_key      TEXT    NOT NULL,                  -- 规范化路径（小写）
    file_hash     TEXT    NOT NULL DEFAULT '',
    file_size     INTEGER NOT NULL DEFAULT 0,
    file_mtime    INTEGER NOT NULL DEFAULT 0,
    file_type     TEXT    NOT NULL DEFAULT 'docx',
    parse_status  INTEGER NOT NULL DEFAULT 0,        -- 0待解析 2成功 3失败
    parse_note    TEXT    NOT NULL DEFAULT '',
    char_count    INTEGER NOT NULL DEFAULT 0,
    cloud_allowed INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    deleted_at    INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_path ON documents(path_key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_doc_hash ON documents(file_hash);

CREATE TABLE IF NOT EXISTS node_documents (
    node_id     INTEGER NOT NULL REFERENCES nodes(id)     ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    weight      REAL    NOT NULL DEFAULT 1.0,
    note        TEXT    NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (node_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_nd_doc ON node_documents(document_id);

-- ============ 派生层 ============
CREATE TABLE IF NOT EXISTS doc_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord          INTEGER NOT NULL,
    heading_path TEXT    NOT NULL DEFAULT '',
    text         TEXT    NOT NULL,
    char_len     INTEGER NOT NULL,
    is_table     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (doc_id, ord)
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON doc_chunks(doc_id);

-- 中文检索：trigram 分词，支持任意中文子串（>=3 字）；<3 字由 LIKE 兜底
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    heading_path, text,
    content='doc_chunks', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS trg_chunk_ai AFTER INSERT ON doc_chunks BEGIN
    INSERT INTO chunk_fts(rowid, heading_path, text) VALUES (new.id, new.heading_path, new.text);
END;
CREATE TRIGGER IF NOT EXISTS trg_chunk_ad AFTER DELETE ON doc_chunks BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, heading_path, text)
    VALUES('delete', old.id, old.heading_path, old.text);
END;
CREATE TRIGGER IF NOT EXISTS trg_chunk_au AFTER UPDATE ON doc_chunks BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, heading_path, text)
    VALUES('delete', old.id, old.heading_path, old.text);
    INSERT INTO chunk_fts(rowid, heading_path, text) VALUES (new.id, new.heading_path, new.text);
END;

-- ============ 审计层 ============
CREATE TABLE IF NOT EXISTS op_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    op         TEXT    NOT NULL,
    entity     TEXT    NOT NULL DEFAULT '',
    entity_id  INTEGER,
    payload    TEXT    NOT NULL DEFAULT '{}',
    inverse    TEXT    NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

-- ============ 预留（v0.3 联想，现在建空表让升级零成本）============
CREATE TABLE IF NOT EXISTS node_associations (
    node_id    INTEGER NOT NULL REFERENCES nodes(id)     ON DELETE CASCADE,
    doc_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    score      REAL    NOT NULL DEFAULT 0,
    reason     TEXT    NOT NULL DEFAULT '',
    state      INTEGER NOT NULL DEFAULT 1,   -- 0候选 1已采纳 2已忽略 3已钉住
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (node_id, doc_id)
);
