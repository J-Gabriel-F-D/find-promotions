-- Fase 4: monitor contínuo, estado entre execuções e alertas inteligentes.
--
-- `monitor_run` registra uma sessão do monitor (um `--once` ou vários ciclos).
-- `monitor_state` guarda apenas metadados operacionais, nunca contatos.
-- `alert_rule` é opcional: alertas existentes continuam com as regras de
-- preço/desconto e passam a aceitar filtros probabilísticos adicionais.

CREATE TABLE IF NOT EXISTS monitor_run (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger          TEXT NOT NULL DEFAULT 'manual',
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    status           TEXT NOT NULL DEFAULT 'running',
    cycles           INTEGER NOT NULL DEFAULT 0,
    alerts_checked   INTEGER NOT NULL DEFAULT 0,
    matched          INTEGER NOT NULL DEFAULT 0,
    notifications    INTEGER NOT NULL DEFAULT 0,
    error            TEXT
);

CREATE INDEX IF NOT EXISTS idx_monitor_run_started
    ON monitor_run (started_at DESC);

CREATE TABLE IF NOT EXISTS monitor_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_rule (
    alert_id                 INTEGER PRIMARY KEY REFERENCES alert (id) ON DELETE CASCADE,
    min_trust                REAL,
    max_risk                 TEXT,
    require_real_discount    INTEGER NOT NULL DEFAULT 0,
    min_analysis_confidence  REAL,
    created_at               TEXT NOT NULL,
    CHECK (min_trust IS NULL OR (min_trust >= 0 AND min_trust <= 100)),
    CHECK (min_analysis_confidence IS NULL
           OR (min_analysis_confidence >= 0 AND min_analysis_confidence <= 1)),
    CHECK (max_risk IS NULL OR max_risk IN ('low', 'moderate', 'elevated'))
);
