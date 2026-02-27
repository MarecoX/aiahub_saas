import json
import os
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
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

# Pool Size configurável via ENV (default: 5 para evitar esgotar servidor)
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "5"))

# Fallback para Streamlit Cloud Secrets (se não encontrou em env vars)
if not DB_URL:
    try:
        import streamlit as st

        DB_URL = st.secrets.get("DATABASE_CONNECTION_URI") or st.secrets.get(
            "DATABASE_URL"
        )
    except Exception:
        pass  # Não está rodando no Streamlit ou sem secrets

# LOG DB_URL (MASKED) FOR DEBUGGING
if DB_URL:
    safe_url = DB_URL
    if "@" in safe_url:
        # Mask password: postgres://user:pass@host -> postgres://user:***@host
        try:
            prefix, rest = safe_url.split("@", 1)
            scheme_user_pass, _ = prefix.rsplit(":", 1)
            safe_url = f"{scheme_user_pass}:***@{rest}"
        except Exception:
            safe_url = "ErrorMaskingURL"
    logger.info(f"🔌 DATABASE_URL Carregada: {safe_url}")
else:
    logger.error("❌ DATABASE_CONNECTION_URI ESTÁ VAZIA!")


# Global Pool variable
_pool = None
_error_table_initialized = False
_chat_table_initialized = False


def get_connection():
    """Retorna uma conexão do Pool (Context Manager Safe)."""
    global _pool
    if not DB_URL:
        raise ValueError("DATABASE_CONNECTION_URI não configurada!")

    # Initialize Pool if not exists
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DB_URL,
            min_size=1,
            max_size=DB_POOL_MAX_SIZE,  # Configurável via DB_POOL_MAX_SIZE env var
            timeout=30.0,  # Timeout de 30s antes de desistir
            kwargs={"row_factory": dict_row, "autocommit": True},
            check=ConnectionPool.check_connection,  # Garante que a conexão está viva
        )
        logger.info(
            f"🔌 Pool de conexões PostgreSQL inicializado (max={DB_POOL_MAX_SIZE})"
        )

    return _pool.connection()


def get_client_config(token: str):
    """
    Busca as configurações do cliente baseada no Token (Webhook/InstanceID).
    Retorna um dicionário com: id, system_prompt, gemini_store_id, tool_config, etc.
    """
    if not DB_URL:
        logger.error("❌ ERRO CRÍTICO: DATABASE_CONNECTION_URI não definida!")
        return None

    try:
        # Usando Pool Connection
        with get_connection() as conn:
            # logger.info(f"🔌 Conectado ao BD: {conn.info.dbname} @ {conn.info.host}")

            with conn.cursor() as cur:
                sql = """
                    SELECT id, name, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url, token,
                           lancepilot_token, lancepilot_workspace_id, lancepilot_number, lancepilot_active, followup_config, whatsapp_provider,
                           COALESCE(business_type, 'generic') as business_type
                    FROM clients 
                    WHERE token = %s
                """
                cur.execute(sql, (token,))
                result = cur.fetchone()

                if result:
                    logger.info(
                        f"✅ Cliente identificado: {result['name']} (ID: {result['id']})"
                    )
                    return result

                # --- FALLBACK MIGRATION (Search by Provider Token or Uazapi Key) ---
                # Se não achou pelo token direto da tabela clients, tenta achar quem usa esse token como CREDENCIAL (Provider)
                sql_provider = """
                    SELECT c.id, c.name, c.system_prompt, c.gemini_store_id, c.tools_config, c.human_attendant_timeout, 
                           c.api_url, c.token, c.lancepilot_token, c.lancepilot_workspace_id, c.lancepilot_number, 
                           c.lancepilot_active, c.followup_config, c.whatsapp_provider,
                           COALESCE(c.business_type, 'generic') as business_type
                    FROM clients c
                    LEFT JOIN client_providers cp ON c.id = cp.client_id
                    WHERE cp.config->>'token' = %s 
                       OR c.tools_config->'whatsapp'->>'key' = %s
                       OR c.tools_config->'whatsapp_official'->>'token' = %s
                    LIMIT 1
                """
                cur.execute(sql_provider, (token, token, token))
                result_provider = cur.fetchone()

                if result_provider:
                    logger.info(
                        f"🔄 Migração: Cliente identificado via Token do Provider/Uazapi: {result_provider['name']}"
                    )
                    return result_provider

                logger.warning(f"⚠️ Nenhum cliente encontrado para o token: {token}")
                return None

    except Exception as e:
        logger.error(f"❌ Erro de Banco de Dados: {e}")
        return None


