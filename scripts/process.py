import sys
import os
import asyncio
import logging
import random

# Adiciona o diretório pai (IA) ao path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from chains import ask
from uazapi import send_whatsapp_message
from message_buffer import _split_natural_messages 
from config import REDIS_URL, BUFFER_KEY_SUFIX, DEBOUNCE_SECONDS
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KestraProcess")

async def run_process(chat_id):
    """
    Verifica se é hora de processar o buffer e executa a IA.
    """
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    buffer_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
    
    # 1. Verifica mensagens
    messages = await redis_client.lrange(buffer_key, 0, -1)
    
    if not messages:
        logger.info(f"Nenhuma mensagem no buffer para {chat_id}. Encerrando.")
        return

    # TODO: Lógica de Debounce
    # No Kestra, podemos simplesmente processar o que tem.
    # Para ser fiel ao debounce, precisaríamos checar o timestamp da última inserção.
    # Assumindo que o fluxo Kestra tem um 'Wait' antes desse script ou roda agendado.
    
    full_message = " ".join(messages).strip()
    logger.info(f"🤖 Processando conversa de {chat_id}: {full_message[:50]}...")
    
    try:
        # 2. Chama a IA (RAG)
        # O 'ask' carrega o Chroma internamente
        ai_response = await ask(
            user_query=full_message,
            user_id=chat_id
        )
        
        # 3. Envio (com Splitting)
        response_parts = _split_natural_messages(ai_response)
        
        logger.info(f"✅ Resposta gerada. Enviando {len(response_parts)} partes.")

        for i, part in enumerate(response_parts):
            await send_whatsapp_message(
                number=chat_id,
                text=part
            )
            if i < len(response_parts) - 1:
                delay = random.uniform(1.0, 3.0)
                await asyncio.sleep(delay)

        # 4. Limpa buffer
        await redis_client.delete(buffer_key)
        
    except Exception as e:
        logger.error(f"Erro no processamento: {e}", exc_info=True)
        raise e

if __name__ == "__main__":
    # Espera chat_id como argumento ou variavel
    chat_id_arg = os.getenv("KESTRA_CHAT_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    
    if not chat_id_arg:
        logger.error("Chat ID não fornecido.")
        sys.exit(1)
        
    asyncio.run(run_process(chat_id_arg))
