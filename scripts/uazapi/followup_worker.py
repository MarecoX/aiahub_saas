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
from saas_db import get_connection, get_provider_config, log_event, is_within_followup_hours
from uazapi_saas import send_whatsapp_message, send_whatsapp_audio
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


def clean_message_content(text: str) -> str:
    """Limpa placeholders comuns gerados por alucinação da IA."""
    import re
    # Remove variações de [Nome do Cliente], [Seu Nome], Fulano, etc.
    patterns = [
        r"\[Nome do Cliente\]",
        r"\[Nome do Usuário\]",
        r"\[Insira o Nome\]",
        r"\[Nome\]",
        r"Fulano(,? ?\?|!)?",  # Remove "Fulano?", "Fulano!" etc.
    ]
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)
    
    # Remove espaços duplos e pontuações órfãs resultantes da remoção
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^\s*[,.?!\s]+", "", cleaned) # Remove pontuação no início
    return cleaned.strip()


async def check_and_run_followups():
    logger.info("🔍 Checking for stalled conversations (Refactored for Chaining & Safety)...")

    with get_connection() as conn:
        with conn.cursor() as cur:
            logger.info("🕵️ Executing DB Query for candidates...")

            # --- SAFETY UPDATE: Only check conversations active in the last 24 hours ---
            # Prevents waking up dead/zombie conversations from weeks ago.
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
                AND ac.last_message_at > NOW() - INTERVAL '24 HOURS'
            """)

            rows = cur.fetchall()
            logger.info(f"📊 Rows found (Active Assistant < 24h): {len(rows)}")

            for row in rows:
                chat_id = row["chat_id"]
                client_id = row["client_id"]
                client_token = row.get("client_token") or ""
                
                # --- INITIALIZE STATE FOR CHAINING ---
                # We update these as we iterate through chained stages
                current_stage_idx = row["followup_stage"] or 0
                last_context_txt = row.get("last_context") or ""
                diff_minutes = float(row.get("db_diff_minutes") or 0)
                
                config = row["followup_config"] or {}
                tools_config_json = row.get("tools_config") or {}

                # --- FILTRO POR PROVIDER (PRIMÁRIO) ---
                provider = row.get("whatsapp_provider") or "none"
                if provider not in [None, "", "none", "uazapi"]:
                    continue  # Este worker só processa Uazapi

                # --- SAFETY CHECKS (LEGADO) ---
                meta_cfg = tools_config_json.get("whatsapp", {})
                meta_legacy = tools_config_json.get("whatsapp_official", {})
                lp_cfg = tools_config_json.get("lancepilot", {})

                if meta_cfg.get("active") or meta_legacy.get("active"):
                    continue
                if lp_cfg.get("active"):
                    continue

                # --- DEBUG CHECK ---
                target_chat_id = os.getenv("DEBUG_CHAT_ID")
                if target_chat_id and str(target_chat_id).strip() not in str(chat_id):
                    continue

                # === EARLY EXIT: Config vazia ou None ===
                if not config:
                    continue

                # Check Active Flag via Python
                is_active = config.get("active")
                active_values = [True, "true", "True", "1", 1]
                if is_active not in active_values:
                    continue

                # Check: Allowed Hours (Faixa de Horário)
                if not is_within_followup_hours(config):
                    logger.info(f"🕐 Skipping {chat_id}: Fora da faixa de horário permitida para follow-up.")
                    continue

                # Check 1: Human Intervention (Redis)
                if await check_is_paused(chat_id):
                    logger.info(f"🛑 Skipping {chat_id}: Human Attendant Active (Paused).")
                    continue

                stages = config.get("stages", [])
                
                # === CHAINING LOOP ===
                # This loop allows processing multiple stages SEQUENTIALLY if delay=0
                # e.g. Stage 1 (Audio) -> Sent -> Next Stage (Text, Delay=0) -> Sent Immediately
                
                while True:
                    if not stages or current_stage_idx >= len(stages):
                        # No more stages to process
                        break
                        
                    stage_cfg = stages[current_stage_idx]
                    delay_min = stage_cfg.get("delay_minutes", 60)
                    prompt_behavior = stage_cfg.get("prompt", "Pergunte se o cliente precisa de ajuda.")

                    # Check Time
                    # Note: For the first iteration, diff_minutes comes from DB.
                    # For subsequent chained iterations, we assume IMMEDIATE execution (diff effectively infinite relative to 0)
                    # or strictly check delay <= 0.
                    
                    should_run = False
                    if diff_minutes >= delay_min:
                        should_run = True
                    
                    if not should_run:
                        # Not time yet to run this stage. Break inner loop, move to next Row.
                        break
                        
                    logger.info(
                         f"🚀 Triggering Follow-up Stage {current_stage_idx + 1} for {chat_id} | Diff: {diff_minutes:.1f}m >= Limit: {delay_min}m"
                    )

                    # EXECUTE STAGE
                    stage_type = stage_cfg.get("type", "text")
                    clean_text = ""
                    sent_success = False
                    
                    # === FLUXO DE ÁUDIO ===
                    if stage_type == "audio":
                        # --- AUDIO GUARDRAIL: Verify Context with AI ---
                        # Antes de enviar audio cego, perguntamos se faz sentido
                        audio_sent_decision = True
                        if client:
                            guard_prompt = f"""
                            Review this conversation history. 
                            Active Role: Assistant (Follow-up Bot).
                            
                            History: "{last_context_txt[-2000:]}"
                            
                            Task: I am about to send a pre-recorded FOLLOW-UP AUDIO to re-engage this user.
                            
                            Decision:
                            - If the user said "ok", "bye", "obrigado", or if the conversation was handed off to a human, or if the issue is resolved: RETURN "ABORT"
                            - If the user is silent and we should try to re-engage: RETURN "PROCEED"
                            
                            Return ONLY "ABORT" or "PROCEED".
                            """
                            try:
                                guard_resp = client.models.generate_content(
                                    model="gemini-2.5-flash", 
                                    contents=guard_prompt,
                                    config={"temperature": 0.0}
                                )
                                decision = guard_resp.text.strip().upper()
                                if "ABORT" in decision:
                                    logger.info(f"🛑 Audio Skipped by AI Guardrail: {chat_id}")
                                    # Mark as finished so we don't try again forever
                                    cur.execute(
                                        "UPDATE active_conversations SET status = 'finished' WHERE chat_id = %s AND client_id = %s",
                                        (chat_id, client_id),
                                    )
                                    conn.commit()
                                    audio_sent_decision = False
                                    break # Stop chaining
                            except Exception as xe:
                                logger.warning(f"⚠️ Guardrail Failed, defaulting to proceed: {xe}")

                        if not audio_sent_decision:
                            break # Safety break

                        audio_url = stage_cfg.get("audio_url")
                        if not audio_url:
                            logger.error(f"❌ Audio URL missing for {chat_id} (Stage {current_stage_idx})")
                            break # Critical error, stop chaining

                        # Setup Uazapi Config (Resolve once)
                        uazapi_cfg = get_provider_config(str(client_id), "uazapi")
                        if not uazapi_cfg:
                             uazapi_cfg = tools_config_json.get("uazapi", {})
                        
                        custom_url = uazapi_cfg.get("url") or row.get("api_url") or ""
                        custom_key = uazapi_cfg.get("token") or uazapi_cfg.get("api_key") or client_token or ""

                        try:
                            await send_whatsapp_audio(
                                chat_id, 
                                audio_url, 
                                api_key=custom_key, 
                                base_url=custom_url
                            )
                            clean_text = f"[Áudio Enviado]: {audio_url}"
                            logger.info(f"✅ Sent Stage {current_stage_idx + 1} (AUDIO) to {chat_id}")
                            sent_success = True
                        except Exception as e:
                            logger.error(f"❌ Failed to send audio: {e}")
                            break # Stop chaining on failure

                    # === FLUXO DE TEXTO (GEMINI) ===
                    else:
                        analysis_prompt = f"""
                        Você é um especialista em atendimento. Sua missão é retomar o contato com um cliente que parou de responder.
                        
                        CONDIÇÃO ATUAL: O CLIENTE parou de responder. VOCÊ (a IA) está aguardando retorno.
                        
                        Histórico Recente:
                        Last Context: "{last_context_txt[-2000:]}"
                        
                        Instrução para esta mensagem de follow-up: "{prompt_behavior}"

                        REGRAS DE OURO:
                        1. JAMAIS peça desculpas pela demora. VOCÊ não demorou, você está seguindo um fluxo de retorno programado.
                        2. NÃO diga "ainda estou aqui" ou "voltei". Aja como se estivesse apenas dando continuidade ao processo.
                        3. Se o cliente já resolveu o assunto ou disse "FINISHED", responda apenas "FINISHED".
                        4. Se o contexto pede retomada, gere o texto da mensagem.
                        5. NÃO use placeholders como [Nome].
                        6. Seja breve, direto e natural.
                        """

                        try:
                            if not client:
                                logger.error("Gemini Client Unreachable for Analysis")
                                break

                            resp = client.models.generate_content(
                                model="gemini-2.5-flash", 
                                contents=analysis_prompt,
                                config={"temperature": 0.1}
                            )
                            resp_ai = resp.text.strip()

                            # Salva usage (Omitted for brevity in loop, assumes standard call)
                            
                            if "FINISHED" in resp_ai.upper() and len(resp_ai) < 15:
                                # Smart Termination
                                logger.info(f"🛑 Smart Termination for {chat_id}: Context indicates finished.")
                                cur.execute(
                                    "UPDATE active_conversations SET status = 'finished' WHERE chat_id = %s AND client_id = %s",
                                    (chat_id, client_id),
                                )
                                conn.commit()
                                # Metrics: conversa resolvida pela IA
                                log_event(str(client_id), chat_id, "resolved", {"resolved_by": "ai"})
                                # Conversa finalizada, não podemos continuar chain
                                break
                            else:
                                # Send Message
                                clean_text = clean_message_content(resp_ai)
                                
                                # Setup Config (Again, could be optimized outside but safe here)
                                uazapi_cfg = get_provider_config(str(client_id), "uazapi")
                                if not uazapi_cfg:
                                    uazapi_cfg = tools_config_json.get("uazapi", {})
                                
                                custom_url = uazapi_cfg.get("url") or row.get("api_url") or ""
                                custom_key = uazapi_cfg.get("token") or uazapi_cfg.get("api_key") or client_token or ""

                                await send_whatsapp_message(
                                    chat_id,
                                    clean_text,
                                    api_key=custom_key,
                                    base_url=custom_url,
                                )

                                logger.info(f"✅ Sent Stage {current_stage_idx + 1} to {chat_id}")
                                sent_success = True

                        except Exception as e:
                            logger.error(f"Generate Content Error: {e}")
                            break

                    # === POST-EXECUTION UPDATE ===
                    if sent_success:
                        # Update DB to record this stage
                        cur.execute(
                            """
                            UPDATE active_conversations 
                            SET last_message_at = NOW(),
                                followup_stage = %s,
                                last_context = COALESCE(last_context, '') || E'\nAI: ' || %s,
                                last_role = 'assistant'
                            WHERE chat_id = %s AND client_id = %s
                        """,
                            (current_stage_idx + 1, clean_text, chat_id, client_id),
                        )
                        conn.commit()

                        # Metrics: registra followup enviado
                        log_event(str(client_id), chat_id, "followup_sent", {"stage": current_stage_idx + 1})

                        # Update Local State for Chaining
                        # We advance to next stage
                        current_stage_idx += 1
                        # IMPORTANT: Since we JUST sent a message, the "diff_minutes" relative to *now* is 0.
                        # This allows the NEXT iteration of the 'while True' loop to pick up immediately
                        # if the next stage has delay_minutes <= 0.
                        diff_minutes = 999999 # Hack: Force "time passed" logic? No.
                        # Actually, if we want to run next stage immediately (delay=0), we treat "time since last stage" as... well.
                        # Using 0 is technically correct (just happened), but if delay=0 required, 0 >= 0 is True.
                        # If delay=1, 0 >= 1 is False. 
                        # So updating diff_minutes to 0 is likely safer/correct for what we want (immediate chain only if delay is zero).
                        
                        # Wait, the logic above is: if diff_minutes >= delay_min: run.
                        # If we set diff_minutes = 0.
                        # Next stage: delay=0.   0 >= 0 -> True. Run!
                        # Next stage: delay=60.  0 >= 60 -> False. Break.
                        # Perfect.
                        diff_minutes = 0 
                        
                        # Update context so next prompt knows what was just sent
                        last_context_txt += f"\nAI: {clean_text}"
                        
                        # Small sleep to ensure order in WhatsApp (Audio arrives before Text)
                        await asyncio.sleep(1) 
                    else:
                        # Should not happen if exceptions caught, but break just in case
                        break


if __name__ == "__main__":
    asyncio.run(check_and_run_followups())
