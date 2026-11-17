-- 0005：会话管理（顶置 / 收藏 / 标签）
ALTER TABLE conversations ADD COLUMN pinned   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN tags     TEXT    NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_conv_order
    ON conversations(pinned DESC, favorite DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_conv
    ON messages(conversation_id, id);