def get_client_config_by_id(client_id: str):
    """
    Busca as configurações do cliente baseada no ID (UUID).
    Retorna um dicionário com: id, system_prompt, gemini_store_id, tool_config, etc.
    """
    if not DB_URL:
        logger.error("❌ ERRO CRÍTICO: DATABASE_CONNECTION_URI não definida!")
        return None

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT id, name, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url, token,
                           lancepilot_token, lancepilot_workspace_id, lancepilot_number, lancepilot_active, followup_config, whatsapp_provider,
                           COALESCE(business_type, 'generic') as business_type
                    FROM clients 
                    WHERE id = %s
                """
                cur.execute(sql, (client_id,))
                result = cur.fetchone()

                if result:
                    logger.info(
                        f"✅ Cliente identificado por ID: {result['name']} (ID: {result['id']})"
                    )
                    return result
                else:
                    logger.warning(
                        f"⚠️ Nenhum cliente encontrado para o ID: {client_id}"
                    )
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
        # Pool handles connection
        with get_connection() as conn:
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
    ATUALIZADO: Usa pool de conexões ao invés de conexão direta.
    """
    if not DB_URL or not phone_number:
        return None

    try:
        # Usa pool ao invés de conexão direta
        with get_connection() as conn:
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
    Busca o Token do Cliente pelo phone_id da Meta via client_providers.
    """
    if not DB_URL or not phone_id:
        return None

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.token
                    FROM client_providers cp
                    JOIN clients c ON c.id = cp.client_id
                    WHERE cp.provider_type = 'meta'
                      AND cp.is_active = true
                      AND cp.config->>'phone_id' = %s
                    LIMIT 1
                    """,
                    (phone_id,),
                )
                result = cur.fetchone()
                if result:
                    return result["token"]
                return None
    except Exception as e:
        logger.error(f"Erro ao buscar cliente via WABA PhoneID: {e}")
        return None


# ============================================================================
# PROVIDER FUNCTIONS (client_providers table)
# ============================================================================


def get_provider_config(client_id: str, provider_type: str) -> dict:
    """
    Busca configuração de um provider específico para um cliente.

    Args:
        client_id: UUID do cliente
        provider_type: 'uazapi', 'lancepilot', ou 'meta'

    Returns:
        dict com config do provider ou {} se não encontrado

    Example:
        config = get_provider_config("abc-123", "uazapi")
        url = config.get("url")
        token = config.get("token")
    """
    if not client_id or not provider_type:
        return {}

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT config 
                    FROM client_providers 
                    WHERE client_id = %s 
                      AND provider_type = %s 
                      AND is_active = true
                    ORDER BY is_default DESC
                    LIMIT 1
                """,
                    (client_id, provider_type),
                )
                result = cur.fetchone()
                if result:
                    return result["config"] or {}
                return {}
    except Exception as e:
        logger.error(f"❌ Erro ao buscar provider config: {e}")
        return {}


def get_default_provider(client_id: str) -> tuple:
    """
    Retorna o provider padrão do cliente.

    Returns:
        tuple: (provider_type, config) ou (None, {}) se não encontrado
    """
    if not client_id:
        return (None, {})

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider_type, config 
                    FROM client_providers 
                    WHERE client_id = %s 
                      AND is_default = true 
                      AND is_active = true
                    LIMIT 1
                """,
                    (client_id,),
                )
                result = cur.fetchone()
                if result:
                    return (result["provider_type"], result["config"] or {})
                return (None, {})
    except Exception as e:
        logger.error(f"❌ Erro ao buscar default provider: {e}")
        return (None, {})


