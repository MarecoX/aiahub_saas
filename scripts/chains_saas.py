from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.checkpoint.postgres import PostgresSaver
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
    except:
        pass

DATABASE_URL = os.environ.get("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")

# --- DATABASE / CHECKPOINTER SETUP ---
try:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL não encontrada. Checkpointer pode falhar.")
        conn = None
        checkpointer = None
    else:
        conn = psycopg.connect(DATABASE_URL, autocommit=True)
        checkpointer = PostgresSaver(conn=conn)
        checkpointer.setup()
        logger.info("✅ PostgresSaver Checkpointer configurado com sucesso.")
except Exception as e:
    logger.error(f"❌ Falha ao configurar Checkpointer: {e}")
    checkpointer = None


# --- TOOLS ---

from google import genai
from google.genai import types
# from langchain.tools import StructuredTool # Deprecated/Moved
from langchain_core.tools import StructuredTool

# Configura Gemini Client
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    try:
        import streamlit as st
        GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
    except:
        pass
gemini_client = None
if GEMINI_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_KEY)
    except Exception as e:
        logger.error(f"Erro init Gemini Client: {e}")

# --- DYNAMIC TOOL FACTORY ---

def create_knowledge_base_tool(store_id: str):
    """
    Cria uma ferramenta de busca dinâmica ligada a um Vector Store (Enterprise) específico.
    """
    def search_func(query: str):
        if not gemini_client:
            return "Erro: Client Gemini não configurado."
            
        try:
            logger.info(f"📚 RAG Enterprise: {store_id} | Query: {query}")
            
            # Padrão Enterprise: Queries usando a tool File Search no generate_content
            response = gemini_client.models.generate_content(
                model='gemini-3-flash-preview', # ou gemini-2.0-flash-exp se disponível
                contents=query,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[store_id]
                        )
                    )]
                )
            )
            
            # Retorna o texto gerado (que é a resposta baseada nos docs)
            # O citacoes (grounding_metadata) estão em response.candidates[0].grounding_metadata
            return response.text
            
        except Exception as e:
            logger.error(f"Erro RAG Enterprise: {e}")
            return f"Erro ao consultar Base de Conhecimento: {str(e)}"

    return StructuredTool.from_function(
        func=search_func,
        name="consultar_documentos_empresa",
        description="Use esta ferramenta para buscar informações nos manuais, PDFs e arquivos da empresa. O Gemini pesquisará internamente e retornará a resposta baseada nos documentos."
    )

# --- FACTORY ---

def create_saas_agent(system_prompt: str, tools_list: list, store_id: str = None):
    """
    Cria um Agente OpenAI usando create_agent e PostgresSaver.
    Injeta dinamicamente o tool de Knowledge Base se store_id for válido.
    """
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.3,
        api_key=OPENAI_API_KEY
    )
    
    final_tools = list(tools_list) if tools_list else []
    
    # Injeta Knowledge Base do Cliente (Enterprise usa nomes resource, ex: projects/... ou stores/...)
    # Nosso store_id local pode ser o 'name' completo ou apenas o ID. 
    # O Gemini Manager v2 tenta usar o name completo. 
    # Assume-se que store_id venha correto do DB (atualizado pelo Manager).
    
    if store_id:
        kb_tool = create_knowledge_base_tool(store_id)
        final_tools.append(kb_tool)
        logger.info(f"📎 Tool Enterprise Docs injetada: {store_id}")
    
    return create_agent(
        model=llm,
        tools=final_tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer
    )

# --- INTERFACE ---

async def ask_saas(query: str, chat_id: str, system_prompt: str, client_config: dict, tools_list: list = None):
    try:
        tools = tools_list or []
        
        # Extrai Store ID
        store_id = client_config.get('gemini_store_id')
        
        # 1. Cria o Agente (Passando Store ID)
        agent_runnable = create_saas_agent(system_prompt, tools, store_id=store_id)
        
        # 2. Config de Execução
        config = {
            "configurable": {
                "thread_id": chat_id
            }
        }
        
        # 3. Executa com Proteção
        try:
            result = await asyncio.to_thread(
                agent_runnable.invoke,
                {"messages": [("user", query)]},
                config=config
            )
# ... (restante do código igual)
        except BadRequestError as e:
            # AUTO-HEALING: Detecta erro de tool_calls pendentes e limpa
            error_str = str(e)
            if "tool_calls" in error_str or "400" in error_str:
                logger.warning(f"🚨 Histórico corrompido detectado para {chat_id}. Iniciando Auto-Limpeza...")
                
                # Executa limpeza (sync) em thread
                await asyncio.to_thread(clear_chat_history, chat_id)
                
                return "⚠️ [Auto-Correção] Detectei um erro na minha memória recente (ferramenta travada). Reiniciei nosso contexto para corrigir. Por favor, faça sua pergunta novamente."
            
            # Se for outro BadRequest, relança
            raise e
        
        # 4. Processa Resposta
        messages = result.get("messages", [])
        if messages:
            return messages[-1].content
        else:
            return "Erro: Nenhuma resposta gerada."
            
    except Exception as e:
        logger.error(f"Erro no Agent SaaS: {e}", exc_info=True)
        return "Desculpe, tive um erro interno ao processar sua solicitação inteligente."

