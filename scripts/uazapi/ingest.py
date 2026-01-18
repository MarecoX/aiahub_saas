import sys
import os
import asyncio
import json
import logging

import redis.asyncio as redis
from kestra import Kestra

# Adiciona o diretório shared ao path para importar módulos compartilhados
# Usa insert(0) para dar PRIORIDADE ao shared sobre outros locais
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
)

from message_handler import handle_message
from config import REDIS_URL, BUFFER_KEY_SUFIX, BUFFER_TTL
from saas_db import get_connection, get_client_config

# Configuração de Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KestraIngest")


async def run_ingest(webhook_data):
    """
    Processa o webhook de entrada e salva no buffer do Redis.
    """
    try:
        # 1. Parse Input
        if isinstance(webhook_data, str):
            try:
                webhook_data = json.loads(webhook_data)
            except json.JSONDecodeError:
                logger.error("Falha ao decodificar JSON de entrada.")
                return

        message_data = webhook_data.get("message", {})

        # 2. Safety Checks (Igual ao antigo ingest_adapter.py)
        # Suporte a chatid ou remoteJid
        chat_id = message_data.get("chatid") or message_data.get("remoteJid")

        if not chat_id:
            logger.warning("Mensagem ignorada: sem chat_id ou remoteJid.")
            return

        # Ignora mensagens do próprio bot e ATIVA MODO PAUSA (Human Takeover)
        if message_data.get("fromMe"):
            logger.info(
                "👋 Detectada mensagem humana (fromMe=True). Iniciando bloqueio da IA..."
            )

            try:
                # Recupera Token para config personalizada
                token = webhook_data.get("token") or webhook_data.get("instanceId")
                pause_time_min = 60  # Default

                if token:
                    client_cfg = get_client_config(token)
                    if client_cfg and client_cfg.get("human_attendant_timeout"):
                        pause_time_min = client_cfg["human_attendant_timeout"]

                pause_ttl = pause_time_min * 60

                # Seta a chave no Redis
                pause_key = f"ai_paused:{chat_id}"
                redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                await redis_client.set(pause_key, "true", ex=pause_ttl)
                await redis_client.aclose()

                logger.warning(
                    f"🛑 IA PAUSADA por {pause_time_min} min para chat {chat_id} (Trap List Triggered)"
                )

            except Exception as e:
                logger.error(f"Erro ao ativar Trap List: {e}")

            return

        # Ignora grupos se necessário
        if "@g.us" in chat_id:
            logger.info("Ignorando mensagem de grupo.")
            return

        logger.info(f"Processando mensagem de: {chat_id}")

        # --- Busca credenciais do cliente para download de mídia ---
        token = webhook_data.get("token") or webhook_data.get("instanceId")
        api_url = None
        api_key = None

        if token:
            client_config = get_client_config(token)
            if client_config:
                # Prioridade: tools_config.uazapi > colunas diretas
                tools_cfg = client_config.get("tools_config") or {}
                uazapi_cfg = tools_cfg.get("uazapi", {})

                api_url = uazapi_cfg.get("url") or client_config.get("api_url")
                api_key = uazapi_cfg.get("api_key") or client_config.get("token")
        # -----------------------------------------------------------

        # 3. Processa Mídia/Texto (Usa lógica central robusta do message_handler)
        # 3. Processa Mídia/Texto (Usa lógica central robusta do message_handler)
        # --- SMART CALL v2 (Suporte a versões 1.0, 1.1 e 1.2) ---
        import inspect
        try:
            sig = inspect.signature(handle_message)
            call_kwargs = {}
            
            # Suporte a credenciais (v1.1+)
            if "api_url" in sig.parameters:
                call_kwargs["api_url"] = api_url
                call_kwargs["api_key"] = api_key
            
            # Suporte a tracking (v1.2+)
            if "client_id" in sig.parameters:
                c_id = client_config.get("id") if token and client_config else None
                call_kwargs["client_id"] = str(c_id) if c_id else None
                call_kwargs["chat_id"] = chat_id

            logger.info(f"🚀 Chamando handle_message com args: {list(call_kwargs.keys())}")
            msg_info = await handle_message(message_data, **call_kwargs)

        except Exception as e:
            logger.error(f"Erro ao inspecionar/chamar handle_message: {e}")
            # Fallback de emergência (v1.0)
            msg_info = await handle_message(message_data)
        # -------------------------------------------------------------------------------

        if not msg_info.should_process:
            logger.info(f"Mensagem ignorada (tipo {msg_info.message_type}).")
            return

        # 4. Salva no Redis (Buffer)
        text_content = str(msg_info.text) if msg_info.text is not None else ""
        if isinstance(msg_info.text, dict):
            logger.warning(
                f"⚠️ Alerta: msg_info.text era um dicionário! {msg_info.text}"
            )
            text_content = json.dumps(msg_info.text)  # Serializa se for dict

        # --- COMANDOS ESPECIAIS (Palavras-chave) ---
        message_lower = text_content.strip().lower()
        token = webhook_data.get("token") or webhook_data.get("instanceId")

        # DEBUG: Ver exatamente o que está chegando
        logger.info(
            f"🔍 DEBUG message_lower='{message_lower}' (len={len(message_lower)})"
        )

        if message_lower == "#reset":
            # Limpa memória/histórico do chat
            logger.info(f"🔄 Comando #reset detectado para {chat_id}")
            try:
                from saas_db import clear_chat_history

                clear_chat_history(chat_id)
                logger.info(f"✅ Histórico limpo para {chat_id}")
            except Exception as e:
                logger.error(f"Erro ao limpar histórico: {e}")
            Kestra.outputs(
                {
                    "chat_id": str(chat_id),
                    "client_token": token or "",
                    "status": "reset_executed",
                }
            )
            return

        if message_lower == "#ativar":
            # Remove pausa de atendimento humano
            logger.info(f"✅ Comando #ativar detectado para {chat_id}")
            try:
                pause_key = f"ai_paused:{chat_id}"
                redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                deleted = await redis_client.delete(pause_key)
                if deleted:
                    logger.info(f"🤖 IA reativada para {chat_id}")
                else:
                    logger.info(f"IA já estava ativa para {chat_id}")
                await redis_client.aclose()
            except Exception as e:
                logger.error(f"Erro ao reativar IA: {e}")
            Kestra.outputs(
                {
                    "chat_id": str(chat_id),
                    "client_token": token or "",
                    "status": "ai_reactivated",
                }
            )
            return

        if message_lower in ["#stop", "#pausa"]:
            # Pausa IA (Modo Humano)
            logger.info(f"🛑 Comando #stop detectado para {chat_id}")
            try:
                pause_key = f"ai_paused:{chat_id}"
                redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                # Pausa por 24h
                await redis_client.set(pause_key, "true", ex=86400)
                await redis_client.aclose()
                logger.info(f"🛑 IA pausada manualmente para {chat_id}")
            except Exception as e:
                logger.error(f"Erro ao pausar IA: {e}")
            Kestra.outputs(
                {
                    "chat_id": str(chat_id),
                    "client_token": token or "",
                    "status": "ai_paused_manual",
                }
            )
            return
        # --- FIM COMANDOS ESPECIAIS ---

        buffer_key = f"{chat_id}{BUFFER_KEY_SUFIX}"

        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

        await redis_client.rpush(buffer_key, text_content)
        await redis_client.expire(buffer_key, int(BUFFER_TTL))

        logger.info(f"✅ Mensagem salva no buffer Redis: {text_content[:50]}...")

        # --- TRACKING UPDATE (Follow-up System) ---
        try:
            token = webhook_data.get("token") or webhook_data.get("instanceId")
            if token:
                # Importação lazy ou uso direto se já importado
                client_cfg = get_client_config(token)
                if client_cfg:
                    client_id = client_cfg["id"]

                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            # Upsert na tabela de rastreamento (Multi-Tenant safe)
                            # Resetamos status='active' e followup_stage=0 pois user falou
                            cur.execute(
                                """
                                INSERT INTO active_conversations (chat_id, client_id, last_message_at, last_role, followup_stage, status, last_context)
                                VALUES (%s, %s, NOW(), 'user', 0, 'active', %s)
                                ON CONFLICT (chat_id, client_id) DO UPDATE SET
                                    last_message_at = NOW(),
                                    last_role = 'user',
                                    followup_stage = 0,
                                    status = 'active',
                                    last_context = EXCLUDED.last_context;
                            """,
                                (chat_id, client_id, text_content),
                            )
                            conn.commit()
                    logger.info(
                        f"🔄 Tracking atualizado para {chat_id} (Client {client_id}) - User Reset"
                    )
        except Exception as e:
            logger.error(f"⚠️ Erro ao atualizar tracking: {e}")
        # ------------------------------------------

        # 5. Output para Kestra (Crítico para passar chat_id para próxima task)
        Kestra.outputs(
            {"chat_id": chat_id, "status": "buffered", "preview": text_content[:50]}
        )

    except Exception as e:
        logger.error(f"Erro na ingestão: {e}", exc_info=True)
        raise e


if __name__ == "__main__":
    # O Kestra passa inputs via variáveis ou args.
    kestra_input = os.getenv("KESTRA_TRIGGER_BODY") or (
        sys.argv[1] if len(sys.argv) > 1 else None
    )

    if not kestra_input:
        logger.error("Nenhum input fornecido.")
        # Não falha hard para não quebrar fluxo se for trigger vazio, mas loga erro
        sys.exit(0)

    asyncio.run(run_ingest(kestra_input))