def list_client_providers(client_id: str) -> list:
    """
    Lista todos os providers configurados para um cliente.

    Returns:
        list de dicts com id, provider_type, instance_name, config, is_active, is_default
    """
    if not client_id:
        return []

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, provider_type, instance_name, config, is_active, is_default
                    FROM client_providers 
                    WHERE client_id = %s
                    ORDER BY is_default DESC, provider_type, instance_name
                """,
                    (client_id,),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao listar providers: {e}")
        return []


def upsert_provider_config(
    client_id: str,
    provider_type: str,
    config: dict,
    instance_name: str = "Principal",
    is_active: bool = True,
    is_default: bool = False,
) -> str:
    """
    Insere ou atualiza configuração de um provider.

    Returns:
        UUID do registro criado/atualizado ou None em caso de erro
    """
    if not client_id or not provider_type:
        return None

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Se is_default=True, desmarcar outros defaults do mesmo tipo
                if is_default:
                    cur.execute(
                        """
                        UPDATE client_providers 
                        SET is_default = false 
                        WHERE client_id = %s AND provider_type = %s
                    """,
                        (client_id, provider_type),
                    )

                cur.execute(
                    """
                    INSERT INTO client_providers 
                        (client_id, provider_type, instance_name, config, is_active, is_default)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (client_id, provider_type, instance_name) 
                    DO UPDATE SET 
                        config = EXCLUDED.config,
                        is_active = EXCLUDED.is_active,
                        is_default = EXCLUDED.is_default,
                        updated_at = NOW()
                    RETURNING id
                """,
                    (
                        client_id,
                        provider_type,
                        instance_name,
                        json.dumps(config),
                        is_active,
                        is_default,
                    ),
                )
                result = cur.fetchone()
                logger.info(
                    f"✅ Provider {provider_type} salvo para cliente {client_id}"
                )
                return str(result["id"]) if result else None
    except Exception as e:
        logger.error(f"❌ Erro ao salvar provider: {e}")
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
    whatsapp_provider="none",
    business_type="generic",
):
    """
    Cria um novo cliente no banco de dados.
    """
    try:
        default_tools = json.dumps({"consultar_cep": True})

        with get_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url, username, password_hash, whatsapp_provider, business_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        whatsapp_provider,
                        business_type,
                    ),
                )
                new_id = cur.fetchone()["id"]
                logger.info(f"✅ Cliente criado via DB: {name} (ID: {new_id})")
                return new_id
    except Exception as e:
        logger.error(f"❌ Erro ao criar cliente: {e}")
        return None


def delete_client_db(client_id):
    """
    Remove um cliente e seus dados do banco.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Remove mensagens (Opcional, com cascade isso seria automatico mas por segurança...)
                cur.execute(
                    "DELETE FROM chat_messages WHERE client_id = %s", (client_id,)
                )

                # 2. Remove conversas ativas
                # (Se existir tabela active_conversations, se não ignorar ou usar try catch especifico)
                # cur.execute("DELETE FROM active_conversations WHERE client_id = %s", (client_id,))

                # 3. Remove cliente
                cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))

                logger.info(f"🗑️ Cliente {client_id} deletado com sucesso.")
                return True
    except Exception as e:
        logger.error(f"❌ Erro ao deletar cliente {client_id}: {e}")
        return False


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
        "ai_active",
        "business_type",
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


