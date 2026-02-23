import os
import json
import logging
import asyncio
import base64
import redis.asyncio as redis
from kestra import Kestra

# Import local modules
import sys

# Adiciona o diretório 'shared' ao path para importar módulos compartilhados
current_dir = os.path.dirname(os.path.abspath(__file__))
shared_dir = os.path.join(os.path.dirname(current_dir), "shared")
sys.path.append(shared_dir)

from config import REDIS_URL
from message_buffer import buffer_message  # noqa: E402
from saas_db import get_client_token_by_phone, get_client_config  # noqa: E402

# Config logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IngestLancePilot")


async def run_ingest():
    """
    Ingestão Específica para Webhooks do LancePilot (V3).
    Espera receber o payload do LP.
    Identificação do Cliente:
    1. Via Query Param ?token=XYZ (Prioritário)
    2. Via Payload field 'to' (Número Conectado) -> Database Lookup
    """
    logger.info("🚀 Iniciando Ingestão LancePilot")

    # 1. Inputs do Kestra (Prioriza B64 para evitar erro Pebble com {{ }} no payload)
    body_b64 = os.getenv("KESTRA_TRIGGER_BODY_B64")
    if body_b64:
        try:
            body_json = base64.b64decode(body_b64).decode("utf-8")
            logger.info("📦 Input decodificado de B64 com sucesso")
        except Exception as e:
            logger.error(f"Erro ao decodificar B64: {e}")
            body_json = "{}"
    else:
        body_json = os.getenv("KESTRA_TRIGGER_BODY", "{}")
    webhook_token = os.getenv("KESTRA_WEBHOOK_TOKEN")

    if not body_json:
        logger.warning("Empty Body. Exiting.")
        return

    try:
        data = json.loads(body_json)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON Body: {body_json}")
        return

    # DEBUG: Log raw payload to understand structure
    logger.info(f"🔍 DEBUG RAW DATA: {json.dumps(data, indent=2)}")

    # LancePilot Default Structure: { "event": "message.incoming", "data": { ... } }
    event = data.get("event")

    lp_data = data.get("data", {})
    attrs = lp_data.get("attributes", {})
    source = attrs.get("source")
    to_number = attrs.get("to")

    # LÓGICA DE FILTRO DE EVENTOS
    # 1. Mensagem recebida do contato (Customer) -> message.incoming
    # 2. Mensagem enviada pelo Humano (App) -> message.outgoing + source='app'
    # 3. Mensagem enviada pela AI (API) -> message.outgoing + source='api' (IGNORAR)

    # Helper para limpar JID
    def clean_jid(jid):
        if not jid:
            return None
        return jid.split("@")[0].replace("+", "")

    # LÓGICA DE DIREÇÃO E IDENTIFICAÇÃO
    # Definimos quem é a Empresa (Business) e quem é o Cliente Final (Customer/ChatID)
    if event == "message.outgoing":
        # Outgoing: From Business(App) -> To Customer
        business_number = attrs.get("from")
        chat_id = clean_jid(attrs.get("to"))

        if source == "app":
            logger.info(
                "🛑 Detectado mensagem enviada por HUMANO (message.outgoing + source='app')."
            )
        else:
            logger.info(
                f"Ignorando message.outgoing com source='{source}' (Provável envio da IA)."
            )
            Kestra.outputs({"status": "ignored_outgoing", "chat_id": "None"})
            return

    elif event == "message.incoming":
        # Incoming: From Customer -> To Business
        business_number = attrs.get("to")
        # Usa o número do contato (relationships.contact.attributes.number) pois é o formato correto para envio
        # O campo "from" pode vir em formato diferente do esperado pela API de envio
        contact_data = lp_data.get("relationships", {}).get("contact", {})
        contact_attrs = contact_data.get("attributes", {})
        contact_number = contact_attrs.get("number") or attrs.get("from")
        chat_id = clean_jid(contact_number)

    else:
        logger.info(f"Ignorando evento desconhecido: {event}")
        Kestra.outputs({"status": "ignored_event", "chat_id": "None"})
        return

    cleaned_business_number = clean_jid(business_number)

    # --- 2. Identificação do Cliente (SaaS) ---
    # Se não veio token na URL, tenta pegar pelo número da EMPRESA (business_number)
    if not webhook_token or webhook_token == "None":
        logger.info(
            f"⚠️ Token ausente na URL. Buscando cliente pelo número (Business): {cleaned_business_number} (Raw: {business_number})"
        )

        if cleaned_business_number:
            webhook_token = get_client_token_by_phone(cleaned_business_number)
            if webhook_token:
                logger.info(f"✅ Cliente identificado: {webhook_token}")
            else:
                logger.error(
                    f"❌ NENHUM cliente configurado com o número {cleaned_business_number}!"
                )

                # Se for outgoing humano e não achou client, não conseguimos pausar adequadamente se precisarmos de config.
                # Mas logamos warning.
                if event == "message.outgoing":
                    logger.warning(
                        "Não foi possível identificar cliente para pausar IA."
                    )
                    return

                Kestra.outputs({"status": "client_not_found", "chat_id": "None"})
                return
        else:
            logger.error(
                "❌ Token ausente E business_number vazio. Impossível identificar cliente."
            )
            Kestra.outputs({"status": "missing_identity", "chat_id": "None"})
            return

    # Human Handover Check
    # Se source == 'app', foi enviado pelo atendente humano via painel do LancePilot/App
    source = attrs.get("source")  # Re-get just in case

    if source == "app":
        logger.info(
            f"🛑 Mensagem enviada por Humano (App) para {chat_id}. Verificando Opt-out..."
        )

        # Tenta extrair texto da mensagem do App
        outgoing_text = ""
        try:
            outgoing_text = attrs.get("message", {}).get("body", "") or attrs.get(
                "message", {}
            ).get("text", {}).get("body", "")
        except Exception:
            pass

        # Configs de Cliente
        timeout_seconds = 3600  # Default
        is_permanent_stop = False

        if webhook_token:
            try:
                client_cfg = get_client_config(webhook_token)
                if client_cfg:
                    # 1. Verifica se deve Parar Permanentemente (Opt-out Trigger)
                    tools_cfg = client_cfg.get("tools_config", {})
                    stop_cfg = tools_cfg.get("desativar_ia", {})
                    if isinstance(stop_cfg, bool):
                        stop_cfg = {"active": stop_cfg}

                    if stop_cfg.get("active") and outgoing_text:
                        instr = stop_cfg.get("instructions", "")
                        # Checa se o texto contem o gatilho (ex: emoji)
                        # Logica simples: Se o gatilho estiver contido na mensagem
                        triggers = [
                            t.strip() for t in instr.split(",") if t.strip()
                        ]  # Pode separar por virgula
                        # Ou check genérico se instrução menciona algo
                        # Vamos assumir check simples: se o texto for IGUAL ou CONTER emoji
                        if any(t in outgoing_text for t in triggers) or (
                            "🛑" in outgoing_text
                        ):
                            is_permanent_stop = True
                            logger.info(
                                f"🛑 GATILHO DE PARADA TOTAL DETECTADO NA MENSAGEM DO ATENDENTE: {outgoing_text}"
                            )

                    # 1.5 Check "permanent on human reply" config
                    ah_cfg = tools_cfg.get("atendimento_humano", {})
                    if isinstance(ah_cfg, bool):
                        ah_cfg = {"active": ah_cfg}
                    if ah_cfg.get("permanent_on_human_reply", False):
                        is_permanent_stop = True
                        logger.info(
                            f"💀 PARADA PERMANENTE (permanent_on_human_reply=True) para {chat_id}"
                        )

                    # 2. Configura Timeout Normal
                    configured_timeout = client_cfg.get("human_attendant_timeout")
                    if configured_timeout:
                        timeout_seconds = int(configured_timeout) * 60
            except Exception as e:
                logger.error(f"Erro ao buscar config cliente: {e}")

        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            pause_key = f"ai_paused:{chat_id}"

            if is_permanent_stop:
                # Set SEM expiração = Permanente
                await r.set(pause_key, "true_permanent")
                logger.info(f"💀 IA MORTA (Permanente) via Atendente para {chat_id}")
            else:
                # Set COM expiração = Pausa Temporária
                await r.set(pause_key, "true", ex=timeout_seconds)
                logger.info(
                    f"🛑 ATIVANDO PAUSA TEMPORÁRIA: {timeout_seconds}s para {chat_id}"
                )

            await r.aclose()
        except Exception as e:
            logger.error(f"Erro Redis Pause: {e}")

        Kestra.outputs(
            {
                "status": "human_sent_paused",
                "chat_id": str(chat_id),
                "mode": "permanent" if is_permanent_stop else "temporary",
            }
        )
        return

    message_payload = attrs.get("message", {})
    message_type = message_payload.get("type", "text")

    # Extrai conteúdo baseado no tipo de mensagem
    message_body = None

    if message_type == "text":
        # Tenta pegar message.body (direto) ou message.text.body (estrutura aninhada)
        message_body = message_payload.get("body")
        if not message_body:
            message_body = message_payload.get("text", {}).get("body")

    elif message_type == "audio":
        # Áudio: baixa e transcreve usando OpenAI Whisper
        audio_url = message_payload.get("audio", {}).get("value")
        if audio_url:
            logger.info(f"🎤 Áudio detectado. Transcrevendo: {audio_url[:50]}...")
            try:
                import httpx
                from openai import OpenAI
                import tempfile

                # Baixa o áudio
                audio_response = httpx.get(audio_url, timeout=30.0)
                if audio_response.status_code == 200:
                    # Salva temporariamente
                    with tempfile.NamedTemporaryFile(
                        suffix=".ogg", delete=False
                    ) as tmp_file:
                        tmp_file.write(audio_response.content)
                        tmp_path = tmp_file.name

                    # Transcreve com Whisper
                    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                    with open(tmp_path, "rb") as audio_file:
                        transcription = client.audio.transcriptions.create(
                            model="whisper-1", file=audio_file
                        )
                    message_body = transcription.text
                    logger.info(f"📝 Transcrição: {message_body[:50]}...")

                    # Remove arquivo temporário
                    os.unlink(tmp_path)
                else:
                    logger.error(f"Falha ao baixar áudio: {audio_response.status_code}")
            except Exception as e:
                logger.error(f"Erro na transcrição de áudio: {e}")
                message_body = "[Áudio recebido - transcrição falhou]"

    elif message_type == "image":
        # Imagem: por enquanto só loga, pode adicionar OCR/descrição futuramente
        image_url = message_payload.get("image", {}).get("value")
        logger.info(f"🖼️ Imagem recebida: {image_url}")
        message_body = f"[Imagem enviada: {image_url}]"

    else:
        # Outros tipos (document, video, etc)
        logger.info(f"📎 Tipo de mensagem não tratado: {message_type}")
        message_body = f"[{message_type} recebido]"

    to_number = attrs.get("to")  # Número do Business (opcional, para debug)
    logger.info(f"📨 LP Webhook de {chat_id} para {to_number}")

    if not chat_id or not message_body:
        logger.warning(
            f"Payload incompleto. ChatID: {chat_id}, BodyFound: {bool(message_body)}"
        )
        return

    logger.info(f"💬 Conteúdo: {message_body[:50]}...")

    # --- COMANDOS ESPECIAIS (Palavras-chave) ---
    message_lower = message_body.strip().lower()

    if message_lower == "#reset":
        # Limpa memória/histórico do chat
        logger.info(f"🔄 Comando #reset detectado para {chat_id}")
        try:
            from saas_db import clear_chat_history

            clear_chat_history(chat_id)
            logger.info(f"✅ Histórico limpo para {chat_id}")
        except Exception as e:
            logger.error(f"Erro ao limpar histórico: {e}")
        Kestra.outputs(
            {
                "chat_id": str(chat_id),
                "client_token": webhook_token,
                "status": "reset_executed",
            }
        )
        return

    if message_lower == "#ativar":
        # Remove pausa de atendimento humano
        logger.info(f"✅ Comando #ativar detectado para {chat_id}")
        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            pause_key = f"ai_paused:{chat_id}"
            deleted = await r.delete(pause_key)
            if deleted:
                logger.info(f"🤖 IA reativada para {chat_id}")
            else:
                logger.info(f"IA já estava ativa para {chat_id}")
            await r.close()
        except Exception as e:
            logger.error(f"Erro ao reativar IA: {e}")
        Kestra.outputs(
            {
                "chat_id": str(chat_id),
                "client_token": webhook_token,
                "status": "ai_reactivated",
            }
        )
        return
    # --- FIM COMANDOS ESPECIAIS ---

    # 4. Buffer (Redis)
    # Usamos o mesmo message_buffer do fluxo principal, pois a lógica de debounce é igual.
    # O worker RAG vai ler desse buffer depois.
    try:
        await buffer_message(chat_id, message_body)
    except Exception as e:
        logger.error(f"❌ Erro Buffer: {e}")
        raise e

    # 5. Output para Kestra
    # Passamos o chat_id e o token (essencial para o RAG saber qual cliente carregar)
    Kestra.outputs(
        {"chat_id": str(chat_id), "client_token": webhook_token, "status": "buffered"}
    )


if __name__ == "__main__":
    asyncio.run(run_ingest())
