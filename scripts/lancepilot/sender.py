import os
import sys
import logging
import asyncio
import random

# Fix Sys Path - use shared folder
current_dir = os.path.dirname(os.path.abspath(__file__))
shared_dir = os.path.join(os.path.dirname(current_dir), "shared")
sys.path.append(shared_dir)
# Also add lancepilot folder itself for lancepilot.client
sys.path.append(os.path.dirname(current_dir))

# Import Local
from message_buffer import _split_natural_messages
from lancepilot.client import LancePilotClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LancePilotSender")


async def run_sender():
    logger.info("🚀 Iniciando Worker de Envio (LancePilot)")

    # 1. Inputs do Kestra (Outputs do RAG Worker)
    chat_id = os.getenv("KESTRA_CHAT_ID")
    response_text = os.getenv("KESTRA_RESPONSE_TEXT")
    lp_token = os.getenv("KESTRA_LP_TOKEN")
    lp_workspace = os.getenv("KESTRA_LP_WORKSPACE")

    if not chat_id or chat_id == "None":
        logger.info("Nenhum destinatário. Fim.")
        return

    if not response_text:
        logger.info("Resposta vazia. Nada a enviar.")
        return

    if not lp_token or not lp_workspace:
        logger.error(
            "❌ Credenciais LancePilot ausentes (LP_TOKEN ou LP_WORKSPACE). Não é possível enviar."
        )
        return

    try:
        # Divide a resposta
        parts = _split_natural_messages(response_text)
        logger.info(f"📤 Enviando {len(parts)} mensagens para {chat_id} via LP...")

        client = LancePilotClient(lp_token)

        for i, part in enumerate(parts):
            client.send_text_message_via_number(
                workspace_id=lp_workspace, phone_number=chat_id, text=part
            )

            # Delay natural
            if i < len(parts) - 1:
                delay = random.uniform(1.0, 3.0)
                await asyncio.sleep(delay)

        logger.info("✅ Envio concluído com sucesso.")

    except Exception as e:
        logger.error(f"❌ Erro no Envio LP: {e}", exc_info=True)
        raise e


if __name__ == "__main__":
    asyncio.run(run_sender())
