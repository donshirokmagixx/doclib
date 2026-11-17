-- 0004：模型可选（免费 / 付费），并能算钱
-- 需求：AI 接口可自由选择——接免费模型（本地 Ollama、免费额度）或按 token 计费的模型

ALTER TABLE ai_providers ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0;  -- 当前默认模型（按 role 各一个）
ALTER TABLE ai_providers ADD COLUMN free       INTEGER NOT NULL DEFAULT 0;  -- 1 = 免费（本地/免费额度）
ALTER TABLE ai_providers ADD COLUMN price_in   REAL    NOT NULL DEFAULT 0;  -- 元 / 百万 tokens（输入）
ALTER TABLE ai_providers ADD COLUMN price_out  REAL    NOT NULL DEFAULT 0;  -- 元 / 百万 tokens（输出）
ALTER TABLE ai_providers ADD COLUMN note       TEXT    NOT NULL DEFAULT ''; -- 备注：从哪来的、免费额度多少

CREATE INDEX IF NOT EXISTS idx_ai_prov_default
    ON ai_providers(role, is_default, enabled);
