"""
Reminder Worker - Processa lembretes pendentes com análise de contexto.

Este script:
1. Busca lembretes pendentes cujo scheduled_at já passou
2. Carrega o histórico de conversa do chat
3. Chama a IA para analisar se ainda faz sentido enviar e gerar mensagem
4. Envia a mensagem via Uazapi
5. Marca o lembrete como 'sent' ou 'cancelled'
"""

import sys
import os
import asyncio
import logging
from datetime import datetime

# Adiciona shared folder ao path
shared_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
sys.path.append(shared_dir)


# --- BOOTSTRAP AMBIENTE KESTRA ---
def ensure_env(key, default):
    if not os.getenv(key):
        os.environ[key] = default


ensure_env("REDIS_URL", "redis://localhost:6379")
if os.getenv("DATABASE_URL") and not os.getenv("DATABASE_CONNECTION_URI"):
    os.environ["DATABASE_CONNECTION_URI"] = os.getenv("DATABASE_URL")

from kestra import Kestra
from saas_db import get_connection, get_client_config_by_id
from message_history import get_recent_messages
from uazapi_saas import send_whatsapp_message

# Configura logs
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ReminderWorker")

# OpenAI para análise de contexto
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


async def analyze_context_and_generate_message(
    chat_id: str, client_config: dict, reminder_message: str
) -> tuple[bool, str]:
    """
    Analisa o contexto do chat e decide se deve enviar o lembrete.
    Retorna: (should_send: bool, message: str ou reason: str)
    """
    from openai import OpenAI

    # Carrega histórico recente
    client_id = client_config.get("id")
    recent_msgs = get_recent_messages(client_id, chat_id, limit=10)

    if not recent_msgs:
        # Sem histórico, envia mensagem padrão
        return True, f"Olá! Estou retornando conforme combinamos. {reminder_message}"

    # Formata histórico
    history_text = "\n".join(
        [f"[{msg['role'].upper()}]: {msg['content']}" for msg in recent_msgs]
    )

    # Chama OpenAI para análise
    client = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = """Você é um assistente que analisa conversas de WhatsApp.
Seu trabalho é:
1. Analisar o contexto da conversa
2. Decidir se faz sentido enviar um lembrete de follow-up
3. Se SIM, gerar uma mensagem personalizada e natural
4. Se NÃO, explicar o motivo

Responda EXATAMENTE no formato:
DECISÃO: ENVIAR ou NÃO_ENVIAR
MENSAGEM: [sua mensagem personalizada ou motivo para não enviar]

Motivos para NÃO ENVIAR:
- Cliente já fechou negócio/comprou
- Cliente disse que não tem interesse
- Cliente pediu para não ser contatado
- Conversa indica que assunto já foi resolvido"""

    user_prompt = f"""Contexto do lembrete: {reminder_message}

Histórico da conversa:
{history_text}

Analise e decida se devo enviar o lembrete e gere uma mensagem apropriada."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )

        result = response.choices[0].message.content or ""

        # Parseia resposta
        if "NÃO_ENVIAR" in result.upper():
            # Extrai motivo
            reason = (
                result.split("MENSAGEM:")[-1].strip()
                if "MENSAGEM:" in result
                else "Contexto indica que não deve enviar"
            )
            return False, reason
        else:
            # Extrai mensagem
            message = (
                result.split("MENSAGEM:")[-1].strip()
                if "MENSAGEM:" in result
                else reminder_message
            )
            return True, message

    except Exception as e:
        logger.error(f"Erro ao analisar contexto: {e}")
        # Fallback: envia mensagem padrão
        return True, f"Olá! Estou retornando conforme combinamos. {reminder_message}"


async def process_pending_reminders():
    """Processa todos os lembretes pendentes."""
    now = datetime.now()
    processed = 0
    sent = 0
    cancelled = 0

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Busca lembretes pendentes
                cur.execute(
                    """
                    SELECT r.id, r.client_id, r.chat_id, r.message, r.scheduled_at
                    FROM reminders r
                    WHERE r.status = 'pending' AND r.scheduled_at <= %s
                    ORDER BY r.scheduled_at
                    LIMIT 50
                """,
                    (now,),
                )

                reminders = cur.fetchall()

        logger.info(f"📋 Encontrados {len(reminders)} lembretes pendentes")

        for reminder in reminders:
            reminder_id = reminder["id"]
            client_id = reminder["client_id"]
            chat_id = reminder["chat_id"]
            message = reminder["message"]

            try:
                # Carrega config do cliente
                client_config = get_client_config_by_id(str(client_id))

                if not client_config:
                    logger.warning(
                        f"⚠️ Cliente {client_id} não encontrado. Cancelando lembrete."
                    )
                    await update_reminder_status(
                        reminder_id, "cancelled", "Cliente não encontrado"
                    )
                    cancelled += 1
                    continue

                # Analisa contexto e gera mensagem
                (
                    should_send,
                    result_message,
                ) = await analyze_context_and_generate_message(
                    chat_id, client_config, message
                )

                if should_send:
                    # Envia mensagem
                    api_url = client_config.get("api_url")
                    api_token = client_config.get("token")

                    await send_whatsapp_message(
                        chat_id, result_message, api_key=api_token, base_url=api_url
                    )

                    await update_reminder_status(reminder_id, "sent", result_message)
                    logger.info(f"✅ Lembrete {reminder_id} enviado para {chat_id}")
                    sent += 1
                else:
                    await update_reminder_status(
                        reminder_id, "cancelled", result_message
                    )
                    logger.info(
                        f"🚫 Lembrete {reminder_id} cancelado: {result_message[:50]}..."
                    )
                    cancelled += 1

                processed += 1

                # Delay entre lembretes
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"❌ Erro ao processar lembrete {reminder_id}: {e}")
                await update_reminder_status(reminder_id, "error", str(e))

    except Exception as e:
        logger.error(f"❌ Erro ao buscar lembretes: {e}")

    return processed, sent, cancelled


async def update_reminder_status(reminder_id, status: str, notes: str = None):
    """Atualiza o status de um lembrete."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE reminders 
                    SET status = %s, updated_at = NOW(), notes = %s
                    WHERE id = %s
                """,
                    (status, notes, reminder_id),
                )
    except Exception as e:
        logger.error(f"Erro ao atualizar status do lembrete {reminder_id}: {e}")


async def main():
    logger.info("🔔 Iniciando Reminder Worker...")

    processed, sent, cancelled = await process_pending_reminders()

    logger.info(
        f"📊 Resumo: {processed} processados, {sent} enviados, {cancelled} cancelados"
    )

    # Output para Kestra
    Kestra.outputs(
        {
            "processed": processed,
            "sent": sent,
            "cancelled": cancelled,
            "timestamp": datetime.now().isoformat(),
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
