from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import before_model
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from google import genai
from openai import BadRequestError
import os
import psycopg
import logging
import asyncio
import sys

# Garante acesso ao saas_db (mesmo diretório)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
# Tenta importar clear_chat_history, fail-safe se saas_db falhar
try:
    from saas_db import clear_chat_history
except ImportError:

    def clear_chat_history(id):
        logging.error("Função clear_chat_history não encontrada!")
        return False


logger = logging.getLogger("KestraChainsSaaS")

# Configuração Global
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    try:
        import streamlit as st

        OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        pass

DATABASE_URL = os.environ.get("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")

# --- DATABASE / CHECKPOINTER SETUP ---
# Conexão lazy para evitar conexões stale que o PostgreSQL fecha
_checkpointer = None
_conn = None


def get_checkpointer():
    """Retorna checkpointer, reconectando se necessário."""
    global _checkpointer, _conn

    if not DATABASE_URL:
        logger.warning("DATABASE_URL não encontrada. Checkpointer desabilitado.")
        return None

    try:
        # Testa se a conexão ainda está viva
        if _conn is not None:
            try:
                _conn.execute("SELECT 1")
            except Exception:
                logger.warning("⚠️ Conexão PostgreSQL stale detectada. Reconectando...")
                _conn = None
                _checkpointer = None

        # Cria nova conexão se necessário
        if _conn is None:
            _conn = psycopg.connect(DATABASE_URL, autocommit=True)
            _checkpointer = PostgresSaver(conn=_conn)
            _checkpointer.setup()
            logger.info("✅ PostgresSaver Checkpointer (re)conectado com sucesso.")

        return _checkpointer
    except Exception as e:
        logger.error(f"❌ Falha ao configurar Checkpointer: {e}")
        return None


# --- TOOLS ---


# Configura Gemini Client
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    try:
        import streamlit as st

        GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass
gemini_client = None
if GEMINI_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_KEY)
    except Exception as e:
        logger.error(f"Erro init Gemini Client: {e}")

# --- DYNAMIC TOOL FACTORY ---

# Acumulador de uso do Gemini RAG (resetado a cada ask_saas)
_gemini_usage_accumulator = {"input_tokens": 0, "output_tokens": 0}


def create_knowledge_base_tool(store_id: str):
    """
    Cria uma ferramenta de busca dinâmica ligada a um Vector Store (Enterprise) específico.
    """

    # Cache simples para evitar chamadas repetidas com mesma query
    _rag_cache = {}

    def search_func(query: str):
        if not gemini_client:
            return "Erro: Client Gemini não configurado."

        # Verifica cache (evita loop infinito)
        cache_key = f"{store_id}:{query}"
        if cache_key in _rag_cache:
            logger.info(f"📚 RAG Cache Hit: {query[:50]}...")
            return _rag_cache[cache_key]

        try:
            logger.info(f"📚 RAG Enterprise (v2-FIX): {store_id} | Query: {query}")

            # Padrão Enterprise: Queries usando a tool File Search no generate_content
            # Usando dicionário para garantir compatibilidade com proto e API REST
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=query,
                config={
                    "tools": [{"file_search": {"file_search_store_names": [store_id]}}]
                },
            )

            # Retorna o texto gerado (que é a resposta baseada nos docs)
            if response.text:
                # Limita resposta a 2000 chars para evitar overflow no OpenAI
                result = response.text[:2000]
                _rag_cache[cache_key] = result

                # Acumula usage do Gemini para tracking
                global _gemini_usage_accumulator
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    _gemini_usage_accumulator["input_tokens"] += getattr(
                        response.usage_metadata, "prompt_token_count", 0
                    )
                    _gemini_usage_accumulator["output_tokens"] += getattr(
                        response.usage_metadata, "candidates_token_count", 0
                    )

                return result
            return "Sem informações relevantes encontradas nos documentos."

        except Exception as e:
            logger.error(f"Erro RAG Enterprise: {e}")
            return f"Erro ao consultar Base de Conhecimento: {str(e)}"

    return StructuredTool.from_function(
        func=search_func,
        name="consultar_documentos_empresa",
        description="Use esta ferramenta para buscar informações nos manuais, PDFs e arquivos da empresa. O Gemini pesquisará internamente e retornará a resposta baseada nos documentos.",
    )


# --- FACTORY ---


