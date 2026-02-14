"""
🚨 Debug Dashboard — Query Functions
Módulo separado com todas as queries para o Centro de Alertas do Admin.
Mantém o saas_db.py limpo e focado em operações core.
"""

import logging
import os
import sys

# Garante que scripts/shared está no path para imports funcionarem
_shared_dir = os.path.dirname(os.path.abspath(__file__))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

try:
    from shared.saas_db import get_connection
except ImportError:
    from saas_db import get_connection

logger = logging.getLogger("DebugQueries")


# ============================================================
# 📊 SAÚDE DO SISTEMA
# ============================================================


def get_system_health():
    """
    Retorna métricas gerais do sistema para o painel de saúde.
    Returns dict com: total_clients, active_conversations, errors_24h,
                      cost_24h, errors_by_hour (list), top_error_clients (list)
    """
    result = {
        "total_clients": 0,
        "active_conversations": 0,
        "errors_24h": 0,
        "cost_24h": 0.0,
        "errors_by_hour": [],
        "top_error_clients": [],
    }
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Total de clientes
                cur.execute("SELECT COUNT(*) as cnt FROM clients")
                row = cur.fetchone()
                result["total_clients"] = row["cnt"] if row else 0

                # Conversas ativas
                try:
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM active_conversations WHERE status = 'active'"
                    )
                    row = cur.fetchone()
                    result["active_conversations"] = row["cnt"] if row else 0
                except Exception:
                    pass  # Tabela pode não existir

                # Erros nas últimas 24h
                try:
                    cur.execute(
                        "SELECT COUNT(*) as cnt FROM error_logs WHERE timestamp > NOW() - INTERVAL '24 hours'"
                    )
                    row = cur.fetchone()
                    result["errors_24h"] = row["cnt"] if row else 0
                except Exception:
                    pass

                # Custo nas últimas 24h
                try:
                    cur.execute(
                        "SELECT COALESCE(SUM(cost_usd), 0) as total FROM usage_tracking WHERE created_at > NOW() - INTERVAL '24 hours'"
                    )
                    row = cur.fetchone()
                    result["cost_24h"] = float(row["total"]) if row else 0.0
                except Exception:
                    pass

                # Erros por hora (últimas 48h)
                try:
                    cur.execute("""
                        SELECT date_trunc('hour', timestamp) as hora, COUNT(*) as total
                        FROM error_logs
                        WHERE timestamp > NOW() - INTERVAL '48 hours'
                        GROUP BY hora
                        ORDER BY hora
                    """)
                    result["errors_by_hour"] = cur.fetchall()
                except Exception:
                    pass

                # Top 5 clientes com mais erros (últimas 24h)
                try:
                    cur.execute("""
                        SELECT e.client_id, c.name as client_name, COUNT(*) as error_count
                        FROM error_logs e
                        LEFT JOIN clients c ON c.id::text = e.client_id
                        WHERE e.timestamp > NOW() - INTERVAL '24 hours'
                        AND e.client_id IS NOT NULL
                        GROUP BY e.client_id, c.name
                        ORDER BY error_count DESC
                        LIMIT 5
                    """)
                    result["top_error_clients"] = cur.fetchall()
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"❌ Erro em get_system_health: {e}")

    return result


# ============================================================
# 🐞 ERRORS & BUGS
# ============================================================


def get_error_logs_filtered(
    client_id: str = None,
    error_type: str = None,
    days: int = 7,
    limit: int = 50,
):
    """Retorna logs de erro filtrados por cliente, tipo, período."""
    try:
        conditions = ["timestamp > NOW() - INTERVAL '%s days'"]
        params = [days]

        if client_id:
            conditions.append("client_id = %s")
            params.append(client_id)

        if error_type:
            conditions.append("error_type = %s")
            params.append(error_type)

        where_clause = " AND ".join(conditions)
        params.append(limit)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, timestamp, source, error_type, message, traceback,
                           client_id, chat_id, memory_usage, context_data
                    FROM error_logs
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro em get_error_logs_filtered: {e}")
        return []


