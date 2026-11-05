-- 0005_reviews: linhas individuais de avaliacao declaradas pela fonte.
--
-- Apenas feeds JSON/fixture fornecem textos; APIs oficiais usadas hoje nao
-- expoem avaliacao individual. O autor nao e armazenado (minimizacao de PII)
-- e o texto e tratado como declaracao da fonte, nunca como fato validado.
--
-- `id` e estavel a partir do produto, loja, fonte, nota, data e conteudo.
-- Recoletar o mesmo feed e idempotente. A exclusao do agregado (ou do produto)
-- remove os textos em cascata.

CREATE TABLE IF NOT EXISTS review_text (
    id               TEXT PRIMARY KEY,
    review_id        TEXT NOT NULL REFERENCES review_summary (id) ON DELETE CASCADE,
    product_id       TEXT NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    store_id         TEXT NOT NULL REFERENCES store (id) ON DELETE CASCADE,
    rating           INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title            TEXT NOT NULL DEFAULT '',
    body             TEXT NOT NULL,
    reviewed_at      TEXT,
    source           TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    collected_at     TEXT NOT NULL,
    last_verified_at TEXT,
    confidence       REAL NOT NULL DEFAULT 0.5
);

CREATE INDEX IF NOT EXISTS idx_review_text_review ON review_text (review_id);
CREATE INDEX IF NOT EXISTS idx_review_text_product ON review_text (product_id, reviewed_at DESC);