def create_saas_agent(system_prompt: str, tools_list: list, store_id: str = None):
    """
    Cria um Agente OpenAI usando create_agent e PostgresSaver.
    Injeta dinamicamente o tool de Knowledge Base se store_id for válido.
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=OPENAI_API_KEY)

    final_tools = list(tools_list) if tools_list else []

    # Injeta Knowledge Base do Cliente (Enterprise usa nomes resource, ex: projects/... ou stores/...)
    # Nosso store_id local pode ser o 'name' completo ou apenas o ID.
    # O Gemini Manager v2 tenta usar o name completo.
    # Assume-se que store_id venha correto do DB (atualizado pelo Manager).

    if store_id:
        kb_tool = create_knowledge_base_tool(store_id)
        final_tools.append(kb_tool)
        logger.info(f"📎 Tool Enterprise Docs injetada: {store_id}")

    # --- CONTEXT TRIMMING (LangChain 1.0 Strict) ---

    # Middleware para Trimming (Max 20 mensagens)
    @before_model
    def trim_middleware(state, runtime) -> dict | None:
        messages = state["messages"]
        # Mantém System + Últimas 20 (aprox. 8k tokens)
        if len(messages) <= 20:
            return None

        # Limpa tudo e reinserir as ultimas 20
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages[-20:]]}

    logger.info("✂️ Context Trimmer ativado (Middleware LangChain 1.0).")

    return create_agent(
        model=llm,
        tools=final_tools,
        system_prompt=system_prompt,
        checkpointer=get_checkpointer(),
        middleware=[trim_middleware],
    )


# --- INTERFACE ---


async def ask_saas(
    query: str,
    chat_id: str,
    system_prompt: str,
    client_config: dict,
    tools_list: list = None,
):
    global _conn, _checkpointer  # Para poder resetar a conexão

    tools = tools_list or []
    store_id = client_config.get("gemini_store_id")

    # Reseta acumulador de Gemini usage
    global _gemini_usage_accumulator
    _gemini_usage_accumulator = {"input_tokens": 0, "output_tokens": 0}

    # Retry loop para lidar com conexões stale
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # 1. Cria o Agente (Passando Store ID)
            agent_runnable = create_saas_agent(system_prompt, tools, store_id=store_id)

            # 2. Config de Execução
            config = {"configurable": {"thread_id": chat_id}}

            # 3. Executa com Proteção
            try:
                result = await asyncio.to_thread(
                    agent_runnable.invoke,
                    {"messages": [("user", query)]},
                    config=config,
                )
            except BadRequestError as e:
                # AUTO-HEALING: Detecta erro de tool_calls pendentes e limpa
                error_str = str(e)
                if "tool_calls" in error_str or "400" in error_str:
                    logger.warning(
                        f"🚨 Histórico corrompido detectado para {chat_id}. Iniciando Auto-Limpeza..."
                    )
                    await asyncio.to_thread(clear_chat_history, chat_id)
                    return "⚠️ [Auto-Correção] Detectei um erro na minha memória recente. Reiniciei nosso contexto. Por favor, faça sua pergunta novamente."
                raise e

            # 4. Processa Resposta
            messages = result.get("messages", [])

            # Captura usage para tracking
            usage_data = {"openai": None, "gemini": _gemini_usage_accumulator.copy()}
            # Tenta extrair usage do OpenAI (via response_metadata)
            if messages and hasattr(messages[-1], "response_metadata"):
                token_usage = messages[-1].response_metadata.get("token_usage", {})
                if token_usage:
                    usage_data["openai"] = {
                        "input_tokens": token_usage.get("prompt_tokens", 0),
                        "output_tokens": token_usage.get("completion_tokens", 0),
                    }

            if messages:
                return messages[-1].content, usage_data
            else:
                return "Erro: Nenhuma resposta gerada.", usage_data

        except psycopg.OperationalError as e:
            # CONEXÃO STALE - Reconecta e tenta novamente
            logger.warning(
                f"⚠️ Conexão PostgreSQL perdida (tentativa {attempt + 1}/{max_retries}): {e}"
            )
            _conn = None
            _checkpointer = None

            if attempt < max_retries - 1:
                logger.info("🔄 Reconectando e tentando novamente...")
                continue
            else:
                logger.error("❌ Falha após todas as tentativas de reconexão")
                return (
                    "Desculpe, tive um problema de conexão. Por favor, tente novamente."
                )

        except Exception as e:
            logger.error(f"Erro no Agent SaaS: {e}", exc_info=True)
            return "Desculpe, tive um erro interno ao processar sua solicitação."
