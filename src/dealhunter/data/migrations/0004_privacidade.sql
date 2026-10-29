-- Retenção de dados pessoais sem reabrir notificações já enviadas.
--
-- O histórico detalhado (alert_event) pode ser apagado após a janela de
-- retenção, mas a chave de deduplicação precisa sobreviver enquanto o alerta
-- existir. Caso contrário, a próxima verificação voltaria a notificar a mesma
-- oferta e transformaria a retenção em um vetor de spam.

CREATE TABLE IF NOT EXISTS alert_dedupe (
    dedupe_key TEXT PRIMARY KEY,
    alert_id   INTEGER NOT NULL REFERENCES alert (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_dedupe_alert ON alert_dedupe (alert_id);

INSERT OR IGNORE INTO alert_dedupe (dedupe_key, alert_id, created_at)
    SELECT dedupe_key, alert_id, created_at FROM alert_event;
