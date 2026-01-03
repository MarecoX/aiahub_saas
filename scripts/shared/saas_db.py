import os
import psycopg
from psycopg.rows import dict_row
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Configura Carga de Env (Garante que scripts achem o .env na raiz Kestra_2.0 ou acima)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Tenta carregar do pai (Kestra_2.0) e do avô (IA)
load_dotenv(os.path.join(current_dir, "..", ".env"))  # Kestra_2.0/.env
load_dotenv(os.path.join(current_dir, "..", "..", ".env"))  # IA/.env

# Configuração de Conexão (Priorização: Env > Streamlit Secrets)
DB_URL = os.getenv("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")

# Fallback para Streamlit Cloud Secrets (se não encontrou em env vars)
if not DB_URL:
    try:
        import streamlit as st

        DB_URL = st.secrets.get("DATABASE_CONNECTION_URI") or st.secrets.get(
            "DATABASE_URL"
        )
    except Exception:
        pass  # Não está rodando no Streamlit ou sem secrets


def get_connection():
    """Retorna uma conexão Psycopg 3 configurada (dict_row, autocommit)."""
    if not DB_URL:
        raise ValueError(
            "DATABASE_CONNECTION_URI não configurada! Configure no .env ou Streamlit Secrets."
        )
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
                    SELECT id, name, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url, token,
                           uazapi_url, uazapi_token, uazapi_active,
                           lancepilot_token, lancepilot_workspace_id, lancepilot_number, lancepilot_active
                    FROM clients 
                    WHERE token = %s
                """
                cur.execute(sql, (token,))
                result = cur.fetchone()

                if result:
                    logger.info(
                        f"✅ Cliente identificado: {result['name']} (ID: {result['id']})"
                    )
                    return result  # Já é dict devido ao row_factory
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
        "DELETE FROM checkpoint_writes WHERE thread_id = %s",
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


def get_client_token_by_phone(phone_number: str):
    """
    Busca o Token do Cliente baseado no número de telefone conectado (LancePilot).
    Agora usa colunas dedicadas em vez de JSONB.
    """
    if not DB_URL or not phone_number:
        return None

    try:
        with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # Busca cliente usando colunas dedicadas
                sql = """
                    SELECT token 
                    FROM clients 
                    WHERE lancepilot_active = TRUE
                      AND lancepilot_number = %s
                    LIMIT 1
                """
                cur.execute(sql, (phone_number,))
                result = cur.fetchone()

                if result:
                    logger.info(f"✅ Cliente identificado: {result['token']}")
                    return result["token"]
                else:
                    # Debug: Listar todos os números salvos para ver o que tem no banco
                    cur.execute("SELECT lancepilot_number as num FROM clients")
                    all_nums = [r["num"] for r in cur.fetchall()]
                    logger.warning(
                        f"⚠️ Nenhum cliente encontrado para number='{phone_number}'. Números no banco: {all_nums}"
                    )
                    return None
    except Exception as e:
        logger.error(f"❌ Erro ao buscar usuario por telefone: {e}")
        return None


def get_client_token_by_waba_phone(phone_id: str):
    """
    Busca o Token do Cliente pesquisando dentro do JSONB tools_config
    pelo campo 'whatsapp_official' -> 'phone_id'.
    """
    if not DB_URL or not phone_id:
        return None

    try:
        with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # Busca cliente onde (tools_config -> 'whatsapp_official' ->> 'phone_id') match
                sql = """
                    SELECT token 
                    FROM clients 
                    WHERE tools_config->'whatsapp_official'->>'phone_id' = %s
                    LIMIT 1
                """
                cur.execute(sql, (phone_id,))
                result = cur.fetchone()

                if result:
                    logger.info(
                        f"✅ Cliente WABA identificado via PhoneID {phone_id}: {result['token']}"
                    )
                    return result["token"]
                else:
                    return None
    except Exception as e:
        logger.error(f"❌ Erro ao buscar cliente via WABA PhoneID: {e}")
        return None


# --- FUNÇÕES DE ESCRITA (API/ADMIN) ---


def create_client_db(
    name,
    token,
    prompt,
    username,
    password_hash,
    api_url=None,
    timeout=3600,
    store_id=None,
):
    """
    Cria um novo cliente no banco de dados.
    """
    try:
        import json

        default_tools = json.dumps({"consultar_cep": True})

        with get_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url, username, password_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """
                cur.execute(
                    sql,
                    (
                        name,
                        token,
                        prompt,
                        store_id,
                        default_tools,
                        timeout,
                        api_url,
                        username,
                        password_hash,
                    ),
                )
                new_id = cur.fetchone()["id"]
                logger.info(f"✅ Cliente criado via DB: {name} (ID: {new_id})")
                return new_id
    except Exception as e:
        logger.error(f"❌ Erro ao criar cliente: {e}")
        return None


def update_client_db(client_id, update_dict):
    """
    Atualiza campos genéricos do cliente.
    update_dict pode conter: system_prompt, human_attendant_timeout, api_url, name
    """
    valid_fields = [
        "system_prompt",
        "human_attendant_timeout",
        "api_url",
        "name",
        "gemini_store_id",
    ]
    filtered = {k: v for k, v in update_dict.items() if k in valid_fields}

    if not filtered:
        return False

    try:
        set_clause = ", ".join([f"{k} = %s" for k in filtered.keys()])
        values = list(filtered.values())
        values.append(client_id)

        sql = f"UPDATE clients SET {set_clause} WHERE id = %s"

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, values)
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar cliente {client_id}: {e}")
        return False


def update_tools_config_db(client_id, new_config_dict):
    """
    Atualiza o JSONB tools_config completo.
    """
    try:
        import json

        config_json = json.dumps(new_config_dict)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE clients SET tools_config = %s WHERE id = %s",
                    (config_json, client_id),
                )
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao salvar tools_config para {client_id}: {e}")
        return False


def get_all_clients_db():
    """
    Lista todos os clientes (para Admin/API).
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, token, username, api_url, human_attendant_timeout, tools_config FROM clients ORDER BY created_at DESC"
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao listar clientes: {e}")
        return []