def get_error_types():
    """Retorna lista de error_types distintos para filtro no UI."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT error_type FROM error_logs ORDER BY error_type"
                )
                return [row["error_type"] for row in cur.fetchall()]
    except Exception:
        return []


def cleanup_old_errors(days: int = 30):
    """Remove logs de erro com mais de N dias."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM error_logs WHERE timestamp < NOW() - INTERVAL '%s days'",
                    (days,),
                )
                deleted = cur.rowcount
                logger.info(f"🗑️ {deleted} error logs antigos removidos (> {days} dias)")
                return deleted
    except Exception as e:
        logger.error(f"❌ Erro em cleanup_old_errors: {e}")
        return 0


# ============================================================
# 🔄 LOOP DETECTOR
# ============================================================


def get_loop_suspects(min_calls: int = 5, window_minutes: int = 2):
    """
    Detecta suspeitas de loop: chats com muitas chamadas de API em curto período.
    Busca em usage_tracking por chat_ids com > min_calls registros em < window_minutes.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        u.chat_id,
                        u.client_id,
                        c.name as client_name,
                        COUNT(*) as call_count,
                        MIN(u.created_at) as first_call,
                        MAX(u.created_at) as last_call,
                        SUM(u.cost_usd) as total_cost,
                        EXTRACT(EPOCH FROM (MAX(u.created_at) - MIN(u.created_at))) as duration_seconds
                    FROM usage_tracking u
                    LEFT JOIN clients c ON c.id = u.client_id
                    WHERE u.created_at > NOW() - INTERVAL '7 days'
                    GROUP BY u.chat_id, u.client_id, c.name
                    HAVING COUNT(*) >= %s
                       AND EXTRACT(EPOCH FROM (MAX(u.created_at) - MIN(u.created_at))) < %s
                    ORDER BY call_count DESC
                    LIMIT 20
                    """,
                    (min_calls, window_minutes * 60),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro em get_loop_suspects: {e}")
        return []


# ============================================================
# 💬 CONVERSATION INSPECTOR
# ============================================================


def get_conversation_history(client_id: str, chat_id: str, limit: int = 50):
    """Retorna o histórico de mensagens e estado de um chat específico."""
    result = {"messages": [], "state": None}
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Mensagens
                cur.execute(
                    """
                    SELECT id, role, content, media_url, created_at
                    FROM chat_messages
                    WHERE client_id = %s AND chat_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (client_id, chat_id, limit),
                )
                result["messages"] = cur.fetchall()

                # Estado da conversa
                try:
                    cur.execute(
                        """
                        SELECT status, followup_stage, last_role, last_message_at, last_context
                        FROM active_conversations
                        WHERE client_id = %s AND chat_id = %s
                        """,
                        (client_id, chat_id),
                    )
                    result["state"] = cur.fetchone()
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"❌ Erro em get_conversation_history: {e}")

    return result


# ============================================================
# 💰 CONSUMO & CUSTOS
# ============================================================


def get_usage_report(days: int = 30):
    """Retorna relatório de uso agrupado por cliente e dia."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        u.client_id,
                        c.name as client_name,
                        DATE(u.created_at) as dia,
                        COUNT(DISTINCT u.chat_id) as atendimentos,
                        SUM(u.openai_input_tokens + u.openai_output_tokens) as tokens_openai,
                        SUM(u.gemini_input_tokens + u.gemini_output_tokens) as tokens_gemini,
                        SUM(u.whisper_seconds) as segundos_audio,
                        SUM(u.images_count) as imagens,
                        SUM(u.cost_usd) as custo_usd
                    FROM usage_tracking u
                    LEFT JOIN clients c ON c.id = u.client_id
                    WHERE u.created_at > NOW() - INTERVAL '%s days'
                    GROUP BY u.client_id, c.name, dia
                    ORDER BY dia DESC, custo_usd DESC
                    """,
                    (days,),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro em get_usage_report: {e}")
        return []


def get_daily_cost_chart(days: int = 30):
    """Retorna custo total por dia para gráfico."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DATE(created_at) as dia, SUM(cost_usd) as custo
                    FROM usage_tracking
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY dia
                    ORDER BY dia
                    """,
                    (days,),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro em get_daily_cost_chart: {e}")
        return []
