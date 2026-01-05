import sys
import os
import asyncio
import logging
import redis.asyncio as redis

# import google.generativeai as genai  <-- REMOVED DEPRECATED SDK
from kestra import Kestra

# Adiciona o diretório shared ao path para importar módulos compartilhados
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
)
from saas_db import get_client_config, get_connection
from tools_library import get_enabled_tools

# Configuração de Logs
# Configuração de Logs
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger("KestraRAG")

# Configurações Globais
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BUFFER_KEY_SUFIX = os.getenv("BUFFER_KEY_SUFIX", "_buffer")


async def run_rag():
    logger.info("🚀 Iniciando Worker SaaS (Kestra 2.0)")

    # 1. Inputs do Kestra
    chat_id = os.getenv("KESTRA_CHAT_ID")
    client_token = os.getenv(
        "KESTRA_CLIENT_TOKEN"
    )  # <--- O Token que define quem paga a conta

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
        # Opcional: Mandar msg de erro pro WhatsApp
        return

    logger.info(f"🧠 Cliente Carregado: {client_config['name']}")
    system_prompt = client_config["system_prompt"]
    # store_id = client_config['gemini_store_id'] # Futuro: Usar no contexto

    # 3. Recuperar Mensagens do Redis (Buffer)
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

    # --- TRAP LIST (Check Pause) ---
    pause_key = f"ai_paused:{chat_id}"
    is_paused = await redis_client.get(pause_key)

    if is_paused:
        logger.warning(
            f"🛑 ATENÇÃO: Chat {chat_id} PAUSADO (Atendimento Humano). Ignorando ciclo."
        )
        # Limpa o buffer de mensagens acumuladas do usuário para não processar depois
        cleanup_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
        await redis_client.delete(cleanup_key)
        await redis_client.close()

        # Output VAZIO para não disparar envio
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
        return

    full_query = " ".join(msgs)
    logger.info(f"💬 Query do Usuário: {full_query}")

    # 4. Processamento Inteligente (Agente Híbrido: OpenAI + Gemini Tools)
    # Importa aqui para evitar circularidade se houver, ou move para topo
    from chains_saas import ask_saas

    try:
        # Carrega Tools Dinâmicas (passa chat_id para injeção em atendimento_humano)
        tools_list = get_enabled_tools(
            client_config.get("tools_config"),
            chat_id=chat_id,
            client_config=client_config,
        )

        # Chama o Cérebro (OpenAI) passando as Tools (Gemini/Maps)
        response_text = await ask_saas(
            query=full_query,
            chat_id=chat_id,
            system_prompt=system_prompt,
            client_config=client_config,
            tools_list=tools_list,
        )

        logger.info(f"🤖 Resposta Agente SaaS: {response_text[:50]}...")

        # --- TRACKING UPDATE (Follow-up System) ---
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Atualiza status para 'assistant' e timestamp
                    # Não altera o estágio (se já estiver em follow-up, o worker de follow-up que decide)
                    # Mas se for uma resposta normal, mantemos o estágio (ou resetamos? Se o bot responde, esperamos o user)
                    # Se o bot respondeu, a bola está com o user. Se o user nao responder, stage 1 entra.
                    # Então stage deve ser mantido ou 0? Se era 0, continua 0.
                    # Se era um follow-up que acabou de rodar (via outro worker), esse worker aqui é o RAG normal.
                    # RAG normal = Resposta a uma pergunta do user.
                    # Logo, o user perguntou (ingest setou user/0). Bot respondeu (setamos assistant).
                    # Entao stage continua 0. O próximo será 1.

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
            logger.info(f"🔄 Tracking atualizado para {chat_id} (Assistant Reply)")
        except Exception as e:
            logger.error(f"⚠️ Erro ao atualizar tracking RAG: {e}")
        # ------------------------------------------

        # 5. Output para o Kestra (Task de Envio)
        # Prioridade de Credenciais:
        # 1. Colunas Diretas (api_url, token)
        # 2. Tools Config (whatsapp.url, whatsapp.key)
        # 3. Input Kestra (client_token) para api_key

        tools_cfg = client_config.get("tools_config", {}) or {}
        w_cfg = tools_cfg.get("whatsapp", {})

        api_override_url = client_config.get("api_url") or w_cfg.get("url") or ""
        api_override_key = (
            client_config.get("token") or w_cfg.get("key") or client_token or ""
        )

        Kestra.outputs(
            {
                "response_text": response_text,
                "chat_id": chat_id,
                "api_url": api_override_url,
                "api_key": api_override_key,
            }
        )

    except Exception as e:
        logger.error(f"❌ Erro na Geração IA: {e}", exc_info=True)
        raise e


if __name__ == "__main__":
    asyncio.run(run_rag())
