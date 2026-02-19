import logging
from typing import Dict, Any, Optional
import asyncio
import os
import redis

from scripts.shared.saas_db import (
    get_client_config,
    get_client_token_by_waba_phone,
    add_message,
    get_provider_config,
)
from scripts.shared.chains_saas import ask_saas
from scripts.meta.meta_client import MetaClient
from scripts.shared.media_utils import transcribe_audio_bytes
from scripts.shared.tools_library import get_enabled_tools

logger = logging.getLogger(__name__)

VERIFY_TOKEN_SECRET = os.getenv("META_VERIFY_TOKEN", "aiahub_meta_secret_2026")


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

                if "messages" not in value:
                    continue

                metadata = value.get("metadata", {})
                phone_id_from_webhook = metadata.get("phone_number_id")

                # BUSCA CLIENTE
                client_token = get_client_token_by_waba_phone(phone_id_from_webhook)
                if not client_token:
                    logger.warning(
                        f"⚠️ Mensagem de PhoneID desconhecido: {phone_id_from_webhook}"
                    )
                    continue

                # CONFIG
                client_config = get_client_config(client_token)
                if not client_config:
                    continue

                # Buscar config do provider Meta
                meta_cfg = get_provider_config(str(client_config["id"]), "meta")
                if not meta_cfg:
                    logger.warning(f"Meta provider não configurado para {client_config['id']}")
                    continue

                access_token = meta_cfg.get("access_token")
                meta = MetaClient(access_token, phone_id_from_webhook)

                # MESSAGES
                messages = value.get("messages", [])
                for msg in messages:
                    msg_type = msg.get("type")
                    from_phone = msg.get("from")

                    logger.info(f"📩 Webhook Meta de {from_phone} ({msg_type})")

                    # EXTRACT CONTENT
                    user_text = ""
                    if msg_type == "text":
                        user_text = msg.get("text", {}).get("body", "")
                    elif msg_type == "audio":
                        media_id = msg.get("audio", {}).get("id")
                        audio_bytes = await meta.download_media_bytes(
                            await meta.get_media_url(media_id)
                        )
                        if audio_bytes:
                            user_text = (
                                transcribe_audio_bytes(audio_bytes, "whisper-1") or ""
                            )
                            user_text += "\n[Áudio Transcrito]"
                    elif msg_type == "image":
                        caption = msg.get("image", {}).get("caption", "")
                        user_text = caption or "[Imagem recebida]"

                    if not user_text:
                        continue

                    # REDIS CONNECTION
                    redis_conn = None
                    try:
                        redis_url = (
                            client_config.get("redis_url")
                            or os.getenv("REDIS_URL")
                            or "redis://localhost:6379"
                        )
                        redis_conn = redis.Redis.from_url(
                            redis_url, decode_responses=True
                        )
                    except Exception as e:
                        logger.error(f"Redis Error: {e}")

                    # COMMANDS (Admin/Control)
                    msg_lower = user_text.strip().lower()
                    if msg_lower in ["#reset", "#ativar", "#stop", "#pausa"]:
                        if redis_conn:
                            if msg_lower == "#reset":
                                redis_conn.delete(f"ai_paused:{from_phone}")
                                redis_conn.delete(f"buffer:meta:{from_phone}")
                                await meta.send_message_text(
                                    from_phone, "🔄 Conversa reiniciada e IA ativa."
                                )
                                continue

                            elif msg_lower == "#ativar":
                                redis_conn.delete(f"ai_paused:{from_phone}")
                                await meta.send_message_text(
                                    from_phone, "✅ IA Reativada."
                                )
                                continue

                            elif msg_lower in ["#stop", "#pausa"]:
                                redis_conn.setex(
                                    f"ai_paused:{from_phone}", 86400, "true"
                                )
                                await meta.send_message_text(
                                    from_phone, "🛑 IA Pausada (Modo Humano)."
                                )
                                continue

                    # DEBOUNCE LOGIC
                    final_text = user_text
                    if redis_conn:
                        try:
                            buffer_key = f"buffer:meta:{from_phone}"
                            redis_conn.rpush(buffer_key, user_text)
                            await asyncio.sleep(2.0)

                            pipe = redis_conn.pipeline()
                            pipe.lrange(buffer_key, 0, -1)
                            pipe.delete(buffer_key)
                            results = pipe.execute()
                            buffered = results[0]

                            if not buffered:
                                continue
                            final_text = "\n".join(buffered)
                            logger.info(
                                f"📨 Processando lote de {len(buffered)} msgs de {from_phone}"
                            )
                        except Exception as e:
                            logger.error(f"Buffer Error: {e}")
                            final_text = user_text

                    # CHECK HUMAN PAUSE
                    if redis_conn and redis_conn.exists(f"ai_paused:{from_phone}"):
                        logger.info(f"🛑 Chat {from_phone} pausado. Salvando apenas.")
                        add_message(client_config["id"], from_phone, "user", final_text)
                        continue

                    # CALL AI
                    tools_config = client_config.get("tools_config", {})
                    tools_list = get_enabled_tools(
                        tools_config, chat_id=from_phone, client_config=client_config
                    )

                    from datetime import datetime
                    from zoneinfo import ZoneInfo

                    _now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
                    _dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
                    system_prompt = f"Data/Hora Atual: {_dias[_now_br.weekday()]}, {_now_br.strftime('%d/%m/%Y %H:%M')} (Fuso horário: UTC-3 Brasília)\n\n{client_config['system_prompt']}"
                    t_cfg = client_config.get("tools_config", {})
                    if t_cfg:
                        stop_cfg = t_cfg.get("desativar_ia", {})
                        if isinstance(stop_cfg, bool):
                            stop_cfg = {"active": stop_cfg}
                        if stop_cfg.get("active"):
                            instr = stop_cfg.get("instructions", "")
                            if instr:
                                system_prompt += f"\n\n🚨 **REGRA DE PARADA (OPT-OUT)**:\n{instr}\n👉 SE detectar essa intenção, CHAME A TOOL `desativar_ia` IMEDIATAMENTE."

                    response_text, _ = await ask_saas(
                        query=final_text,
                        chat_id=from_phone,
                        system_prompt=system_prompt,
                        client_config=client_config,
                        tools_list=tools_list,
                    )

                    if response_text:
                        await meta.send_message_text(from_phone, response_text)
                        add_message(client_config["id"], from_phone, "user", final_text)
                        add_message(
                            client_config["id"], from_phone, "assistant", response_text
                        )

    except Exception as e:
        logger.error(f"❌ Erro Webhook Meta: {e}", exc_info=True)
        return {"status": "error"}
