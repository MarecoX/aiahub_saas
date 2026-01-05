import logging
from typing import Dict, Any, Optional

from scripts.shared.saas_db import (
    get_client_config,
    get_client_token_by_waba_phone,
    add_message,
)
from scripts.shared.chains_saas import ask_saas
from scripts.meta.meta_client import MetaClient
from scripts.shared.chains_saas import ask_saas
from scripts.meta.meta_client import MetaClient
from scripts.shared.media_utils import transcribe_audio_bytes, analyze_image_bytes
import redis
from scripts.shared.tools_library import get_enabled_tools

logger = logging.getLogger(__name__)

VERIFY_TOKEN_SECRET = "aiahub_meta_secret_2026"  # Hardcoded or Env Var


def verify_webhook_challenge(mode: str, token: str, challenge: str) -> Optional[str]:
    """Valida o handshake da Meta (GET /webhook)."""
    if mode == "subscribe" and token == VERIFY_TOKEN_SECRET:
        logger.info("✅ Webhook Meta Verificado com Sucesso!")
        return challenge
    logger.warning(f"⚠️ Falha na verificação do Webhook. Token recebido: {token}")
    return None


async def process_incoming_webhook(data: Dict[str, Any]):
    """
    Processa o payload POST do Webhook da Meta.
    Extrai mensagens, identifica o cliente e chama a IA.
    """
    try:
        entry = data.get("entry", [])
        if not entry:
            return

        for e in entry:
            changes = e.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                # Check messages
                if "messages" not in value:
                    continue

                metadata = value.get("metadata", {})
                phone_id_from_webhook = metadata.get("phone_number_id")

                # BUSCA CLIENTE PELO PHONE ID
                client_token = get_client_token_by_waba_phone(phone_id_from_webhook)

                if not client_token:
                    logger.warning(
                        f"⚠️ Mensagem recebida de PhoneID desconhecido: {phone_id_from_webhook}"
                    )
                    continue

                # Carrega Config Completa do Cliente
                client_config = get_client_config(client_token)
                if not client_config:
                    continue

                # Extrai Credenciais WABA do tools_config do cliente
                tools = client_config.get("tools_config", {})

                # Check priority: 'whatsapp' (new) > 'whatsapp_official' (legacy)
                waba_cfg = tools.get("whatsapp", {})
                if not waba_cfg.get("active") and not waba_cfg.get("token"):
                    waba_cfg = tools.get("whatsapp_official", {})

                # Validação de Segurança
                if not waba_cfg.get("active"):
                    logger.info(
                        f"⏸️ Integração Meta Desativada para cliente {client_config['name']}"
                    )
                    continue

                access_token = waba_cfg.get("access_token") or waba_cfg.get(
                    "token"
                )  # Token do System User

                # Instancia Cliente Graph API
                meta = MetaClient(access_token, phone_id_from_webhook)

                # Processa Mensagens
                messages = value.get("messages", [])
                for msg in messages:
                    msg_type = msg.get("type")
                    from_phone = msg.get("from")  # Número do Cliente Final

                    # --- CHECK HUMAN PAUSE (REDIS) ---
                    # Verifica se o atendimento foi pausado para humano
                    try:
                        redis_url = (
                            client_config.get("redis_url") or "redis://localhost:6379"
                        )
                        r = redis.Redis.from_url(redis_url, decode_responses=True)
                        pause_key = f"ai_paused:{from_phone}"
                        if r.get(pause_key):
                            logger.info(
                                f"🛑 Chat {from_phone} pausado por humano. Ignorando mensagem."
                            )
                            r.close()
                            continue
                        r.close()
                    except Exception as e:
                        logger.error(f"Erro ao checar Redis Pause: {e}")
                    # ---------------------------------

                    # --- INBOX LOGGING (USER) ---
                    msg_content = ""
                    media_url = None
                    if msg_type == "text":
                        msg_content = msg["text"]["body"]
                    elif msg_type == "image":
                        msg_content = msg.get("image", {}).get("caption", "[Imagem]")
                    elif msg_type == "audio":
                        msg_content = "[Áudio]"
                    else:
                        msg_content = f"[{msg_type.upper()}]"

                    add_message(
                        client_id=client_config["id"],
                        chat_id=from_phone,
                        role="user",
                        content=msg_content,
                        media_url=media_url,
                    )
                    # -----------------------------

                    # -----------------------------

                    # LÓGICA DE UNIFICAÇÃO DE TEXTO (Multimodal)
                    user_text = None

                    if msg_type == "text":
                        user_text = msg_content

                    elif msg_type == "audio":
                        audio_data = msg.get("audio", {})
                        media_id = audio_data.get("id")
                        mime_type = audio_data.get("mime_type", "audio/ogg")

                        logger.info(f"🎙️ WABA Áudio de {from_phone} | ID: {media_id}")

                        # Download & Transcribe
                        try:
                            media_url = await meta.get_media_url(media_id)
                            if media_url:
                                audio_bytes = await meta.download_media_bytes(media_url)
                                if audio_bytes:
                                    transcription = transcribe_audio_bytes(audio_bytes)
                                    user_text = f"[ÁUDIO DO USUÁRIO]: {transcription}"
                        except Exception as e:
                            logger.error(f"❌ Falha ao processar áudio: {e}")
                            user_text = "[Áudio enviado, mas erro na transcrição]"

                    elif msg_type == "image":
                        image_data = msg.get("image", {})
                        media_id = image_data.get("id")
                        mime_type = image_data.get("mime_type", "image/jpeg")
                        caption = image_data.get("caption", "")

                        logger.info(f"📸 WABA Imagem de {from_phone} | ID: {media_id}")

                        # Download & Analyze
                        try:
                            media_url = await meta.get_media_url(media_id)
                            if media_url:
                                image_bytes = await meta.download_media_bytes(media_url)
                                if image_bytes:
                                    description = analyze_image_bytes(
                                        image_bytes, mime_type
                                    )
                                    user_text = f"[IMAGEM ENVIADA]:\nDescrição Visual: {description}"
                                    if caption:
                                        user_text += f"\nLegenda do Usuário: {caption}"
                        except Exception as e:
                            logger.error(f"❌ Falha ao processar imagem: {e}")
                            user_text = (
                                f"[Imagem enviada: {caption}]"
                                if caption
                                else "[Imagem enviada]"
                            )

                    # PROCESSAMENTO FINAL (SE HOUVER TEXTO OU CONTEXTO MULTIMODAL)
                    if user_text:
                        logger.info(
                            f"📩 WABA Processando de {from_phone}: {user_text[:100]}..."
                        )

                        # PREPARE TOOLS
                        tools_list = get_enabled_tools(
                            tools_config=tools.get("functions", {}),
                            chat_id=from_phone,
                            client_config=client_config,
                        )

                        # CHAMA O AGENTE IA
                        response_text = await ask_saas(
                            query=user_text,
                            chat_id=from_phone,
                            system_prompt=client_config["system_prompt"],
                            client_config=client_config,
                            tools_list=tools_list,
                        )

                        # Envia Resposta
                        await meta.send_message_text(from_phone, response_text)

                        # --- INBOX LOGGING (ASSISTANT) ---
                        add_message(
                            client_id=client_config["id"],
                            chat_id=from_phone,
                            role="assistant",
                            content=response_text,
                        )
                        # ---------------------------------
                        resp = f"🎤 Recebi seu áudio! (ID: {media_id})"
                        await meta.send_message_text(from_phone, resp)

                        add_message(client_config["id"], from_phone, "assistant", resp)

                    else:
                        logger.info(
                            f"Tipo de mensagem não suportado por enquanto: {msg_type}"
                        )

    except Exception as e:
        logger.error(f"❌ Erro crítico no processamento Meta: {e}", exc_info=True)
