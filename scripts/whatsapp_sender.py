import sys
import os
import asyncio
import logging
import random
from kestra import Kestra

# Adiciona o diretório avô (IA / Root) ao path para importar módulos da raiz
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# --- BOOTSTRAP AMBIENTE KESTRA (Igual ao rag_worker.py) ---
def ensure_env(key, default):
    if not os.getenv(key):
        print(f"⚠️ [BOOTSTRAP-Sender] Variável {key} não encontrada. Usando default: {default}")
        os.environ[key] = default

ensure_env("VECTOR_STORE_PATH", "vectorstore")
ensure_env("RAG_FILES_DIR", "rag_files")
ensure_env("BUFFER_KEY_SUFIX", "_buffer")
ensure_env("BUFFER_TTL", "300")
# Corrige incompatibilidade de nomes (Kestra usa DATABASE_URL, App usa DATABASE_CONNECTION_URI)
if os.getenv("DATABASE_URL") and not os.getenv("DATABASE_CONNECTION_URI"):
    os.environ["DATABASE_CONNECTION_URI"] = os.getenv("DATABASE_URL")

from uazapi_saas import send_whatsapp_message
from message_buffer import _split_natural_messages

# Configura logs para sair no STDOUT (evita ficar vermelho/ERROR no Kestra)
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("KestraSend")

async def run_sender():
    chat_id = os.getenv("KESTRA_CHAT_ID")
    raw_response = os.getenv("KESTRA_RESPONSE_TEXT")
    
    if not chat_id or not raw_response:
        logger.info("Nada para enviar.")
        return

    # Usa a função de split centralizada
    parts = _split_natural_messages(raw_response)
    
    for i, part in enumerate(parts):
        try:
            # Usa a função de envio centralizada
            await send_whatsapp_message(chat_id, part)
            logger.info(f"Parte {i+1}/{len(parts)} enviada.")
        except Exception as e:
            logger.error(f"Erro ao enviar parte {i}: {e}")
        
        # Delay pequeno entre mensagens (se houver mais de uma)
        if i < len(parts) - 1:
            delay = random.uniform(1.0, 3.0)
            await asyncio.sleep(delay)

    Kestra.outputs({'status': 'sent', 'count': len(parts)})

if __name__ == "__main__":
    asyncio.run(run_sender())
