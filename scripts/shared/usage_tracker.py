"""
Módulo de tracking de consumo de IA por cliente.
Centraliza o salvamento de métricas de uso.
"""

import logging
from datetime import timedelta
from saas_db import get_connection

logger = logging.getLogger("UsageTracker")

# Preços atuais (USD) - Atualizar conforme mudanças de preço das APIs
PRICES = {
    # OpenAI GPT-4o-mini
    "openai_input": 0.15 / 1_000_000,
    "openai_output": 0.60 / 1_000_000,
    # OpenAI Whisper
    "whisper_per_minute": 0.006,
    # Gemini 3 Flash (Jan 2026)
    "gemini_input": 0.50 / 1_000_000,
    "gemini_output": 3.00 / 1_000_000,  # inclui thinking tokens
    # Vision (por imagem)
    "vision_per_image": 0.00575,
}


def calculate_cost(
    openai_in: int = 0,
    openai_out: int = 0,
    gemini_in: int = 0,
    gemini_out: int = 0,
    whisper_seconds: int = 0,
    images: int = 0,
) -> float:
    """Calcula custo total em USD."""
    return (
        openai_in * PRICES["openai_input"]
        + openai_out * PRICES["openai_output"]
        + gemini_in * PRICES["gemini_input"]
        + gemini_out * PRICES["gemini_output"]
        + (whisper_seconds / 60) * PRICES["whisper_per_minute"]
        + images * PRICES["vision_per_image"]
    )


def save_usage(
    client_id: str,
    chat_id: str,
    source: str,
    provider: str = "uazapi",
    openai_usage: dict = None,
    gemini_usage: dict = None,
    whisper_seconds: int = 0,
    images_count: int = 0,
) -> float:
    """
    Salva métricas de uso no banco de dados.

    Args:
        client_id: UUID do cliente
        chat_id: ID do chat/conversa
        source: Origem ('rag_worker', 'followup', 'media', 'ingest')
        provider: Provider WhatsApp ('uazapi', 'meta', 'lancepilot')
        openai_usage: Dict com input_tokens e output_tokens
        gemini_usage: Dict com input_tokens e output_tokens
        whisper_seconds: Segundos de áudio transcritos
        images_count: Número de imagens processadas

    Returns:
        Custo calculado em USD
    """
    openai_in = openai_usage.get("input_tokens", 0) if openai_usage else 0
    openai_out = openai_usage.get("output_tokens", 0) if openai_usage else 0
    gemini_in = gemini_usage.get("input_tokens", 0) if gemini_usage else 0
    gemini_out = gemini_usage.get("output_tokens", 0) if gemini_usage else 0

    cost = calculate_cost(
        openai_in, openai_out, gemini_in, gemini_out, whisper_seconds, images_count
    )

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usage_tracking 
                    (client_id, chat_id, source, provider,
                     openai_input_tokens, openai_output_tokens, whisper_seconds,
                     gemini_input_tokens, gemini_output_tokens, images_count, cost_usd)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        client_id,
                        chat_id,
                        source,
                        provider,
                        openai_in,
                        openai_out,
                        whisper_seconds,
                        gemini_in,
                        gemini_out,
                        images_count,
                        cost,
                    ),
                )
        logger.info(f"💰 Usage saved: ${cost:.6f} USD ({source}/{provider})")
    except Exception as e:
        logger.error(f"❌ Erro ao salvar usage: {e}")

    return cost


def get_client_usage_summary(client_id: str, days: int = 30) -> dict:
    """Retorna resumo de uso de um cliente nos últimos N dias."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        COUNT(DISTINCT chat_id) as atendimentos,
                        SUM(openai_input_tokens + openai_output_tokens) as tokens_openai,
                        SUM(gemini_input_tokens + gemini_output_tokens) as tokens_gemini,
                        SUM(whisper_seconds) as segundos_audio,
                        SUM(images_count) as imagens,
                        SUM(cost_usd) as custo_usd
                    FROM usage_tracking
                    WHERE client_id = %s
                    AND created_at > NOW() - %s
                """,
                    (client_id, timedelta(days=days)),
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
        return {}
    except Exception as e:
        logger.error(f"Erro ao buscar usage summary: {e}")
        return {}
