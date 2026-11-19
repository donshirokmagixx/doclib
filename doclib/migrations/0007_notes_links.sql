-- 0007: Markdown notes + wikilinks/backlinks
-- 笔记是真值层（DB 内 Markdown）；note_chunks 是派生检索层；note_links 是解析后的链接。

CREATE TABLE IF NOT EXISTS notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    body_md      TEXT NOT NULL DEFAULT '',
    node_id      INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    partition_id INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    deleted_at   INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_note_title
    ON notes(title COLLATE NOCASE) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_note_node
    ON notes(node_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_note_part
    ON notes(partition_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS note_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    ord          INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    text         TEXT NOT NULL,
    char_len     INTEGER NOT NULL,
    UNIQUE(note_id, ord)
);
CREATE INDEX IF NOT EXISTS idx_note_chunk ON note_chunks(note_id);

CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
    heading_path, text,
    content='note_chunks', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS trg_note_ai AFTER INSERT ON note_chunks BEGIN
    INSERT INTO note_fts(rowid, heading_path, text) VALUES (new.id, new.heading_path, new.text);
END;
CREATE TRIGGER IF NOT EXISTS trg_note_ad AFTER DELETE ON note_chunks BEGIN
    INSERT INTO note_fts(note_fts, rowid, heading_path, text)
    VALUES('delete', old.id, old.heading_path, old.text);
END;
CREATE TRIGGER IF NOT EXISTS trg_note_au AFTER UPDATE ON note_chunks BEGIN
    INSERT INTO note_fts(note_fts, rowid, heading_path, text)
    VALUES('delete', old.id, old.heading_path, old.text);
    INSERT INTO note_fts(rowid, heading_path, text) VALUES (new.id, new.heading_path, new.text);
END;

CREATE TABLE IF NOT EXISTS note_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_kind  TEXT CHECK (target_kind IN ('node','document','note') OR target_kind IS NULL),
    target_id    INTEGER,
    target_title TEXT NOT NULL DEFAULT '',
    heading      TEXT NOT NULL DEFAULT '',
    alias        TEXT NOT NULL DEFAULT '',
    start_off    INTEGER NOT NULL DEFAULT 0,
    end_off      INTEGER NOT NULL DEFAULT 0,
    resolved     INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nl_note ON note_links(note_id);
CREATE INDEX IF NOT EXISTS idx_nl_target ON note_links(target_kind,target_id);