def is_within_business_hours(tools_config: dict) -> tuple:
    """
    Verifica se a IA deve responder agora com base no horário de atendimento.
    Retorna (should_respond: bool, off_message: str).
    Se business_hours não estiver ativo, retorna (True, "").

    Suporta dois modos (campo 'mode'):
      - "dentro" (padrão): IA responde DENTRO do horário configurado.
      - "fora": IA responde FORA do horário configurado
        (útil quando equipe humana atende no horário comercial).
    """
    bh = (tools_config or {}).get("business_hours", {})
    if not bh.get("active"):
        return True, ""

    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    day_keys = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
    schedule = bh.get("schedule", {})
    today = schedule.get(day_keys[now.weekday()], {})
    mode = bh.get("mode", "dentro")

    # Verifica se o momento atual cai dentro da janela configurada
    in_window = False
    if today.get("on"):
        start = today.get("start", "00:00")
        end = today.get("end", "23:59")
        current = now.strftime("%H:%M")
        in_window = start <= current <= end

    if mode == "fora":
        # Modo invertido: IA responde quando NÃO está na janela configurada
        if in_window:
            return False, bh.get("off_message", "")
        return True, ""
    else:
        # Modo padrão: IA responde quando ESTÁ na janela configurada
        if in_window:
            return True, ""
        return False, bh.get("off_message", "")


def is_within_followup_hours(followup_config: dict) -> bool:
    """
    Verifica se o momento atual está dentro da faixa de horário permitida para follow-up.
    Se allowed_hours não estiver ativo, retorna True (sem restrição).

    Args:
        followup_config: Dict com a configuração do follow-up do cliente.

    Returns:
        True se pode disparar follow-up agora, False caso contrário.
    """
    allowed_hours = (followup_config or {}).get("allowed_hours", {})
    if not allowed_hours.get("enabled"):
        return True

    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    current = now.strftime("%H:%M")
    start = allowed_hours.get("start", "00:00")
    end = allowed_hours.get("end", "23:59")

    return start <= current <= end


def get_all_clients_db():
    """
    Lista todos os clientes (para Admin/API).
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, token, username, api_url, human_attendant_timeout, tools_config, whatsapp_provider FROM clients ORDER BY created_at DESC"
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao listar clientes: {e}")
        return []


# --- INBOX FUNCTIONS (Chat History) ---


def ensure_chat_messages_table():
    """
    Cria a tabela de mensagens se não existir.
    LAZY INIT: Só executa uma vez quando realmente precisar.
    """
    global _chat_table_initialized
    if _chat_table_initialized:
        return  # Já inicializado, não precisa fazer nada

    sql = """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id SERIAL PRIMARY KEY,
        client_id UUID REFERENCES clients(id),
        chat_id TEXT NOT NULL,
        role TEXT NOT NULL, -- 'user' or 'assistant' or 'system'
        content TEXT,
        media_url TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id);
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
        _chat_table_initialized = True
        logger.info("✅ Tabela chat_messages verificada/criada.")
    except Exception as e:
        logger.error(f"❌ Erro ao criar tabela chat_messages: {e}")


# REMOVIDO: Chamada automática no import causava esgotamento de conexões
# A tabela será criada na primeira chamada a add_message() se necessário


def add_message(
    client_id, chat_id: str, role: str, content: str, media_url: str = None
):
    """
    Salva uma mensagem no histórico.
    """
    # Garante que a tabela existe (lazy init)
    ensure_chat_messages_table()

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (client_id, chat_id, role, content, media_url)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (client_id, chat_id, role, content, media_url),
                )
    except Exception as e:
        logger.error(f"❌ Erro ao salvar mensagem no Inbox: {e}")


