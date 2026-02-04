import sys
import os
import asyncio
import logging
import random
from kestra import Kestra

# Adiciona shared folder e uazapi folder ao path
shared_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
uazapi_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(shared_dir)
sys.path.append(uazapi_dir)


# --- BOOTSTRAP AMBIENTE KESTRA (Igual ao rag_worker.py) ---
def ensure_env(key, default):
    if not os.getenv(key):
        print(
            f"⚠️ [BOOTSTRAP-Sender] Variável {key} não encontrada. Usando default: {default}"
        )
        os.environ[key] = default


ensure_env("VECTOR_STORE_PATH", "vectorstore")
ensure_env("RAG_FILES_DIR", "rag_files")
ensure_env("BUFFER_KEY_SUFIX", "_buffer")
ensure_env("BUFFER_TTL", "300")
# Corrige incompatibilidade de nomes (Kestra usa DATABASE_URL, App usa DATABASE_CONNECTION_URI)
if os.getenv("DATABASE_URL") and not os.getenv("DATABASE_CONNECTION_URI"):
    os.environ["DATABASE_CONNECTION_URI"] = os.getenv("DATABASE_URL")

from uazapi_saas import send_whatsapp_message, send_whatsapp_audio, send_whatsapp_media
from message_buffer import _split_natural_messages

# Configura logs para sair no STDOUT (evita ficar vermelho/ERROR no Kestra)
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("KestraSend")


async def run_sender():
    import re

    chat_id = os.getenv("KESTRA_CHAT_ID")
    raw_response = os.getenv("KESTRA_RESPONSE_TEXT")

    if not chat_id or not raw_response:
        logger.info("Nada para enviar.")
        return

    # Dynamic Routing (Instance Selection)
    dynamic_url = os.getenv("KESTRA_API_URL")
    dynamic_key = os.getenv("KESTRA_API_KEY")

    # --- SEO/SEQUENTIAL SENDING LOGIC ---
    # O objetivo é respeitar a ordem: Texto -> Imagem -> Texto -> Video...
    
    media_extensions = r"\.(?:mp3|wav|ogg|m4a|opus|mp4|avi|mov|jpg|jpeg|png|gif|webp|pdf|doc|docx|xls|xlsx|txt|csv)"
    
    # Combina Regex para pegar Markdown OU Raw Link
    # Group 1: Caption (Markdown)
    # Group 2: URL (Markdown)
    # Group 3: URL (Raw)
    pattern = re.compile(
        r"\[([^\]]*)\]\((https?://[^\)]+" + media_extensions + r")\)|"  # Markdown
        r"((?<!\()https?://[^\s]+" + media_extensions + r")",           # Raw
        re.IGNORECASE
    )

    last_pos = 0
    total_sent = 0
    medias_count = 0
    
    for match in pattern.finditer(raw_response):
        # 1. Envia o TEXTO antes da mídia (se houver)
        pre_text = raw_response[last_pos : match.start()].strip()
        if pre_text:
            parts = _split_natural_messages(pre_text)
            for part in parts:
                try:
                    await send_whatsapp_message(
                        chat_id, part, api_key=dynamic_key, base_url=dynamic_url
                    )
                    logger.info(f"📝 Texto enviado: {part[:30]}...")
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    total_sent += 1
                except Exception as e:
                    logger.error(f"Erro ao enviar texto: {e}")

        # 2. Prepara a MÍDIA
        caption = match.group(1) or ""
        url = match.group(2) or match.group(3)
        
        # Limpa legenda se for igual a URL ou vazia
        if caption.strip() == url.strip() or caption.startswith("http"):
            caption = ""

        # Determina tipo
        media_type = "document"
        ext = url.split(".")[-1].lower()
        if ext in ["mp3", "wav", "ogg", "m4a", "opus"]:
            media_type = "audio"
        elif ext in ["mp4", "avi", "mov"]:
            media_type = "video"
        elif ext in ["jpg", "jpeg", "png", "gif", "webp"]:
            media_type = "image"
            
        # 3. Envia a MÍDIA
        try:
            if media_type == "audio":
                await send_whatsapp_audio(
                    chat_id, url, api_key=dynamic_key, base_url=dynamic_url
                )
            else:
                await send_whatsapp_media(
                    chat_id, 
                    url, 
                    media_type=media_type, 
                    caption=caption, # Envia legenda junto com a mídia (se houver)
                    api_key=dynamic_key, 
                    base_url=dynamic_url
                )
            logger.info(f"📎 Mídia enviada ({media_type}): {url[:30]}...")
            medias_count += 1
            total_sent += 1
            await asyncio.sleep(1.5) # Tempo para processar mídia
        except Exception as e:
            logger.error(f"Erro ao enviar mídia {url}: {e}")

        last_pos = match.end()

    # 4. Envia o RESTANTE do texto (pós-última mídia)
    remaining_text = raw_response[last_pos:].strip()
    if remaining_text:
        parts = _split_natural_messages(remaining_text)
        for part in parts:
            try:
                await send_whatsapp_message(
                    chat_id, part, api_key=dynamic_key, base_url=dynamic_url
                )
                logger.info(f"� Texto final enviado: {part[:30]}...")
                await asyncio.sleep(random.uniform(1.0, 2.0))
                total_sent += 1
            except Exception as e:
                logger.error(f"Erro ao enviar texto final: {e}")

    Kestra.outputs(
        {"status": "sent", "count": total_sent, "medias": medias_count})


if __name__ == "__main__":
    asyncio.run(run_sender())
