import asyncio
import redis.asyncio as redis
from collections import defaultdict
from config import REDIS_URL, BUFFER_KEY_SUFIX, BUFFER_TTL, DEBOUNCE_SECONDS
from uazapi import send_whatsapp_message

import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MessageBuffer")

# Cliente Redis
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# Dicionário para gerenciar tarefas de debounce
debounce_tasks = {}


async def buffer_message(chat_id: str, message: str):
    """
    Adiciona mensagem ao buffer e reinicia o timer de debounce.
    """
    buffer_key = f"{chat_id}{BUFFER_KEY_SUFIX}"

    # Adiciona mensagem na lista do Redis
    await redis_client.rpush(buffer_key, message)
    await redis_client.expire(buffer_key, int(BUFFER_TTL))

    logger.info(f"📥 [Buffer] Mensagem de {chat_id} adicionada: {message[:30]}...")

    # Cancela timer anterior se existir
    if chat_id in debounce_tasks:
        task = debounce_tasks[chat_id]
        if not task.done():
            task.cancel()
            logger.debug(f"⏱️ [Buffer] Timer cancelado para {chat_id}")

    # Cria novo timer
    debounce_tasks[chat_id] = asyncio.create_task(handle_debounce(chat_id))


import re
import random


def _split_natural_messages(text: str) -> list[str]:
    """
    Divide o texto em blocos naturais.
    - Parágrafos de texto são separados em mensagens individuais.
    - Listas (numeradas ou bullets) são agrupadas em uma única mensagem.
    """
    if not text:
        return []

    # Limpeza de Markdown
    text = text.replace("**", "*")  # Converte bold MD para bold WhatsApp
    text = (
        text.replace("### ", "").replace("## ", "").replace("# ", "")
    )  # Remove headers

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return []

    chunks = []
    current_block = []

    for line in lines:
        # Detecta se é item de lista (1. , -, *)
        is_list_item = re.match(r"^(\d+[\.)]|\*|-)\s+", line)

        if not current_block:
            current_block.append(line)
            continue

        # Verifica linha anterior (para decidir se agrupa)
        last_line = current_block[-1]
        last_was_list = re.match(r"^(\d+[\.)]|\*|-)\s+", last_line)

        if is_list_item and last_was_list:
            # Continuação de lista -> Agrupa
            current_block.append(line)
        else:
            # MUDANÇA: Agora agrupa TUDO (não divide por contexto)
            # Só divide se a IA gerou \n\n explícito (tratado antes)
            current_block.append(line)

    if current_block:
        chunks.append("\n".join(current_block))

    return chunks


async def handle_debounce(chat_id: str):
    """
    Aguarda o tempo de debounce e processa as mensagens acumuladas.
    """
    try:
        logger.info(
            f"⏳ [Buffer] Iniciando espera de {DEBOUNCE_SECONDS}s para {chat_id}"
        )
        await asyncio.sleep(int(DEBOUNCE_SECONDS))

        logger.info(f"🚀 [Buffer] Processando mensagens de {chat_id}")

        buffer_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
        messages = await redis_client.lrange(buffer_key, 0, -1)

        full_message = " ".join(messages).strip()

        if full_message:
            logger.info(f"🤖 [Buffer] Enviando para IA: {full_message[:50]}...")

            # Chama a IA
            # Legacy Logic - Disabled for Kestra V2
            # ai_response = await ask(
            #     user_query=full_message,
            #     user_id=chat_id
            # )

            # Divide a resposta em balões menores
            # response_parts = _split_natural_messages(ai_response)

            # logger.info(f"✅ [Buffer] Resposta recebida. Enviando {len(response_parts)} partes para WhatsApp...")

            # for i, part in enumerate(response_parts):
            #     # Envia cada parte
            #     await send_whatsapp_message(
            #         number=chat_id,
            #         text=part
            #     )

            #     # Se não for a última mensagem, espera um pouco para dar ar de "naturalidade"
            #     # Um delay baseado no tamanho do texto lido ou apenas um respiro
            #     if i < len(response_parts) - 1:
            #         # Delay aleatório entre 1s e 3s para simular "digitando" ou leitura
            #         delay = random.uniform(1.0, 3.0)
            #         await asyncio.sleep(delay)
            pass

        # Limpa o buffer
        await redis_client.delete(buffer_key)

        # Remove a task do dicionário
        if chat_id in debounce_tasks:
            del debounce_tasks[chat_id]

    except asyncio.CancelledError:
        logger.debug(f"🚫 [Buffer] Tarefa cancelada para {chat_id}")
        raise
    except Exception as e:
        logger.error(f"❌ [Buffer] Erro ao processar buffer: {e}", exc_info=True)
