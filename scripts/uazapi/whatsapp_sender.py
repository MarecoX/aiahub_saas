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

from uazapi_saas import send_whatsapp_message, send_whatsapp_audio
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

    # --- DETECT AUDIO URLs ---
    audio_urls_full = re.findall(
        r"https?://[^\s]+\.(?:mp3|wav|ogg|m4a|opus)", raw_response, re.IGNORECASE
    )

    # Remove audio URLs from text response
    text_response = raw_response
    for audio_url in audio_urls_full:
        text_response = text_response.replace(audio_url, "").strip()

    # Send audio FIRST (if any)
    for audio_url in audio_urls_full:
        try:
            await send_whatsapp_audio(
                chat_id, audio_url, api_key=dynamic_key, base_url=dynamic_url
            )
            logger.info(f"🔊 Áudio enviado: {audio_url[:60]}...")
            await asyncio.sleep(1.5)  # Delay between audio and text
        except Exception as e:
            logger.error(f"Erro ao enviar áudio {audio_url}: {e}")
    # -------------------------

    # Send text (without audio URLs)
    if text_response.strip():
        parts = _split_natural_messages(text_response)

        for i, part in enumerate(parts):
            try:
                await send_whatsapp_message(
                    chat_id, part, api_key=dynamic_key, base_url=dynamic_url
                )
                logger.info(f"Parte {i + 1}/{len(parts)} enviada.")
            except Exception as e:
                logger.error(f"Erro ao enviar parte {i}: {e}")

            # Delay pequeno entre mensagens (se houver mais de uma)
            if i < len(parts) - 1:
                delay = random.uniform(1.0, 3.0)
                await asyncio.sleep(delay)

    total_sent = len(audio_urls_full) + (len(parts) if text_response.strip() else 0)
    Kestra.outputs(
        {"status": "sent", "count": total_sent, "audios": len(audio_urls_full)}
    )


if __name__ == "__main__":
    asyncio.run(run_sender())
