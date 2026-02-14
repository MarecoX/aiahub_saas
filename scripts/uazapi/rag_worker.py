import sys
import os
import asyncio
import json
import logging
import redis.asyncio as redis
from datetime import datetime

# import google.generativeai as genai  <-- REMOVED DEPRECATED SDK
from kestra import Kestra

# Adiciona o diretório raiz ao path para importar scripts.shared...
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
# Adiciona o diretório shared ao path (compatibilidade com imports diretos 'from saas_db')
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
)
from saas_db import get_client_config, get_connection, get_provider_config, log_event
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
        Kestra.outputs(
            {"response_text": "", "chat_id": "", "api_url": "", "api_key": ""}
        )
        return

    if not client_token:
        logger.error(
            "❌ ERRO: KESTRA_CLIENT_TOKEN não fornecido! O Worker não sabe quem é o cliente."
        )
        Kestra.outputs(
            {
                "response_text": "",
                "chat_id": chat_id or "",
                "api_url": "",
                "api_key": "",
            }
        )
        return

    # 2. Carregar "Cérebro" do Banco de Dados
    logger.info(f"🔍 Buscando configs para o token: {client_token}")
    client_config = get_client_config(client_token)

    if not client_config:
        logger.error("❌ Cliente não encontrado no Banco de Dados. Abortando.")
        Kestra.outputs(
            {
                "response_text": "",
                "chat_id": chat_id or "",
                "api_url": "",
                "api_key": "",
            }
        )
        return

    logger.info(f"🧠 Cliente Carregado: {client_config['name']}")
    system_prompt = f"Data/Hora Atual: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n{client_config['system_prompt']}"

    # --- INJEÇÃO DE INSTRUÇÕES DINÂMICAS (UI) ---
    t_cfg = client_config.get("tools_config", {})

    # -------------------------------------------------------------
    # 🔐 SECURITY CHECKS (Whitelist / Blocklist)
    # -------------------------------------------------------------
    sec_lists = t_cfg.get("security_lists", {}) if t_cfg else {}
    logger.info(f"🔐 Security Config Found: {sec_lists}")

    # Normaliza telefone (remove sufixo @s.whatsapp.net se houver)
    sender_phone = chat_id.split("@")[0] if "@" in chat_id else chat_id

    # 1. Blocklist (Se estiver na lista, PARE)
    blocklist = sec_lists.get("blocked_numbers", "")
    if blocklist:
        blocked_numbers = [
            n.strip() for n in blocklist.replace("\n", ",").split(",") if n.strip()
        ]
        if sender_phone in blocked_numbers:
            logger.warning(f"🚫 Sender {sender_phone} is in BLOCKLIST. Aborting.")
            Kestra.outputs(
                {"response_text": "", "chat_id": chat_id, "api_url": "", "api_key": ""}
            )
            return

    # 2. Whitelist (Se lista existir E sender NÃO estiver nela, PARE)
    whitelist = sec_lists.get("allowed_numbers", "")
    if whitelist:
        logger.info(
            f"🛡️ Security Whitelist Check: Sender={sender_phone} | Raw List={repr(whitelist)}"
        )
        allowed_numbers = [
            n.strip() for n in whitelist.replace("\n", ",").split(",") if n.strip()
        ]
        logger.info(f"🛡️ Valid Allowed Numbers: {allowed_numbers}")

        if sender_phone not in allowed_numbers:
            logger.warning(f"🛡️ Sender {sender_phone} NOT in WHITELIST. Aborting.")
            Kestra.outputs(
                {"response_text": "", "chat_id": chat_id, "api_url": "", "api_key": ""}
            )
            return
    # -------------------------------------------------------------

    if t_cfg:
        # 1. Desativar IA (Opt-out)
        stop_cfg = t_cfg.get("desativar_ia", {})
        # Normaliza bool/dict
        if isinstance(stop_cfg, bool):
            stop_cfg = {"active": stop_cfg}

        if stop_cfg.get("active"):
            instr = stop_cfg.get("instructions", "")
            if instr:
                system_prompt += f"\n\n🚨 **REGRA DE PARADA (OPT-OUT)**:\n{instr}\n👉 SE detectar essa intenção, CHAME A TOOL `desativar_ia` IMEDIATAMENTE."
    # ---------------------------------------------

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

        # Output VAZIO para não disparar envio (mas com todas as vars esperadas pelo Flow)
        Kestra.outputs(
            {"response_text": "", "chat_id": chat_id, "api_url": "", "api_key": ""}
        )
        return
    # -------------------------------

    # -------------------------------

    # 3b. Define Chave do Buffer (Namespaced)
    # Deve bater com a lógica do ingest.py: f"{client_id}:{chat_id}{BUFFER_KEY_SUFIX}"
    client_id_str = str(client_config["id"])
    key = f"{client_id_str}:{chat_id}{BUFFER_KEY_SUFIX}"

    # Leitura + Limpeza Atômica
    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        results = await pipe.execute()

    msgs = results[0]

    # --- FALLBACK DE COMPATIBILIDADE ---
    # Se não achou na chave nova, tenta na chave antiga (sem namespace) para não perder msg em voo
    if not msgs:
        old_key = f"{chat_id}{BUFFER_KEY_SUFIX}"
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(old_key, 0, -1)
            pipe.delete(old_key)
            results = await pipe.execute()
        msgs = results[0]
        if msgs:
            logger.warning(
                f"⚠️ Mensagens encontradas na chave legada (sem namespace): {chat_id}"
            )
    # -----------------------------------

    if not msgs:
        logger.info(
            f"Buffer vazio para {chat_id}. Worker duplicado ou chave incorreta?"
        )
        await redis_client.aclose()
        Kestra.outputs(
            {"response_text": "", "chat_id": chat_id, "api_url": "", "api_key": ""}
        )
        return

    # Parse JSON Messages (Protocolo v2: {"text": "...", "id": "..."})
    final_texts = []
    last_msg_id = None

    for m in msgs:
        try:
            # Tenta decodificar JSON
            data = json.loads(m)
            if isinstance(data, dict):
                text = data.get("text", "")
                if text:
                    final_texts.append(text)

                # Atualiza último ID visto
                if data.get("id"):
                    last_msg_id = data.get("id")
            else:
                # Fallback se for string pura (legado)
                final_texts.append(str(m))

        except json.JSONDecodeError:
            # string pura
            final_texts.append(str(m))

    full_query = " ".join(final_texts)
    logger.info(f"💬 Query do Usuário: {full_query} (Last ID: {last_msg_id})")

    # Injeta ID no System Prompt para uso de ferramentas
    # MOVIDO PARA O FINAL DO PROMPT para dar maior peso (Recency Bias)
    reaction_instruction = ""
    if last_msg_id:
        # Busca instruções de reação do cliente
        tools_cfg = client_config.get("tools_config", {})
        react_cfg = tools_cfg.get("whatsapp_reactions", {})
        react_instructions = react_cfg.get("instructions", "")

        if react_cfg.get("active"):
            reaction_instruction = f"""
\n🚨 **INSTRUÇÃO CRÍTICA DE INTERFACE (REAÇÕES)** 🚨
O ID da mensagem do usuário é: '{last_msg_id}'
"""
            # Se cliente configurou instruções de quando reagir
            if react_instructions:
                reaction_instruction += f"""
📋 **REGRAS DE REAÇÃO DO CLIENTE**:
{react_instructions}
"""

            reaction_instruction += f"""
COMO REAGIR:
1. ⚠️ **OPCIONAL/PREFERENCIAL**: Se apropriado, use `reagir_mensagem(emoji='...', message_id='{last_msg_id}')`.
2. 🚫 **PROIBIDO**: NÃO coloque o emoji no texto da sua resposta. Use a Tool ou nada.
3. ⚡ **PRIORIDADE**: Se o usuário pedir explícitamente ("Reaja", "Curta"), USE a ferramenta IMEDIATAMENTE.
"""
            # Adiciona ao final do prompt existente
            system_prompt += reaction_instruction

        # --- LOOP GENÉRICO DE INSTRUÇÕES DE FERRAMENTAS ---
        # Injeta instruções específicas de cada ferramenta ativa (ex: consultar_cep, agendamento, etc)
        for tool_name, tool_data in tools_cfg.items():
            # Pula reactions pois já foi tratado acima com lógica especial
            if tool_name == "whatsapp_reactions":
                continue

            if isinstance(tool_data, dict) and tool_data.get("active"):
                instructions = tool_data.get("instructions")
                if instructions:
                    system_prompt += f"""
\n🔧 **INSTRUÇÕES PARA {tool_name.upper()}**:
{instructions}
"""

        # INSTRUÇÃO DE PRIORIDADE DE FERRAMENTAS
        system_prompt += f"""
\n⚡ **PRIORIDADE DE EXECUÇÃO** ⚡
O parâmetro 'chat_id' é: '{chat_id}'
Se o usuário pedir uma ação (ex: "Agende", "Verifique"), IGNORE o RAG e use a ferramenta.
"""

        # --- REINFORÇO ANTI-LOOP GLOBAL (RECENCY BIAS) ---
        system_prompt += """
\n🚫 **REGRA DE OURO (ANTI-LOOP)** 🚫
1. **NÃO chame a mesma ferramenta duas vezes** com os mesmos argumentos.
2. Se a ferramenta retornou dados (mesmo que seja um dicionário JSON), **PARE E RESPONDA** ao usuário usando esses dados.
3. Não tente "confirmar" chamando a ferramenta de novo. O primeiro resultado é o correto.
4. Se `consultar_cep` retornou o endereço, **NÃO** chame-a novamente. Apenas diga o endereço para o cliente.
"""

    # --- PERSISTÊNCIA DE HISTÓRICO (CRÍTICO PARA FOLLOW-UP) ---
    try:
        from saas_db import add_message

        # Salva msg do User
        add_message(client_config["id"], chat_id, "user", full_query)
    except Exception as e:
        logger.error(f"❌ Erro ao salvar histórico (User): {e}")
    # ------------------------------------------------------------

    # --- AUTO-DETECT OPT-OUT TRIGGERS (Bypass AI) ---
    stop_cfg = t_cfg.get("desativar_ia", {}) if t_cfg else {}
    if isinstance(stop_cfg, bool):
        stop_cfg = {"active": stop_cfg}

    if stop_cfg.get("active"):
        trigger_text = stop_cfg.get("instructions", "")
        # Extrai gatilhos do texto (ex: "Se enviar 👍" -> procura por "👍")
        # Também aceita padrões como #desativar, 👍, 🛑, etc.
        import re

        # Pega emojis e hashtags do trigger_text
        emojis_pattern = r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U0001F44D\U0001F44E👍👎🛑✋✅❌🚫💀]"
        hashtags_pattern = r"#\w+"

        found_emojis = re.findall(emojis_pattern, trigger_text)
        found_hashtags = re.findall(hashtags_pattern, trigger_text)

        triggers = found_emojis + found_hashtags + ["#desativar", "#parar"]  # Defaults

        # Verifica se a mensagem do usuário contém algum trigger
        user_msg_lower = full_query.lower().strip()
        for trigger in triggers:
            if trigger.lower() in user_msg_lower or trigger in full_query:
                logger.info(
                    f"🛑 TRIGGER DETECTADO: '{trigger}' na mensagem. Desativando IA automaticamente."
                )
                # Desativa diretamente no Redis
                pause_key = f"ai_paused:{chat_id}"
                await redis_client.set(pause_key, "true_permanent")
                await redis_client.aclose()

                # Retorna mensagem de confirmação
                Kestra.outputs(
                    {
                        "response_text": "✅ Entendido! A IA foi desativada para você. Um atendente humano assumirá a partir de agora.",
                        "chat_id": chat_id,
                        "api_url": client_config.get("api_url", ""),
                        "api_key": client_config.get("token", ""),
                    }
                )
                return
    # -----------------------------------------------

    # --- CHECK: Respostas Automáticas (IA) Ativadas? ---
    tools_config = client_config.get("tools_config") or {}
    ai_active = tools_config.get(
        "ai_active", True
    )  # Default True para retrocompatibilidade

    if not ai_active:
        logger.info(
            f"🔇 IA DESATIVADA para cliente {client_config['name']}. Ignorando mensagem."
        )
        Kestra.outputs(
            {"response_text": "", "chat_id": chat_id, "api_url": "", "api_key": ""}
        )
        return
    # ------------------------------------------------

    # 4. Processamento Inteligente (Agente Híbrido: OpenAI + Gemini Tools)
    # Importa aqui para evitar circularidade se houver, ou move para topo
    from chains_saas import ask_saas

    try:
        # Carrega Tools Dinâmicas (passa chat_id para injeção em atendimento_humano)
        tools_list = get_enabled_tools(
            client_config.get("tools_config"),
            chat_id=chat_id,
            client_config=client_config,
            last_msg_id=last_msg_id,
        )

        # DEBUG PROMPT INJECTION
        logger.info(f"🧠 SYSTEM PROMPT (Last 600 chars): ...{system_prompt[-600:]}")

        # Chama o Cérebro (OpenAI) passando as Tools (Gemini/Maps)
        # 4. CHAMA A IA (Multimodal + Tools + RAG)
        response_text, usage_data, history_messages = await ask_saas(
            query=full_query,
            chat_id=chat_id,
            system_prompt=system_prompt,
            client_config=client_config,
            tools_list=tools_list,
        )

        logger.info(f"🤖 Resposta Agente SaaS: {response_text[:50]}...")

        # === DEBUG AVANÇADO DE FERRAMENTAS ===
        logger.info(
            f"🔍 [DEBUG FERRAMENTAS] Analisando histórico de execução ({len(history_messages)} msgs)..."
        )
        found_tool_calls = False
        for msg in history_messages:
            # Verifica se a mensagem tem 'tool_calls' (OpenAI)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                found_tool_calls = True
                for tc in msg.tool_calls:
                    logger.info(
                        f"🛠️ [TOOL DECISION] O Agente DECIDIU chamar: {tc.get('name')} | Arms: {tc.get('args')}"
                    )

            # Verifica mensagens de 'tool' (Output da ferramenta)
            if msg.type == "tool":
                logger.info(
                    f"📉 [TOOL OUTPUT] Retorno da ferramenta {msg.name}: {msg.content[:200]}..."
                )

        # Metrics: registra tools usadas
        if found_tool_calls:
            for msg in history_messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        log_event(str(client_config["id"]), chat_id, "tool_used", {"tool": tc.get("name", "unknown")})

        if not found_tool_calls:
            logger.info(
                "🚫 [DEBUG FERRAMENTAS] O Agente NÃO tentou chamar nenhuma ferramenta nesta execução."
            )
            logger.info(
                f"👀 Contexto de Reação: LastMsgID={last_msg_id} | ChatID={chat_id}"
            )
            logger.info(
                "💡 Dica: Verifique se o prompt realmente exige 'obrigatório' ou se a IA achou desnecessário."
            )
        # =====================================

        # Salva usage para tracking de custos
        try:
            from usage_tracker import save_usage

            save_usage(
                client_id=str(client_config["id"]),
                chat_id=chat_id,
                source="rag_worker",
                provider="uazapi",
                openai_usage=usage_data.get("openai"),
                gemini_usage=usage_data.get("gemini"),
            )
        except Exception as e:
            logger.warning(f"⚠️ Erro ao salvar usage: {e}")

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

        # Buscar config do provider Uazapi
        uazapi_cfg = get_provider_config(str(client_config["id"]), "uazapi")

        # Fallback para estrutura antiga se provider não migrado
        if not uazapi_cfg:
            tools_cfg = client_config.get("tools_config", {}) or {}
            w_cfg = tools_cfg.get("whatsapp", {})
            uazapi_cfg = {
                "url": client_config.get("api_url") or w_cfg.get("url") or "",
                "token": client_config.get("token") or w_cfg.get("key") or "",
            }

        api_override_url = uazapi_cfg.get("url") or ""
        api_override_key = uazapi_cfg.get("token") or client_token or ""

        # --- TRACKING: Marca que a IA respondeu ---
        try:
            _cid = client_config.get("id") if client_config else None
            if _cid and chat_id:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO active_conversations (chat_id, client_id, last_message_at, last_role, status)
                            VALUES (%s, %s, NOW(), 'ai', 'active')
                            ON CONFLICT (chat_id, client_id) DO UPDATE SET
                                last_message_at = NOW(),
                                last_role = 'ai';
                        """,
                            (chat_id, _cid),
                        )
                        conn.commit()
                logger.info(f"\U0001f916 Tracking: IA respondeu em {chat_id}")
                # Metrics: registra resposta da IA
                log_event(str(_cid), chat_id, "ai_responded", {
                    "tokens": usage_data.get("openai", {}).get("total_tokens", 0) if usage_data else 0
                })
        except Exception as e:
            logger.warning(f"\u26a0\ufe0f Erro ao trackear resposta IA: {e}")
        # ------------------------------------------------

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
        # --- ERROR LOGGING ---
        try:
            from saas_db import log_error

            cid = (
                client_config.get("id")
                if "client_config" in locals() and client_config
                else None
            )
            # Contexto extra
            ctx = {
                "chat_id": chat_id,
                "step": "rag_generation",
                "query": full_query if "full_query" in locals() else "N/A",
            }
            log_error("rag_worker.py", e, ctx, client_id=cid, chat_id=chat_id)
        except Exception as log_err:
            logger.error(f"Failed to log error to DB: {log_err}")
        # ---------------------
        raise e
    finally:
        # Garante fechamento da conexão Redis
        if redis_client:
            await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_rag())
