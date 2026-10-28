-- 0003_fase2: cupons, promoções com janela e agregado de avaliações.
-- Convencoes: dinheiro em centavos (INTEGER), datas em ISO-8601 UTC (TEXT).
-- Nada aqui e "validado" por definicao: `last_verified_at` nulo significa que
-- apenas a fonte declarou o dado.

CREATE TABLE IF NOT EXISTS coupon (
    id                 TEXT PRIMARY KEY,
    store_id           TEXT NOT NULL REFERENCES store (id) ON DELETE CASCADE,
    code               TEXT NOT NULL,
    kind               TEXT NOT NULL,
    value              INTEGER NOT NULL,
    min_purchase_cents INTEGER,
    max_discount_cents INTEGER,
    currency           TEXT NOT NULL DEFAULT 'BRL',
    valid_from         TEXT,
    valid_until        TEXT,
    source             TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    collected_at       TEXT NOT NULL,
    last_verified_at   TEXT,
    confidence         REAL NOT NULL DEFAULT 0.5
);

CREATE INDEX IF NOT EXISTS idx_coupon_store ON coupon (store_id);
CREATE INDEX IF NOT EXISTS idx_coupon_code ON coupon (code);

-- Log append-only das simulacoes locais (`method = 'local_rules'`).
-- Nao substitui validacao na loja: registra apenas o que calculamos.
CREATE TABLE IF NOT EXISTS coupon_validation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id           TEXT NOT NULL REFERENCES coupon (id) ON DELETE CASCADE,
    method              TEXT NOT NULL,
    applicable          INTEGER NOT NULL,
    reason              TEXT NOT NULL,
    checked_price_cents INTEGER,
    checked_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coupon_validation_coupon
    ON coupon_validation (coupon_id, checked_at);

CREATE TABLE IF NOT EXISTS promotion (
    id           TEXT PRIMARY KEY,
    offer_id     TEXT NOT NULL REFERENCES offer (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    label        TEXT,
    starts_at    TEXT,
    ends_at      TEXT,
    source       TEXT NOT NULL,
    source_url   TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    confidence   REAL NOT NULL DEFAULT 0.5
);

CREATE INDEX IF NOT EXISTS idx_promotion_offer ON promotion (offer_id);
CREATE INDEX IF NOT EXISTS idx_promotion_window ON promotion (ends_at);

-- Fase 2 guarda apenas o agregado publicado pela fonte (sem texto individual).
-- A loja faz parte da identidade: lojas diferentes publicam agregados diferentes
-- para o mesmo produto.
CREATE TABLE IF NOT EXISTS review_summary (
    id                TEXT PRIMARY KEY,
    product_id        TEXT NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    store_id          TEXT NOT NULL REFERENCES store (id) ON DELETE CASCADE,
    rating_avg        REAL NOT NULL,
    rating_count      INTEGER NOT NULL,
    distribution_json TEXT NOT NULL DEFAULT '{}',
    source            TEXT NOT NULL,
    source_url        TEXT NOT NULL,
    collected_at      TEXT NOT NULL,
    last_verified_at  TEXT,
    confidence        REAL NOT NULL DEFAULT 0.5,
    UNIQUE (product_id, store_id, source)
);

CREATE INDEX IF NOT EXISTS idx_review_summary_product ON review_summary (product_id);
CREATE INDEX IF NOT EXISTS idx_review_summary_store ON review_summary (store_id);
