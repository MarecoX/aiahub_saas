import os
import sys
import logging
import datetime
import asyncio
import redis.asyncio as redis
from google import genai

# Add path to import local modules (shared directory)
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
)
from saas_db import get_connection
from uazapi_saas import send_whatsapp_message
from config import REDIS_URL

# Config logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("FollowUpWorker")

# Gemini Setup
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


async def check_is_paused(chat_id):
    """Verifica se o chat está em pausa (Atendimento Humano)."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        is_paused = await r.get(f"ai_paused:{chat_id}")
        await r.aclose()
        return bool(is_paused)
    except Exception as e:
        logger.error(f"Erro Redis Pause Check: {e}")
        return False


async def analyze_context(chat_id, instruction):
    """
    Analisa se a conversa já foi encerrada ou se precisa de follow-up.
    Retorna (should_send: bool, generated_text: str)
    """
    try:
        if not client:
            logger.error("Gemini Client not configured (Missing API Key).")
            return False, None

        # Simplificação v1: Apenas gerar a mensagem seguindo a instrução.
        # Por enquanto, vamos focar na Geração Inteligente.

        prompt = f"""
        Você é um assistente virtual profissional.
        O cliente parou de responder faz um tempo.
        
        Sua tarefa: Gerar uma mensagem de "Follow-up" (retomada).
        Instrução de Comportamento: {instruction}
        
        Regras:
        1. Se a instrução for para encerrar, gere uma despedida educada.
        2. Se for para tentar retomar, seja sutil.
        3. Gere APENAS o texto da mensagem.
        """

        # V2 SDK call
        response = client.models.generate_content(
            model="gemini-1.5-flash", contents=prompt
        )

        text = response.text.strip()
        return True, text

    except Exception as e:
        logger.error(f"Erro Context Analysis: {e}")
        return False, None


async def check_and_run_followups():
    logger.info("🔍 Checking for stalled conversations (UAZAPI)...")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Join active_conversations with clients
            cur.execute("""
                SELECT 
                    ac.chat_id, 
                    ac.client_id, 
                    ac.last_message_at, 
                    ac.last_role,
                    ac.followup_stage,
                    ac.last_context,
                    c.followup_config,
                    c.tools_config,
                    c.username
                FROM active_conversations ac
                JOIN clients c ON ac.client_id = c.id
                WHERE ac.last_role = 'assistant'
                AND ac.status = 'active'
            """)

            rows = cur.fetchall()
            logger.info(f"📊 Rows found: {len(rows)}")

            for row in rows:
                chat_id = row["chat_id"]
                client_id = row["client_id"]
                last_msg_at = row["last_message_at"]
                current_stage_idx = row["followup_stage"] or 0
                config = row["followup_config"] or {}
                last_context_txt = row.get("last_context") or ""
                tools_config_json = row.get("tools_config") or {}

                # ----------------------------------------------------
                # SEPARATION OF CONCERNS:
                # Se este cliente usa Meta Oficial Ativo, este worker DEVE IGNORAR.
                # Quem cuida dele é o meta_followup_worker.py
                # ----------------------------------------------------
                # ----------------------------------------------------
                meta_cfg = tools_config_json.get("whatsapp", {})
                meta_legacy = tools_config_json.get("whatsapp_official", {})
                lp_cfg = tools_config_json.get("lancepilot", {})

                # IGNORA SE FOR META OU LANCEPILOT
                if meta_cfg.get("active") or meta_legacy.get("active"):
                    continue
                if lp_cfg.get("active"):
                    continue

                # Check Active Flag via Python
                is_active = config.get("active")
                if str(is_active).lower() != "true":
                    continue

                # Check 1: Human Intervention (Redis)
                if await check_is_paused(chat_id):
                    logger.info(
                        f"🛑 Skipping {chat_id}: Human Attendant Active (Paused)."
                    )
                    continue

                stages = config.get("stages", [])
                if not stages or current_stage_idx >= len(stages):
                    continue

                stage_cfg = stages[current_stage_idx]
                delay_min = stage_cfg.get("delay_minutes", 60)
                prompt_behavior = stage_cfg.get(
                    "prompt", "Pergunte se o cliente precisa de ajuda."
                )

                # Check Time
                now = datetime.datetime.now()
                if last_msg_at.tzinfo:
                    last_msg_at = last_msg_at.replace(tzinfo=None)
                diff_minutes = (now - last_msg_at).total_seconds() / 60

                if diff_minutes >= delay_min:
                    # Logic Generation... (Simplified for restore)
                    try:
                        analysis_prompt = f"""
                        Você é um especialista em atendimento. Analise a conversa abaixo.
                        
                        Histórico Recente:
                        Last Context: "{last_context_txt[-2000:]}"
                        
                        Instrução de Retomada: "{prompt_behavior}"

                        DECISÃO:
                        1. Se o cliente já encerrou/agradeceu -> Responda APENAS: "FINISHED"
                        2. Se pode retomar -> Responda com a mensagem de texto.
                        """
                        if client:
                            resp_ai = client.models.generate_content(
                                model="gemini-2.5-flash", contents=analysis_prompt
                            ).text.strip()

                            if "FINISHED" in resp_ai.upper() and len(resp_ai) < 15:
                                # Smart Termination
                                logger.info(
                                    f"🛑 Smart Termination for {chat_id} (UAZAPI)"
                                )
                                cur.execute(
                                    """
                                    UPDATE active_conversations SET status = 'finished' 
                                    WHERE chat_id = %s AND client_id = %s
                                """,
                                    (chat_id, client_id),
                                )
                                conn.commit()
                            else:
                                # UAZAPI SPECIFIC SEND
                                await send_whatsapp_message(chat_id, resp_ai)
                                logger.info(
                                    f"✅ [UAZAPI] Sent Stage {current_stage_idx + 1} to {chat_id}"
                                )

                                cur.execute(
                                    """
                                    UPDATE active_conversations 
                                    SET last_message_at = NOW(),
                                        followup_stage = %s
                                    WHERE chat_id = %s AND client_id = %s
                                """,
                                    (current_stage_idx + 1, chat_id, client_id),
                                )
                                conn.commit()

                    except Exception as e:
                        logger.error(f"Erro AI Generation: {e}")


if __name__ == "__main__":
    asyncio.run(check_and_run_followups())
