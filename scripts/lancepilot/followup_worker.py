import os
import sys
import logging
import asyncio
import datetime
import redis.asyncio as redis
from google import genai

# Fix Sys Path - use shared folder AND scripts folder for lancepilot package
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(current_dir)  # scripts/
shared_dir = os.path.join(scripts_dir, "shared")
sys.path.append(shared_dir)
sys.path.append(scripts_dir)  # For lancepilot.client import

# Imports
from saas_db import get_connection  # noqa: E402
from config import REDIS_URL  # noqa: E402
from lancepilot.client import LancePilotClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("FollowUpWorker_LP")

# Gemini Setup
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client_ai = None
if GEMINI_API_KEY:
    client_ai = genai.Client(api_key=GEMINI_API_KEY)


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


async def check_and_run_followups():
    logger.info("🔍 [LancePilot] Checking for stalled conversations...")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Seleciona TODAS conversas ativas onde o assistente falou por último
            # Filtraremos no Python quais são LancePilot
            cur.execute("""
                SELECT 
                    ac.chat_id, 
                    ac.client_id, 
                    ac.last_message_at, 
                    ac.last_role,
                    ac.followup_stage,
                    ac.last_context,
                    c.tools_config,
                    c.followup_config,
                    c.username,
                    c.whatsapp_provider,
                    EXTRACT(EPOCH FROM (NOW() - ac.last_message_at)) / 60 as db_diff_minutes
                FROM active_conversations ac
                JOIN clients c ON ac.client_id = c.id
                WHERE ac.last_role = 'assistant'
                AND ac.status = 'active'
            """)

            rows = cur.fetchall()
            logger.info(f"📊 Candidates found: {len(rows)}")

            for row in rows:
                chat_id = row["chat_id"]
                client_id = row["client_id"]
                last_msg_at = row["last_message_at"]
                current_stage_idx = row["followup_stage"] or 0
                followup_config = row["followup_config"] or {}
                tools_config = row["tools_config"] or {}
                last_context_txt = row.get("last_context") or ""

                # --- FILTRO POR PROVIDER (PRIMÁRIO) ---
                provider = row.get("whatsapp_provider") or "none"
                if provider != "lancepilot":
                    continue  # Este worker só processa LancePilot
                # ----------------------------------------

                # 1. VERIFICAR CREDENCIAIS (LEGADO - Manter para pegar tokens)
                lp_cfg = tools_config.get("lancepilot", {})
                if not lp_cfg.get("active"):
                    # Não é cliente LancePilot, ignora (deixe pro worker Uazapi)
                    continue

                lp_token = lp_cfg.get("token")
                lp_workspace = lp_cfg.get("workspace_id")
                if not lp_token or not lp_workspace:
                    logger.warning(
                        f"⚠️ Client {client_id} has LP active but missing creds."
                    )
                    continue

                # 2. Check Active Flag
                is_active = followup_config.get("active")
                if str(is_active).lower() != "true":
                    continue

                # 3. Check Human Intervention
                if await check_is_paused(chat_id):
                    logger.info(
                        f"🛑 Skipping {chat_id}: Human Attendant Active (Paused)."
                    )
                    continue

                # 4. Check Stages
                stages = followup_config.get("stages", [])
                if not stages or current_stage_idx >= len(stages):
                    continue

                stage_cfg = stages[current_stage_idx]
                delay_min = stage_cfg.get("delay_minutes", 60)
                prompt_behavior = stage_cfg.get(
                    "prompt", "Pergunte se o cliente precisa de ajuda."
                )

                # 5. Check Time (Timezone Safe via SQL)
                diff_minutes = float(row.get("db_diff_minutes") or 0)

                if diff_minutes >= delay_min:
                    logger.info(
                        f"🚀 Triggering Follow-up Stage {current_stage_idx + 1} for {chat_id} (LP)"
                    )

                    # 6. Check 24h Window (LancePilot Official API Limit)
                    lp_client = LancePilotClient(lp_token)
                    can_send = lp_client.check_can_send_via_number(
                        workspace_id=lp_workspace, phone_number=chat_id
                    )

                    if not can_send:
                        logger.warning(
                            f"🚫 Janela de 24h FECHADA para {chat_id}. Não é possível enviar Free Message."
                        )
                        # Opcional: Marcar como 'stalled_window' ou apenas ignorar até o cliente falar de novo
                        continue

                    # 7. Generate Content (Gemini)
                    if not client_ai:
                        logger.error("Gemini API Key missing.")
                        continue

                    analysis_prompt = f"""
                    Você é um especialista em atendimento. Analise a conversa abaixo.
                    
                    Histórico Recente:
                    Last Context: "{last_context_txt[-2000:]}"
                    
                    Instrução de Retomada: "{prompt_behavior}"

                    DECISÃO:
                    1. Se o cliente já encerrou/agradeceu -> Responda APENAS: "FINISHED"
                    2. Se pode retomar -> Responda com a mensagem de texto.
                    """

                    try:
                        resp = client_ai.models.generate_content(
                            model="gemini-2.5-flash", contents=analysis_prompt
                        )
                        resp_ai = resp.text.strip()

                        # Salva usage para tracking
                        try:
                            from usage_tracker import save_usage

                            gemini_usage = {}
                            if hasattr(resp, "usage_metadata") and resp.usage_metadata:
                                gemini_usage = {
                                    "input_tokens": getattr(
                                        resp.usage_metadata, "prompt_token_count", 0
                                    ),
                                    "output_tokens": getattr(
                                        resp.usage_metadata, "candidates_token_count", 0
                                    ),
                                }
                            save_usage(
                                client_id=str(client_id),
                                chat_id=chat_id,
                                source="followup",
                                provider="lancepilot",
                                gemini_usage=gemini_usage,
                            )
                        except Exception:
                            pass

                        if "FINISHED" in resp_ai.upper() and len(resp_ai) < 15:
                            logger.info(f"🛑 Smart Termination for {chat_id}")
                            cur.execute(
                                """
                                UPDATE active_conversations SET status = 'finished' 
                                WHERE chat_id = %s AND client_id = %s
                            """,
                                (chat_id, client_id),
                            )
                            conn.commit()
                        else:
                            # 7. SEND VIA LANCEPILOT
                            # lp_client já instanciado acima
                            lp_client.send_text_message_via_number(
                                workspace_id=lp_workspace,
                                phone_number=chat_id,
                                text=resp_ai,
                            )
                            logger.info(
                                f"✅ Sent Stage {current_stage_idx + 1} to {chat_id}"
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
                        logger.error(f"Erro FollowUp Execution: {e}")


if __name__ == "__main__":
    asyncio.run(check_and_run_followups())
