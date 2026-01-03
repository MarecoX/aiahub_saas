import logging
from typing import Dict, Any, Optional

from scripts.shared.saas_db import get_client_config, get_client_token_by_waba_phone
from scripts.shared.chains_saas import ask_saas
from scripts.meta.meta_client import MetaClient

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
                waba_cfg = tools.get("whatsapp_official", {})

                # Validação de Segurança
                if not waba_cfg.get("active"):
                    logger.info(
                        f"⏸️ Integração Meta Desativada para cliente {client_config['name']}"
                    )
                    continue

                access_token = waba_cfg.get("token")  # Token do System User

                # Instancia Cliente Graph API
                meta = MetaClient(access_token, phone_id_from_webhook)

                # Processa Mensagens
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])

                for msg in messages:
                    msg_type = msg.get("type")
                    from_phone = msg.get("from")  # Número do Cliente Final

                    # LÓGICA DE RESPOSTA (Texto apenas por enquanto)
                    if msg_type == "text":
                        user_text = msg["text"]["body"]
                        logger.info(f"📩 WABA Msg de {from_phone}: {user_text}")

                        # CHAMA O AGENTE IA
                        chat_id = f"waba_{phone_id_from_webhook}_{from_phone}"  # Ex: waba_1010_5511999...

                        # Show typing...
                        # (Meta não tem typing indicator oficial fácil na API Cloud v1, mas ok)

                        response_text = await ask_saas(
                            query=user_text,
                            chat_id=chat_id,
                            system_prompt=client_config["system_prompt"],
                            client_config=client_config,
                            tools_list=[],  # Implementar tools se necessário
                        )

                        # Envia Resposta
                        await meta.send_message_text(from_phone, response_text)

                    elif msg_type == "image":
                        # Payload: msg["image"] -> {id, mime_type, sha256, caption}
                        image_data = msg.get("image", {})
                        media_id = image_data.get("id")
                        caption = image_data.get("caption", "")
                        mime_type = image_data.get("mime_type")

                        logger.info(
                            f"📸 WABA Imagem de {from_phone} | ID: {media_id} | Caption: {caption}"
                        )

                        # TODO: Baixar mídia usando meta.get_media_url(media_id) e passar para Vision API
                        # Por enquanto, avisamos que recebemos
                        await meta.send_message_text(
                            from_phone, f"📸 Recebi sua imagem! (ID: {media_id})"
                        )

                    elif msg_type == "audio":
                        # Payload: msg["audio"] -> {id, mime_type, voice}
                        audio_data = msg.get("audio", {})
                        media_id = audio_data.get("id")
                        is_voice = audio_data.get("voice", False)

                        logger.info(
                            f"🎤 WABA Áudio de {from_phone} | ID: {media_id} | VoiceNote: {is_voice}"
                        )

                        # TODO: Baixar mídia e transcrever com Whisper
                        await meta.send_message_text(
                            from_phone, f"🎤 Recebi seu áudio! (ID: {media_id})"
                        )

                    else:
                        logger.info(
                            f"Tipo de mensagem não suportado por enquanto: {msg_type}"
                        )

    except Exception as e:
        logger.error(f"❌ Erro crítico no processamento Meta: {e}", exc_info=True)