def get_messages(client_id, chat_id: str, limit: int = 50):
    """
    Recupera o histórico da conversa ordenado.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, role, content, media_url, created_at 
                    FROM chat_messages 
                    WHERE client_id = %s AND chat_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (client_id, chat_id, limit),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao buscar mensagens: {e}")
        return []


def get_recent_messages(client_id, chat_id: str, limit: int = 10):
    """
    Alias para get_messages para compatibilidade com workers.
    """
    return get_messages(client_id, chat_id, limit)


def get_conversation_state(client_id, chat_id: str) -> dict:
    """
    Detecta se já existe conversa anterior com este chat_id.
    Retorna dict com informações para injeção de contexto.

    Returns:
        {
            "is_returning": bool,        # True se já houve troca de mensagens
            "message_count": int,         # Total de mensagens no histórico
            "last_assistant_msg": str,    # Última mensagem da IA (resumo)
            "last_user_msg": str,         # Última mensagem do usuário
        }
    """
    state = {
        "is_returning": False,
        "message_count": 0,
        "last_assistant_msg": "",
        "last_user_msg": "",
    }
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Conta total de mensagens
                cur.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE client_id = %s AND chat_id = %s",
                    (client_id, chat_id),
                )
                row = cur.fetchone()
                count = row[0] if row else 0
                state["message_count"] = count
                state["is_returning"] = count > 0

                if count > 0:
                    # Busca últimas mensagens (user + assistant) para contexto
                    cur.execute(
                        """
                        SELECT role, content FROM chat_messages
                        WHERE client_id = %s AND chat_id = %s
                        ORDER BY created_at DESC
                        LIMIT 6
                        """,
                        (client_id, chat_id),
                    )
                    recent = cur.fetchall()
                    for role, content in recent:
                        if role == "assistant" and not state["last_assistant_msg"]:
                            state["last_assistant_msg"] = (content or "")[:300]
                        elif role == "user" and not state["last_user_msg"]:
                            state["last_user_msg"] = (content or "")[:300]
    except Exception as e:
        logger.error(f"❌ Erro ao detectar estado da conversa: {e}")

    return state


def get_inbox_conversations(client_id):
    """
    Retorna lista de conversas ativas (Baseada na tabela active_conversations).
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chat_id, last_message_at, last_role, status 
                    FROM active_conversations 
                    WHERE client_id = %s
                    ORDER BY last_message_at DESC
                    LIMIT 20
                    """,
                    (client_id,),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao listar conversas do Inbox: {e}")
        return []


# --- ERROR LOGGING SYSTEM ---
def init_error_log_table():
    """Cria a tabela de logs de erro se não existir."""
    if not DB_URL:
        return

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS error_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        source VARCHAR(100),
                        error_type VARCHAR(100),
                        message TEXT,
                        traceback TEXT,
                        client_id INTEGER,
                        chat_id VARCHAR(100),
                        memory_usage VARCHAR(50),
                        context_data JSONB
                    );
                    """
                )
    except Exception as e:
        logger.error(f"❌ Falha ao criar tabela error_logs: {e}")


def log_error(
    source: str,
    exception: Exception,
    context: dict = None,
    client_id: int = None,
    chat_id: str = None,
):
    """
    Registra um erro no banco de dados para debug posterior.
    """
    import traceback

    # Tenta pegar uso de memória
    mem_usage = "N/A"
    try:
        import psutil

        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        mem_usage = f"{mem_info.rss / 1024 / 1024:.2f} MB"
    except ImportError:
        mem_usage = "psutil_missing"
    except Exception:
        mem_usage = "error_reading_mem"

    # Prepara dados
    error_type = type(exception).__name__
    error_msg = str(exception)
    tb_str = "".join(
        traceback.format_exception(None, exception, exception.__traceback__)
    )

    # Garante que context seja JSON safe
    context_json = "{}"
    if context:
        try:
            # Remove objetos não serializáveis (básico)
            safe_context = {k: str(v) for k, v in context.items()}
            context_json = json.dumps(safe_context)
        except Exception:
            context_json = '{"error": "context_serialization_failed"}'

    try:
        if not DB_URL:
            logger.error("DB_URL not set, cannot log error to DB")
            logger.error(f"Origem: {source} | Erro: {error_msg}")
            return

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO error_logs (source, error_type, message, traceback, client_id, chat_id, memory_usage, context_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        source,
                        error_type,
                        error_msg,
                        tb_str,
                        client_id,
                        chat_id,
                        mem_usage,
                        context_json,
                    ),
                )
        logger.info(f"🐞 Erro registrado no DB: {error_type} em {source}")
    except Exception as db_e:
        logger.error(f"❌ Falha crítica ao salvar log de erro: {db_e}")
        logger.error(f"Erro Original: {error_msg}")


