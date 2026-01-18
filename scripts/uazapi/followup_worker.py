import os
import sys
import logging
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
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.error(f"Erro ao inicializar Gemini Client: {e}")


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

        # Usando gemini-2.5-flash como validado
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )

        text = response.text.strip()
        return True, text

    except Exception as e:
        logger.error(f"Erro Context Analysis: {e}")
        return False, None


async def check_and_run_followups():
    logger.info("🔍 Checking for stalled conversations (Refactored)...")

    with get_connection() as conn:
        with conn.cursor() as cur:
            logger.info("🕵️ Executing DB Query for candidates...")

            # Adicionado c.tools_config para checar se é Meta/LancePilot
            # Adicionado c.api_url para override de Uazapi
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
                    c.username,
                    c.api_url,
                    c.token as client_token,
                    c.whatsapp_provider,
                    EXTRACT(EPOCH FROM (NOW() - ac.last_message_at)) / 60 as db_diff_minutes
                FROM active_conversations ac
                JOIN clients c ON ac.client_id = c.id
                WHERE ac.last_role = 'assistant'
                AND ac.status = 'active'
            """)

            rows = cur.fetchall()
            logger.info(f"📊 Rows found (Active Assistant): {len(rows)}")

            for row in rows:
                chat_id = row["chat_id"]
                client_id = row["client_id"]
                current_stage_idx = row["followup_stage"] or 0
                config = row["followup_config"] or {}
                last_context_txt = row.get("last_context") or ""
                tools_config_json = row.get("tools_config") or {}

                # --- FILTRO POR PROVIDER (PRIMÁRIO) ---
                provider = row.get("whatsapp_provider") or "none"
                if provider not in [None, "", "none", "uazapi"]:
                    continue  # Este worker só processa Uazapi
                # ----------------------------------------

                # --- SAFETY CHECKS (LEGADO - Manter para compatibilidade) ---
                meta_cfg = tools_config_json.get("whatsapp", {})
                meta_legacy = tools_config_json.get("whatsapp_official", {})
                lp_cfg = tools_config_json.get("lancepilot", {})

                # Se usa Meta Oficial ou LancePilot, este worker IGNORA.
                if meta_cfg.get("active") or meta_legacy.get("active"):
                    continue
                if lp_cfg.get("active"):
                    continue
                # -----------------------------------------------

                # --- DEBUG CHECK ---
                target_chat_id = os.getenv("DEBUG_CHAT_ID")
                if target_chat_id and str(target_chat_id).strip() not in str(chat_id):
                    # Se tiver filtro e não for esse chat, pula silenciosamente
                    continue
                # -------------------

                # === EARLY EXIT: Config vazia ou None ===
                if not config:
                    logger.debug(f"⏭️ SKIP [{chat_id}]: followup_config is empty/None")
                    continue

                # === DEBUG LOGGING (CRÍTICO) ===
                logger.info(f"🔍 DEBUG [{chat_id}] followup_config raw: {config}")

                # Check Active Flag via Python - MAIS ROBUSTO
                is_active = config.get("active")

                # Trata vários formatos: True, "true", "True", 1, "1"
                active_values = [True, "true", "True", "1", 1]
                if is_active not in active_values:
                    logger.info(
                        f"⏭️ SKIP [{chat_id}]: Follow-up DESATIVADO (active={is_active})"
                    )
                    continue

                # Check 1: Human Intervention (Redis)
                if await check_is_paused(chat_id):
                    logger.info(
                        f"🛑 Skipping {chat_id}: Human Attendant Active (Paused)."
                    )
                    continue

                stages = config.get("stages", [])
                if not stages or current_stage_idx >= len(stages):
                    logger.info(
                        f"⏭️ SKIP [{chat_id}]: No stages configured (stages={len(stages)}, current={current_stage_idx})"
                    )
                    continue

                stage_cfg = stages[current_stage_idx]
                delay_min = stage_cfg.get("delay_minutes", 60)
                prompt_behavior = stage_cfg.get(
                    "prompt", "Pergunte se o cliente precisa de ajuda."
                )

                # Check Time (Timezone Safe via SQL)
                diff_minutes = float(row.get("db_diff_minutes") or 0)

                if diff_minutes >= delay_min:
                    logger.info(
                        f"🚀 Triggering Follow-up Stage {current_stage_idx + 1} for {chat_id} | Diff: {diff_minutes:.1f}m >= Limit: {delay_min}m"
                    )
                else:
                    # Log Opcional para Debug (pode ficar verboso, mas útil agora)
                    # logger.info(f"⏳ Waiting {chat_id}: {diff_minutes:.1f}m / {delay_min}m")
                    pass

                if diff_minutes >= delay_min:
                    analysis_prompt = f"""
                    Você é um especialista em atendimento. Analise a conversa abaixo.
                    
                    Histórico Recente:
                    Last Context: "{last_context_txt[-2000:]}"
                    (Obs: Pode estar truncado)

                    Instrução de Retomada: "{prompt_behavior}"

                    DECISÃO CRÍTICA:
                    1. Se o cliente JÁ encerrou, agradeceu, disse que vai aguardar, ou disse que não quer mais nada -> Responda APENAS: "FINISHED"
                    2. Se o cliente explicitamente pediu para parar ou demonstrou irritação -> Responda APENAS: "FINISHED"
                    3. Se o contexto pede retomada -> Responda com a mensagem de texto para enviar ao cliente.
                    """

                    try:
                        if not client:
                            logger.error("Gemini Client Unreachable for Analysis")
                            continue

                        resp = client.models.generate_content(
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
                                provider="uazapi",
                                gemini_usage=gemini_usage,
                            )
                        except Exception as usage_err:
                            logger.debug(f"Usage tracking: {usage_err}")

                        if "FINISHED" in resp_ai.upper() and len(resp_ai) < 15:
                            # Smart Termination
                            logger.info(
                                f"🛑 Smart Termination for {chat_id}: Context indicates finished."
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
                            # --- DYNAMIC API CONFIG ---
                            # Tenta pegar config específica de Uazapi do tools_config
                            uazapi_cfg = tools_config_json.get("uazapi", {})
                            custom_url = uazapi_cfg.get("url") or row.get("api_url")
                            # FIX: Prioridade -> Tools Config > Token da Coluna > Env Var (dentro da lib)
                            custom_key = uazapi_cfg.get("api_key") or row.get(
                                "client_token"
                            )

                            # Fallback para Env Vars é tratado dentro de uazapi_saas.py se passarmos None
                            # Mas se custom_url for passado, ele usa.

                            # Send Message
                            await send_whatsapp_message(
                                chat_id,
                                resp_ai,
                                api_key=custom_key,
                                base_url=custom_url,
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
                        error_msg = str(e)
                        if hasattr(e, "response") and e.response is not None:
                            error_msg += f" | Status: {e.response.status_code} | Body: {e.response.text}"

                        logger.error(f"Erro durante FollowUp (Gen/Send): {error_msg}")


if __name__ == "__main__":
    asyncio.run(check_and_run_followups())
