-- 0002_mvp: entidades do MVP (catalogo, ofertas, historico e alertas).
-- Convencoes: dinheiro em centavos (INTEGER), datas em ISO-8601 UTC (TEXT).

CREATE TABLE IF NOT EXISTS store (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    domain        TEXT,
    reputation    REAL,
    source        TEXT NOT NULL DEFAULT 'unknown',
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seller (
    id            TEXT PRIMARY KEY,
    store_id      TEXT REFERENCES store (id) ON DELETE SET NULL,
    name          TEXT NOT NULL,
    rating        REAL,
    sales_count   INTEGER,
    source        TEXT NOT NULL DEFAULT 'unknown',
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    brand         TEXT,
    model         TEXT,
    family        TEXT,
    storage_gb    INTEGER,
    ram_gb        INTEGER,
    gtin          TEXT,
    mpn           TEXT,
    condition     TEXT NOT NULL DEFAULT 'new',
    identity_kind TEXT NOT NULL,
    identity_value TEXT NOT NULL,
    specs_json    TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_identity
    ON product (identity_kind, identity_value);

CREATE TABLE IF NOT EXISTS offer (
    id            TEXT PRIMARY KEY,
    product_id    TEXT NOT NULL REFERENCES product (id) ON DELETE CASCADE,
    store_id      TEXT NOT NULL REFERENCES store (id) ON DELETE CASCADE,
    seller_id     TEXT REFERENCES seller (id) ON DELETE SET NULL,
    url           TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'BRL',
    condition     TEXT NOT NULL DEFAULT 'new',
    availability  TEXT NOT NULL DEFAULT 'unknown',
    coupon_code   TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    UNIQUE (source, url)
);

CREATE INDEX IF NOT EXISTS idx_offer_product ON offer (product_id);
CREATE INDEX IF NOT EXISTS idx_offer_store ON offer (store_id);

-- Append-only: cada coleta vira uma linha. Nunca atualizamos preco historico.
CREATE TABLE IF NOT EXISTS offer_snapshot (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id          TEXT NOT NULL REFERENCES offer (id) ON DELETE CASCADE,
    price_cents       INTEGER NOT NULL,
    list_price_cents  INTEGER,
    shipping_cents    INTEGER,
    currency          TEXT NOT NULL DEFAULT 'BRL',
    installments      INTEGER,
    installment_cents INTEGER,
    collected_at      TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_url        TEXT NOT NULL,
    confidence        REAL NOT NULL DEFAULT 0.8,
    UNIQUE (offer_id, collected_at, price_cents)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_offer_time
    ON offer_snapshot (offer_id, collected_at);

CREATE TABLE IF NOT EXISTS alert (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    label            TEXT NOT NULL,
    query            TEXT NOT NULL,
    spec_json        TEXT NOT NULL,
    max_price_cents  INTEGER,
    min_discount_pct REAL,
    channels_json    TEXT NOT NULL DEFAULT '["console"]',
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    last_checked_at  TEXT
);

CREATE TABLE IF NOT EXISTS alert_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    INTEGER NOT NULL REFERENCES alert (id) ON DELETE CASCADE,
    offer_id    TEXT,
    price_cents INTEGER,
    reason      TEXT NOT NULL,
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER REFERENCES alert_event (id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,
    destination TEXT,
    subject     TEXT,
    body        TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL,
    sent_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_notification_status ON notification (status);