# ============================================================================
# METRICS / EVENT LOGGING (ADR-003)
# ============================================================================


def log_event(client_id: str, chat_id: str, event_type: str, event_data: dict = None):
    """
    Registra um evento de conversa no event log (append-only).
    Custo: ~0ms extra (1 INSERT simples).

    Args:
        client_id: UUID do cliente
        chat_id: ID da conversa
        event_type: Tipo do evento (msg_received, ai_responded, human_takeover, etc.)
        event_data: Dados extras do evento (opcional)
    """
    if not DB_URL or not client_id or not chat_id:
        return

    try:
        data_json = json.dumps(event_data or {})
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_events (client_id, chat_id, event_type, event_data)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (client_id, chat_id, event_type, data_json),
                )
    except Exception as e:
        # Nunca deixa falha de métricas afetar o fluxo principal
        logger.warning(f"⚠️ Falha ao registrar evento {event_type}: {e}")


def get_metrics_daily(client_id: str, start_date=None, end_date=None) -> list:
    """
    Lê métricas pré-agregadas para o dashboard.
    Query instantânea (<50ms) independente do volume de dados.

    Args:
        client_id: UUID do cliente
        start_date: Data inicial (default: 30 dias atrás)
        end_date: Data final (default: hoje)

    Returns:
        Lista de dicts com métricas diárias
    """
    if not DB_URL or not client_id:
        return []

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if start_date and end_date:
                    cur.execute(
                        """
                        SELECT * FROM metrics_daily
                        WHERE client_id = %s AND date BETWEEN %s AND %s
                        ORDER BY date DESC
                        """,
                        (client_id, start_date, end_date),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM metrics_daily
                        WHERE client_id = %s AND date >= CURRENT_DATE - INTERVAL '30 days'
                        ORDER BY date DESC
                        """,
                        (client_id,),
                    )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Erro ao buscar métricas: {e}")
        return []


def get_metrics_summary(client_id: str) -> dict:
    """
    Retorna resumo geral das métricas (últimos 30 dias).
    Para exibir nos cards do dashboard.
    """
    if not DB_URL or not client_id:
        return {}

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(total_conversations), 0) as total_conversations,
                        COALESCE(SUM(total_messages_in), 0) as total_messages_in,
                        COALESCE(SUM(total_messages_out), 0) as total_messages_out,
                        COALESCE(SUM(resolved_by_ai), 0) as resolved_by_ai,
                        COALESCE(SUM(resolved_by_human), 0) as resolved_by_human,
                        COALESCE(SUM(human_takeovers), 0) as human_takeovers,
                        COALESCE(AVG(avg_response_time_ms), 0)::int as avg_response_time_ms,
                        COALESCE(SUM(followups_sent), 0) as followups_sent,
                        COALESCE(SUM(followups_converted), 0) as followups_converted,
                        COALESCE(SUM(total_cost_usd), 0) as total_cost_usd
                    FROM metrics_daily
                    WHERE client_id = %s AND date >= CURRENT_DATE - INTERVAL '30 days'
                    """,
                    (client_id,),
                )
                result = cur.fetchone()
                return dict(result) if result else {}
    except Exception as e:
        logger.error(f"❌ Erro ao buscar resumo de métricas: {e}")
        return {}


# Initialize error_logs table on module load
if not _error_table_initialized:
    init_error_log_table()
    _error_table_initialized = True
