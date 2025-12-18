import sys
import os
import asyncio
import json
import logging
import redis.asyncio as redis
from kestra import Kestra

# Adiciona o diretório pai (IA) ao path para importar módulos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from message_handler import handle_message
from config import REDIS_URL, BUFFER_KEY_SUFIX, BUFFER_TTL

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
            logger.info("👋 Detectada mensagem humana (fromMe=True). Iniciando bloqueio da IA...")
            
            try:
                # Recupera Token para config personalizada
                token = webhook_data.get("token") or webhook_data.get("instanceId")
                pause_time_min = 60 # Default
                
                if token:
                    # Importação atrasada para evitar ciclo de import circular se houver
                    from saas_db import get_client_config
                    client_cfg = get_client_config(token)
                    if client_cfg and client_cfg.get("human_attendant_timeout"):
                        pause_time_min = client_cfg["human_attendant_timeout"]
                        
                pause_ttl = pause_time_min * 60
                
                # Seta a chave no Redis
                pause_key = f"ai_paused:{chat_id}"
                redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                await redis_client.set(pause_key, "true", ex=pause_ttl)
                await redis_client.aclose()
                
                logger.warning(f"🛑 IA PAUSADA por {pause_time_min} min para chat {chat_id} (Trap List Triggered)")
                
            except Exception as e:
                logger.error(f"Erro ao ativar Trap List: {e}")
                
            return
            
        # Ignora grupos se necessário
        if "@g.us" in chat_id:
            logger.info("Ignorando mensagem de grupo.")
            return

        logger.info(f"Processando mensagem de: {chat_id}")

        # 3. Processa Mídia/Texto (Usa lógica central robusta do message_handler)
        msg_info = await handle_message(message_data)

        if not msg_info.should_process:
            logger.info(f"Mensagem ignorada (tipo {msg_info.message_type}).")
            return

        # 4. Salva no Redis (Buffer)
        text_content = str(msg_info.text) if msg_info.text is not None else ""
        if isinstance(msg_info.text, dict):
            logger.warning(f"⚠️ Alerta: msg_info.text era um dicionário! {msg_info.text}")
            text_content = json.dumps(msg_info.text) # Serializa se for dict
            
        buffer_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
        
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        await redis_client.rpush(buffer_key, text_content)
        await redis_client.expire(buffer_key, int(BUFFER_TTL))
        
        logger.info(f"✅ Mensagem salva no buffer Redis: {text_content[:50]}...")
        
        # 5. Output para Kestra (Crítico para passar chat_id para próxima task)
        Kestra.outputs({
            'chat_id': chat_id, 
            'status': 'buffered',
            'preview': text_content[:50]
        })

    except Exception as e:
        logger.error(f"Erro na ingestão: {e}", exc_info=True)
        raise e

if __name__ == "__main__":
    # O Kestra passa inputs via variáveis ou args.
    kestra_input = os.getenv("KESTRA_TRIGGER_BODY") or (sys.argv[1] if len(sys.argv) > 1 else None)
    
    if not kestra_input:
        logger.error("Nenhum input fornecido.")
        # Não falha hard para não quebrar fluxo se for trigger vazio, mas loga erro
        sys.exit(0) 
        
    asyncio.run(run_ingest(kestra_input))
