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
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "meta")))

from saas_db import get_connection
from config import REDIS_URL
from meta_client import MetaClient

# Config logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("MetaFollowUp")

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


async def check_and_run_followups():
    logger.info("🔍 Checking for stalled conversations (META OFFICIAL)...")

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
                    c.username,
                    c.whatsapp_provider
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

                # --- FILTRO POR PROVIDER (PRIMÁRIO) ---
                provider = row.get("whatsapp_provider") or "none"
                if provider != "meta":
                    continue  # Este worker só processa Meta
                # ----------------------------------------

                # --- CONFIG META (LEGADO - Manter para pegar tokens) ---
                meta_cfg = tools_config_json.get("whatsapp", {})
                meta_legacy = tools_config_json.get("whatsapp_official", {})

                # Se não tiver config ativa em nenhum lugar, ignora (Uazapi cuida ou ninguém cuida)
                if not meta_cfg.get("active") and not meta_legacy.get("active"):
                    continue

                # Prioriza 'whatsapp' (novo)
                active_cfg = meta_cfg if meta_cfg.get("active") else meta_legacy

                token = active_cfg.get("access_token") or active_cfg.get("token")
                phone_id = active_cfg.get("phone_id")

                if not token or not phone_id:
                    logger.warning(
                        f"⚠️ Cliente {client_id} tem Meta Ativo mas sem Token/PhoneID."
                    )
                    continue

                # Check Active Flag via Python
                is_active = config.get("active")
                if str(is_active).lower() != "true":
                    continue

                # Check 1: Human Intervention (Redis)
                if await check_is_paused(chat_id):
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
                    try:
                        # GERAÇÃO IA (META)
                        analysis_prompt = f"""
                        Instrução de Retomada: "{prompt_behavior}"
                        
                        Contexto anterior: "{last_context_txt[-500:]}"

                        Gere uma mensagem curta e amigável para retomar contato. 
                        Apenas o texto.
                        """

                        if client:
                            resp = client.models.generate_content(
                                model="gemini-1.5-flash", contents=analysis_prompt
                            )
                            resp_ai = resp.text.strip()

                            # Salva usage para tracking
                            try:
                                from usage_tracker import save_usage

                                gemini_usage = {}
                                if (
                                    hasattr(resp, "usage_metadata")
                                    and resp.usage_metadata
                                ):
                                    gemini_usage = {
                                        "input_tokens": getattr(
                                            resp.usage_metadata, "prompt_token_count", 0
                                        ),
                                        "output_tokens": getattr(
                                            resp.usage_metadata,
                                            "candidates_token_count",
                                            0,
                                        ),
                                    }
                                save_usage(
                                    client_id=str(client_id),
                                    chat_id=chat_id,
                                    source="followup",
                                    provider="meta",
                                    gemini_usage=gemini_usage,
                                )
                            except Exception:
                                pass

                            # META OFFICIAL SPECIFIC SEND
                            meta_client_instance = MetaClient(token, phone_id)
                            await meta_client_instance.send_message_text(
                                chat_id, resp_ai
                            )

                            logger.info(
                                f"✅ [META] Sent Stage {current_stage_idx + 1} to {chat_id}"
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
                        logger.error(f"Erro AI Generation (Meta): {e}")


if __name__ == "__main__":
    asyncio.run(check_and_run_followups())
