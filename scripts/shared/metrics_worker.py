"""
Metrics Aggregation Worker (ADR-003)

Agrega eventos de conversation_events em metrics_daily.
Executado via Kestra cron a cada 5 minutos.

Fluxo:
    conversation_events (append-only)
        → metrics_worker (este script)
            → UPSERT metrics_daily (pré-agregado)
                → Dashboard lê (instantâneo)
"""

import sys
import os
import logging

# Path setup para imports compartilhados
_shared_dir = os.path.dirname(os.path.abspath(__file__))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

from saas_db import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MetricsWorker")


def aggregate_metrics():
    """
    Agrega eventos das últimas 24h em métricas diárias por cliente.
    Usa UPSERT para ser idempotente (pode rodar múltiplas vezes sem duplicar).
    """
    logger.info("📊 Iniciando agregação de métricas...")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Agregar eventos do dia atual e anterior (garante que o dia anterior
                # seja recalculado caso eventos atrasados cheguem)
                cur.execute("""
                    WITH daily_stats AS (
                        SELECT
                            client_id,
                            DATE(created_at) as event_date,

                            -- Mensagens
                            COUNT(*) FILTER (WHERE event_type = 'msg_received') as messages_in,
                            COUNT(*) FILTER (WHERE event_type = 'ai_responded') as messages_out,

                            -- Conversas únicas (distinct chat_id)
                            COUNT(DISTINCT chat_id) FILTER (WHERE event_type = 'msg_received') as conversations,

                            -- Resolução
                            COUNT(*) FILTER (WHERE event_type = 'resolved' AND event_data->>'resolved_by' = 'ai') as by_ai,
                            COUNT(*) FILTER (WHERE event_type = 'resolved' AND event_data->>'resolved_by' = 'human') as by_human,

                            -- Handoff
                            COUNT(*) FILTER (WHERE event_type = 'human_takeover') as takeovers,

                            -- Response time (média dos que têm esse dado)
                            COALESCE(
                                AVG((event_data->>'response_time_ms')::int) FILTER (
                                    WHERE event_type = 'ai_responded' AND event_data ? 'response_time_ms'
                                ), 0
                            )::int as avg_rt,

                            -- Resolution time
                            COALESCE(
                                AVG((event_data->>'resolution_time_ms')::int) FILTER (
                                    WHERE event_type = 'resolved' AND event_data ? 'resolution_time_ms'
                                ), 0
                            )::int as avg_resolution,

                            -- Followups
                            COUNT(*) FILTER (WHERE event_type = 'followup_sent') as fups_sent,
                            COUNT(*) FILTER (WHERE event_type = 'followup_converted') as fups_converted,

                            -- Cost
                            COALESCE(
                                SUM((event_data->>'cost_usd')::decimal) FILTER (
                                    WHERE event_data ? 'cost_usd'
                                ), 0
                            ) as cost,

                            -- Tools (agrega nomes em JSON)
                            COALESCE(
                                jsonb_object_agg(
                                    event_data->>'tool',
                                    1
                                ) FILTER (WHERE event_type = 'tool_used' AND event_data ? 'tool'),
                                '{}'::jsonb
                            ) as tools

                        FROM conversation_events
                        WHERE created_at >= CURRENT_DATE - INTERVAL '1 day'
                        GROUP BY client_id, DATE(created_at)
                    )
                    INSERT INTO metrics_daily (
                        client_id, date,
                        total_conversations, total_messages_in, total_messages_out,
                        resolved_by_ai, resolved_by_human, human_takeovers,
                        avg_response_time_ms, avg_resolution_time_ms,
                        followups_sent, followups_converted,
                        tools_used, total_cost_usd,
                        updated_at
                    )
                    SELECT
                        client_id, event_date,
                        conversations, messages_in, messages_out,
                        by_ai, by_human, takeovers,
                        avg_rt, avg_resolution,
                        fups_sent, fups_converted,
                        tools, cost,
                        NOW()
                    FROM daily_stats
                    ON CONFLICT (client_id, date) DO UPDATE SET
                        total_conversations = EXCLUDED.total_conversations,
                        total_messages_in = EXCLUDED.total_messages_in,
                        total_messages_out = EXCLUDED.total_messages_out,
                        resolved_by_ai = EXCLUDED.resolved_by_ai,
                        resolved_by_human = EXCLUDED.resolved_by_human,
                        human_takeovers = EXCLUDED.human_takeovers,
                        avg_response_time_ms = EXCLUDED.avg_response_time_ms,
                        avg_resolution_time_ms = EXCLUDED.avg_resolution_time_ms,
                        followups_sent = EXCLUDED.followups_sent,
                        followups_converted = EXCLUDED.followups_converted,
                        tools_used = EXCLUDED.tools_used,
                        total_cost_usd = EXCLUDED.total_cost_usd,
                        updated_at = NOW()
                """)

                logger.info("✅ Métricas diárias agregadas com sucesso.")

    except Exception as e:
        logger.error(f"❌ Erro na agregação de métricas: {e}")
        raise


def cleanup_old_events(days_to_keep: int = 90):
    """
    Remove eventos antigos para evitar crescimento infinito da tabela.
    Mantém os últimos N dias (default: 90).
    As métricas agregadas em metrics_daily são mantidas indefinidamente.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM conversation_events
                    WHERE created_at < CURRENT_DATE - INTERVAL '%s days'
                    """,
                    (days_to_keep,)
                )
                logger.info(f"🧹 Eventos com mais de {days_to_keep} dias removidos.")
    except Exception as e:
        logger.error(f"❌ Erro ao limpar eventos antigos: {e}")


if __name__ == "__main__":
    aggregate_metrics()
    cleanup_old_events()
    logger.info("📊 Metrics worker finalizado.")
