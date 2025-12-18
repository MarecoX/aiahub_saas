import os
import psycopg
from psycopg.rows import dict_row
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Configura Carga de Env (Garante que scripts achem o .env na raiz Kestra_2.0 ou acima)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Tenta carregar do pai (Kestra_2.0) e do avô (IA)
load_dotenv(os.path.join(current_dir, '..', '.env'))     # Kestra_2.0/.env
load_dotenv(os.path.join(current_dir, '..', '..', '.env')) # IA/.env

# Configuração de Conexão (Priorização: Env > Streamlit Secrets)
DB_URL = os.getenv("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")

# Fallback para Streamlit Cloud Secrets (se não encontrou em env vars)
if not DB_URL:
    try:
        import streamlit as st
        DB_URL = st.secrets.get("DATABASE_CONNECTION_URI") or st.secrets.get("DATABASE_URL")
    except Exception:
        pass  # Não está rodando no Streamlit ou sem secrets

def get_connection():
    """Retorna uma conexão Psycopg 3 configurada (dict_row, autocommit)."""
    if not DB_URL:
        raise ValueError("DATABASE_CONNECTION_URI não configurada! Configure no .env ou Streamlit Secrets.")
    return psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True)

def get_client_config(token: str):
    """
    Busca as configurações do cliente baseada no Token (Webhook/InstanceID).
    Retorna um dicionário com: id, system_prompt, gemini_store_id, tool_config, etc.
    """
    if not DB_URL:
        logger.error("❌ ERRO CRÍTICO: DATABASE_CONNECTION_URI não definida!")
        return None

    try:
        # Usando Context Manager do Psycopg 3 (Fecha sozinho)
        with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
            # logger.info(f"🔌 Conectado ao BD: {conn.info.dbname} @ {conn.info.host}")
            
            with conn.cursor() as cur:
                sql = """
                    SELECT id, name, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url 
                    FROM clients 
                    WHERE token = %s
                """
                cur.execute(sql, (token,))
                result = cur.fetchone()
                
                if result:
                    logger.info(f"✅ Cliente identificado: {result['name']} (ID: {result['id']})")
                    return result # Já é dict devido ao row_factory
                else:
                    logger.warning(f"⚠️ Nenhum cliente encontrado para o token: {token}")
                    return None

    except Exception as e:
        logger.error(f"❌ Erro de Banco de Dados: {e}")
        return None

def clear_chat_history(thread_id: str):
    """
    Limpa o histórico persistido (checkpoints) de um chat específico.
    Isso corrige o erro de estado inconsistente (400 Bad Request) do OpenAI.
    """
    logger.info(f"🧹 Tentando limpar histórico do chat: {thread_id}")
    queries = [
        "DELETE FROM checkpoints WHERE thread_id = %s",
        "DELETE FROM checkpoint_writes WHERE thread_id = %s"
    ]
    
    try:
        # Autocommit=True dispensa conn.commit()
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                for q in queries:
                    cur.execute(q, (thread_id,))
            
        logger.info(f"✨ Histórico limpo com sucesso para: {thread_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erro ao limpar histórico: {e}")
        return False
