-- Migration 004: Criar tabelas de métricas (ADR-003)
-- conversation_events: Event log append-only (source of truth)
-- metrics_daily: Agregação pré-calculada para dashboard

BEGIN;

-- =============================================
-- 1. conversation_events (Event Log)
-- =============================================
CREATE TABLE IF NOT EXISTS conversation_events (
    id          BIGSERIAL PRIMARY KEY,
    client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    chat_id     TEXT NOT NULL,
    event_type  VARCHAR(50) NOT NULL,
    event_data  JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_events_client_time
    ON conversation_events (client_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conv_events_chat
    ON conversation_events (client_id, chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conv_events_type
    ON conversation_events (event_type, created_at);

-- =============================================
-- 2. metrics_daily (Agregação Pré-calculada)
-- =============================================
CREATE TABLE IF NOT EXISTS metrics_daily (
    id                      BIGSERIAL PRIMARY KEY,
    client_id               UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    date                    DATE NOT NULL,
    total_conversations     INT DEFAULT 0,
    total_messages_in       INT DEFAULT 0,
    total_messages_out      INT DEFAULT 0,
    resolved_by_ai          INT DEFAULT 0,
    resolved_by_human       INT DEFAULT 0,
    human_takeovers         INT DEFAULT 0,
    avg_response_time_ms    INT DEFAULT 0,
    avg_resolution_time_ms  INT DEFAULT 0,
    followups_sent          INT DEFAULT 0,
    followups_converted     INT DEFAULT 0,
    tools_used              JSONB DEFAULT '{}',
    total_cost_usd          DECIMAL(10,4) DEFAULT 0,
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (client_id, date)
);

COMMIT;
