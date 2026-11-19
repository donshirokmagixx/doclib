-- 0006: knowledge graph relations + AI context + citation anchors
-- 真值层不复制树/挂载；图谱 API 联查 nodes.parent_id 与 node_documents。

-- ---------- AI 上下文（每轮可复现） ----------
ALTER TABLE messages      ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE conversations ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}';

-- ---------- 引用快照升级：document / note / selection ----------
ALTER TABLE message_citations ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'document';
ALTER TABLE message_citations ADD COLUMN note_id     INTEGER;
ALTER TABLE message_citations ADD COLUMN doc_title   TEXT NOT NULL DEFAULT '';
ALTER TABLE message_citations ADD COLUMN page        INTEGER;
ALTER TABLE message_citations ADD COLUMN start_off   INTEGER;
ALTER TABLE message_citations ADD COLUMN end_off     INTEGER;
ALTER TABLE message_citations ADD COLUMN quote       TEXT NOT NULL DEFAULT '';

-- ---------- 阅读定位（PDF 页号；Office 可空） ----------
ALTER TABLE doc_chunks ADD COLUMN page      INTEGER;
ALTER TABLE doc_chunks ADD COLUMN start_off INTEGER;
ALTER TABLE doc_chunks ADD COLUMN end_off   INTEGER;

-- ---------- 人工 / AI 关系（多态实体） ----------
CREATE TABLE IF NOT EXISTS relations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    src_kind      TEXT NOT NULL CHECK (src_kind IN ('node','document','note')),
    src_id        INTEGER NOT NULL,
    dst_kind      TEXT NOT NULL CHECK (dst_kind IN ('node','document','note')),
    dst_id        INTEGER NOT NULL,
    rel           TEXT NOT NULL DEFAULT 'related',
    label         TEXT NOT NULL DEFAULT '',
    origin        TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual','ai','import')),
    confidence    REAL NOT NULL DEFAULT 1.0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    deleted_at    INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rel
    ON relations(src_kind,src_id,dst_kind,dst_id,rel,origin)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rel_src
    ON relations(src_kind,src_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_rel_dst
    ON relations(dst_kind,dst_id) WHERE deleted_at IS NULL;
