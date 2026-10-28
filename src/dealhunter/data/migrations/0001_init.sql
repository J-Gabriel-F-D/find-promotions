-- 0001_init: tabelas de infraestrutura (auditoria e controle interno).
-- Tabelas de dominio (product, offer, alert, ...) entram na Fase 1.

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at   TEXT    NOT NULL,
    actor         TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    entity        TEXT,
    entity_id     TEXT,
    before_json   TEXT,
    after_json    TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_occurred_at
    ON audit_log (occurred_at);

CREATE INDEX IF NOT EXISTS idx_audit_log_entity
    ON audit_log (entity, entity_id);
