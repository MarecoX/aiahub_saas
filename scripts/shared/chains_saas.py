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


# --- MULTIMODIAL HELPERS ---
def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcreve áudio usando OpenAI Whisper."""
    try:
        from openai import OpenAI
        import io

        client = OpenAI(api_key=OPENAI_API_KEY)

        # Cria um arquivo em memória com nome fake .mp3 para o Whisper aceitar
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.mp3"

        transcript = client.audio.transcriptions.create(
            model="whisper-1", file=audio_file, language="pt"
        )
        return transcript.text
    except Exception as e:
        logger.error(f"Erro na transcrição de áudio: {e}")
        return f"[Erro ao transcrever áudio: {e}]"


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

        max_retries = 2
        original_query = query

        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    f"📚 RAG Enterprise (v2-FIX): {store_id} | Query: {query} | Attempt: {attempt + 1}"
                )

                # Padrão Enterprise: Queries usando a tool File Search no generate_content
                # Adiciona instrução FORTE de idioma para garantir resposta em português
                prompt_with_lang = (
                    f"IMPORTANTE: Responda APENAS em português brasileiro (pt-BR). "
                    f"NÃO responda em espanhol ou inglês. "
                    f"NÃO peça mais informações, busque diretamente nos documentos. "
                    f"Busque nos documentos e responda em português: {query}"
                )

                response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt_with_lang,
                    config={
                        "tools": [
                            {"file_search": {"file_search_store_names": [store_id]}}
                        ]
                    },
                )

                # Retorna o texto gerado (que é a resposta baseada nos docs)
                if response.text:
                    # Limita resposta a 2000 chars para evitar overflow no OpenAI
                    result = response.text[:2000]

                    # DETECÇÃO DE CLARIFICAÇÃO: Se Gemini pediu mais detalhes ao invés de buscar
                    clarification_indicators = [
                        "podría",
                        "podrías",
                        "¿",
                        "refiere",
                        "especificar",
                        "poderia",
                        "você quis dizer",
                        "qual tipo",
                        "que tipo",
                        "mais detalhes",
                        "esclarecer",
                        "could you",
                    ]
                    is_clarification = "?" in result[:200] and any(
                        indicator in result.lower()[:300]
                        for indicator in clarification_indicators
                    )

                    if is_clarification and attempt < max_retries:
                        logger.warning(
                            f"⚠️ RAG pediu clarificação, retry {attempt + 1}/{max_retries}"
                        )
                        # Retry com query mais direta
                        query = f"Liste TODAS as informações disponíveis sobre: {original_query}"
                        continue

                    # Sucesso - cachear e retornar
                    _rag_cache[cache_key] = result

                    # DEBUG: Log o que o Gemini retornou
                    logger.info(
                        f"📚 RAG Response (primeiros 300 chars): {result[:300]}..."
                    )

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

                logger.warning(f"⚠️ RAG retornou resposta vazia para query: {query}")
                return "Sem informações relevantes encontradas nos documentos."

            except Exception as e:
                logger.error(f"Erro RAG Enterprise: {e}", exc_info=True)
                if attempt < max_retries:
                    continue
                return f"Erro ao consultar Base de Conhecimento: {str(e)}"

        return "Sem informações relevantes encontradas nos documentos."

    return StructuredTool.from_function(
        func=search_func,
        name="consultar_documentos_empresa",
        description="Use esta ferramenta APENAS para dúvidas sobre planos, regras e manuais. PROIBIDO usar para verificar cobertura ou viabilidade técnica de CEP. Para CEP, use sempre 'consultar_viabilidade'.",
    )


# --- FACTORY ---


def create_saas_agent(system_prompt: str, tools_list: list):
    """
    Cria um Agente OpenAI usando create_agent e PostgresSaver.
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5, api_key=OPENAI_API_KEY)

    # 🛑 INJECTION: FORÇA EXECUÇÃO SEQUENCIAL (Prevents "Crazy Mode")
    if system_prompt:
        system_prompt += (
            "\n\n🚨 **SYSTEM RULE: SEQUENTIAL EXECUTION ONLY** 🚨\n"
            "You are FORBIDDEN from calling multiple tools at once.\n"
            "1. Call ONE tool.\n"
            "2. Wait for the result.\n"
            "3. Then proceed.\n"
            "4. 🛑 STOP LOOPING: If you already called a tool and got a result, DO NOT call it again. Use the information you have.\n"
            "NEVER parallelize. ONE BY ONE."
        )

    final_tools = list(tools_list) if tools_list else []

    # --- CONTEXT TRIMMING (LangChain 1.0 Strict) ---

    # Middleware para Trimming (Max 20 mensagens)
    # Middleware para Trimming (Max 20 mensagens)
    @before_model
    def trim_middleware(state, runtime) -> dict | None:
        messages = state["messages"]

        # --- LOG DEBUG DE ESTADO ---
        try:
            msg_summary = [
                f"{m.type}:{len(m.content) if m.content else 0}" for m in messages[-5:]
            ]
            logger.info(
                f"🧠 [State Debug] Msgs: {len(messages)} | Last 5: {msg_summary}"
            )

            # Log se houver ToolMessage recente (Output da ferramenta)
            last_msg = messages[-1]
            if last_msg.type == "tool":
                logger.info(
                    f"🔧 [State Debug] Última msg foi TOOL OUTPUT: {last_msg.content[:100]}..."
                )
            elif last_msg.type == "ai" and last_msg.tool_calls:
                tool_names = [tc["name"] for tc in last_msg.tool_calls]
                logger.info(
                    f"🤖 [State Debug] Última msg foi AI DECISION: {tool_names}"
                )
        except Exception:
            pass
        # ---------------------------

        # Mantém System + Últimas 50 (aprox. 20k tokens)
        if len(messages) <= 50:
            return None

        # Limpa tudo e reinserir as ultimas 50
        logger.info(f"✂️ Trimming ativado! Reduzindo de {len(messages)} para 50.")
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages[-50:]]}

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
    image_base64: str = None,
    audio_bytes: bytes = None,
):
    global _conn, _checkpointer  # Para poder resetar a conexão

    # 1. Processa Áudio (Se houver)
    if audio_bytes:
        transcription = await asyncio.to_thread(transcribe_audio, audio_bytes)
        # Se query veio vazia (só audio), usa a transcrição
        if not query:
            query = transcription
        else:
            query = f"{query}\n[Transcrição de Áudio]: {transcription}"

    # 2. Constrói Mensagem do Usuário (Multimodal se houver imagem)
    from langchain_core.messages import HumanMessage

    if image_base64:
        # GPT-4o aceita lista de conteudos
        user_content = [
            {"type": "text", "text": query},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
            },
        ]
        user_message = HumanMessage(content=user_content)
    else:
        # Texto simples
        user_message = ("user", query)

    tools = tools_list or []
    # Reseta acumulador de Gemini usage
    global _gemini_usage_accumulator
    _gemini_usage_accumulator = {"input_tokens": 0, "output_tokens": 0}

    # Retry loop para lidar com conexões stale
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # 1. Cria o Agente (Tools já injetadas dinamicamente via tools_library)
            agent_runnable = create_saas_agent(system_prompt, tools)

            # 2. Config de Execução (thread_id inclui client_id para isolar contextos)
            client_id = str(client_config.get("id", "unknown"))
            thread_id = (
                f"{client_id}:{chat_id}"  # Cada cliente SaaS tem histórico separado
            )
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 25}

            # 3. Executa com Proteção
            try:
                result = await asyncio.to_thread(
                    agent_runnable.invoke,
                    {"messages": [user_message]},
                    config=config,
                )
            except BadRequestError as e:
                # AUTO-HEALING: Detecta erro de tool_calls pendentes e limpa
                error_str = str(e)
                if "tool_calls" in error_str or "400" in error_str:
                    logger.warning(
                        f"🚨 Histórico corrompido detectado para {thread_id}. Iniciando Auto-Limpeza..."
                    )
                    await asyncio.to_thread(
                        clear_chat_history, thread_id
                    )  # Usa thread_id composto
                    return (
                        "⚠️ [Auto-Correção] Detectei um erro na minha memória recente. Reiniciei nosso contexto. Por favor, faça sua pergunta novamente.",
                        {"openai": None, "gemini": None},
                        [],
                    )
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
                return messages[-1].content, usage_data, messages
            else:
                return "Erro: Nenhuma resposta gerada.", usage_data, []

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
                    "Desculpe, tive um problema de conexão. Por favor, tente novamente.",
                    {"openai": None, "gemini": None},
                    [],
                )

        except Exception as e:
            logger.error(f"Erro no Agent SaaS: {e}", exc_info=True)
            # NUNCA expor erro técnico ao cliente! Mensagem genérica amigável
            return (
                "Desculpe, estou com dificuldades técnicas no momento. Por favor, tente novamente em alguns instantes. 🙏",
                {
                    "openai": None,
                    "gemini": None,
                },
                [],
            )
