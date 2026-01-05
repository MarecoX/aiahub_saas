import os
import sys
import redis.asyncio as redis
import logging
import asyncio
from kestra import Kestra

# Import local modules


# Adiciona o diretório 'shared' ao path para importar módulos compartilhados
current_dir = os.path.dirname(os.path.abspath(__file__))
shared_dir = os.path.join(os.path.dirname(current_dir), "shared")
sys.path.append(shared_dir)

from config import REDIS_URL, BUFFER_KEY_SUFIX
from saas_db import get_client_config, get_connection  # noqa: E402
from tools_library import get_enabled_tools  # noqa: E402

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RAG_Worker_LP")


async def run_rag():
    logger.info("🚀 Iniciando Worker SaaS (LancePilot)")

    # 1. Inputs do Kestra
    chat_id = os.getenv("KESTRA_CHAT_ID")
    client_token = os.getenv(
        "KESTRA_CLIENT_TOKEN"
    )  # O TOKEN que veio da URL do Webhook

    if not chat_id or chat_id == "None":
        logger.info("Nenhum Chat ID para processar. Encerrando.")
        return

    if not client_token:
        logger.error(
            "❌ ERRO: KESTRA_CLIENT_TOKEN não fornecido! O Worker não sabe quem é o cliente."
        )
        return

    # 2. Carregar "Cérebro" do Banco de Dados
    logger.info(f"🔍 Buscando configs para o token: {client_token}")
    client_config = get_client_config(client_token)

    if not client_config:
        logger.error("❌ Cliente não encontrado no Banco de Dados. Abortando.")
        return

    logger.info(f"🧠 Cliente Carregado: {client_config['name']}")
    system_prompt = client_config["system_prompt"]

    # 3. Recuperar Mensagens do Redis (Buffer)
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    # --- TRAP LIST (Check Pause Manual) ---
    pause_key = f"ai_paused:{chat_id}"
    logger.info(f"Checking Pause Key: {pause_key}")
    is_paused = await redis_client.get(pause_key)

    if is_paused:
        logger.warning(
            f"🛑 ATENÇÃO: Chat {chat_id} PAUSADO (Atendimento Humano). Ignorando ciclo."
        )
        cleanup_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
        await redis_client.delete(cleanup_key)
        await redis_client.close()

        Kestra.outputs({"response_text": "", "chat_id": chat_id})
        return
    # -------------------------------

    key = f"{chat_id}{BUFFER_KEY_SUFIX}"

    # Leitura + Limpeza Atômica
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        results = await pipe.execute()

    msgs = results[0]

    if not msgs:
        logger.info(f"Buffer vazio para {chat_id}. Worker duplicado?")
        await redis_client.close()
        return

    full_query = " ".join(msgs)
    logger.info(f"💬 Query do Usuário: {full_query}")

    # 4. Processamento Inteligente
    from chains_saas import ask_saas

    try:
        # Carrega Tools Dinâmicas (passa chat_id e client_config para injeção correta)
        tools_list = get_enabled_tools(
            client_config.get("tools_config"),
            chat_id=chat_id,
            client_config=client_config,
        )

        # Chama o Cérebro (OpenAI)
        response_text = await ask_saas(
            query=full_query,
            chat_id=chat_id,
            system_prompt=system_prompt,
            client_config=client_config,
            tools_list=tools_list,
        )

        logger.info(f"🤖 Resposta Agente: {response_text[:50]}...")

        # --- TRACKING UPDATE ---
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO active_conversations (chat_id, client_id, last_message_at, last_role, status, last_context)
                        VALUES (%s, %s, NOW(), 'assistant', 'active', %s)
                        ON CONFLICT (chat_id, client_id) DO UPDATE SET
                            last_message_at = NOW(),
                            last_role = 'assistant',
                            status = 'active',
                            last_context = COALESCE(active_conversations.last_context, '') || E'\nAI: ' || EXCLUDED.last_context;
                    """,
                        (chat_id, client_config["id"], response_text),
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"⚠️ Erro ao atualizar tracking RAG: {e}")
        # -----------------------

        # 5. Output para o Kestra (Task de Envio LancePilot)
        # Credenciais LancePilot agora vêm de colunas, não JSON
        lp_token = client_config.get("lancepilot_token") or ""
        lp_workspace = client_config.get("lancepilot_workspace_id") or ""

        if not lp_token or not lp_workspace:
            logger.warning("⚠️ Configuração LancePilot ausente neste cliente!")

        Kestra.outputs(
            {
                "response_text": response_text,
                "chat_id": chat_id,
                "lp_token": lp_token or "",
                "lp_workspace": lp_workspace or "",
            }
        )

    except Exception as e:
        logger.error(f"❌ Erro na Geração IA: {e}", exc_info=True)
        raise e
    finally:
        if redis_client:
            await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_rag())
