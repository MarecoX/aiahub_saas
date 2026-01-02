import httpx
import logging
from pathlib import Path
from typing import NamedTuple
import os
import base64
from google import genai
from google.genai import types


logger = logging.getLogger(__name__)

# Configuração
MEDIA_DIR = Path("media_downloads")
MEDIA_DIR.mkdir(exist_ok=True)
UAZAPI_URL = os.getenv("UAZAPI_URL")
UAZAPI_KEY = os.getenv("UAZAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class MessageInfo(NamedTuple):
    """Informações extraídas da mensagem."""

    text: str
    message_type: str
    media_path: str | None
    should_process: bool


async def download_and_process_media(
    message_id: str, media_type: str, message_data: dict
) -> tuple[str, str | None]:
    """
    Baixa e processa mídia usando UAZAPI com transcrição automática.

    Args:
        message_id: ID da mensagem
        media_type: Tipo (audio, image, video, document)
        message_data: Dados da mensagem (para quoted media)

    Returns:
        (texto_extraído, caminho_arquivo)
    """
    try:
        # Payload para UAZAPI
        payload = {
            "id": message_id,
            "return_link": True,
            "return_base64": media_type in ["image", "document"],  # Base64 para análise
        }

        # ← NOVO: Transcrição automática para áudio
        if media_type == "audio":
            payload["transcribe"] = True
            payload["generate_mp3"] = False  # Mantém OGG para economizar banda
            payload["openai_apikey"] = OPENAI_API_KEY

        # Download de status/mensagem citada
        if message_data.get("quoted"):
            payload["download_quoted"] = True

        logger.info(f"Baixando {media_type} ({message_id})...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{UAZAPI_URL}/message/download",
                json=payload,
                headers={"token": f"{UAZAPI_KEY}"},
            )
            response.raise_for_status()
            data = response.json()

        # ← NOVO: Extrai transcrição diretamente
        if media_type == "audio" and data.get("transcription"):
            text = data["transcription"].strip()
            logger.info(f"✅ Áudio transcrito: {text[:60]}...")
            return f"[ÁUDIO DO USUÁRIO]: {text}", None  # Adiciona contexto explícito

        # Para imagem/documento, salva base64 e analisa
        if data.get("base64Data"):
            mime_type = data.get("mimetype", "application/octet-stream")
            base64_data = data["base64Data"]

            # Análise com Gemini
            if media_type == "image":
                description = await _analyze_image_with_gemini(base64_data, mime_type)
                text = f"[IMAGEM ENVIADA PELO USUÁRIO]:\n{description}"
            elif media_type == "document":
                description = await _analyze_document_with_gemini(base64_data)
                text = f"[DOCUMENTO ENVIADO PELO USUÁRIO]:\n{description}"
            else:
                text = f"[{media_type.upper()}]"

            return text, None

        # Fallback: retorna URL
        file_url = data.get("fileURL")
        if file_url:
            logger.info(f"URL de mídia: {file_url}")
            return f"[{media_type.upper()}: {file_url}]", None

        return f"[Mídia {media_type} não pôde ser processada]", None

    except Exception as e:
        logger.error(f"❌ Erro ao processar mídia {message_id}: {e}")
        return "", None


async def _analyze_image_with_gemini(base64_data: str, mime_type: str) -> str:
    """Analisa imagem em base64 com Gemini (V2 SDK)."""
    try:
        logger.info("Analisando imagem com Gemini...")

        client = genai.Client(api_key=GEMINI_API_KEY)

        # Converte Base64 String -> Bytes
        image_bytes = base64.b64decode(base64_data)

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                "Procure e extraia uma descrição/transcrição completa do que você vê. Seja detalhado e específico. Se houver texto, transcreva-o.",
            ],
        )

        text = response.text.strip()
        logger.info(f"✅ Imagem analisada: {text[:60]}...")
        return text

    except Exception as e:
        logger.error(f"❌ Erro ao analisar imagem: {e}")
        return "[Imagem não pôde ser analisada]"


async def _analyze_document_with_gemini(base64_data: str) -> str:
    """Analisa documento PDF em base64 com Gemini (V2 SDK)."""
    try:
        logger.info("Analisando documento com Gemini...")

        client = genai.Client(api_key=GEMINI_API_KEY)

        # Converte Base64 String -> Bytes
        try:
            doc_bytes = base64.b64decode(base64_data)
        except:
            # Fallback se já vier bytes (improvável vindo de JSON, mas seguro)
            doc_bytes = base64_data

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=doc_bytes, mime_type="application/pdf"),
                "Procure e extraia uma descrição/transcrição completa do conteúdo. Resuma os pontos principais, estrutura e informações importantes. Seja detalhado.",
            ],
        )

        text = response.text.strip()
        logger.info(f"✅ Documento analisado: {text[:60]}...")
        return text

    except Exception as e:
        logger.error(f"❌ Erro ao analisar documento: {e}")
        return "[Documento não pôde ser analisado]"


def _extract_text_from_content(content, msg_type: str) -> tuple[str, str]:
    """Extrai texto do conteúdo baseado no tipo."""

    # Texto simples (string)
    if isinstance(content, str):
        return content, msg_type

    # Conteúdo estruturado (dict)
    if isinstance(content, dict):
        text = content.get("text", "")
        if text:
            return text, msg_type

        # Detecta PTT (áudio de voz)
        if content.get("PTT"):
            return "[ÁUDIO_PTT]", "audioMessage"

    # Tipos de mídia
    type_labels = {
        "imageMessage": "IMAGEM",
        "audioMessage": "ÁUDIO",
        "videoMessage": "VÍDEO",
        "documentMessage": "DOCUMENTO",
        "locationMessage": "LOCALIZAÇÃO",
        "contactMessage": "CONTATO",
        "stickerMessage": "STICKER",
        "reactionMessage": "REAÇÃO",
    }

    label = type_labels.get(msg_type, msg_type.upper())
    return f"[{label}]", msg_type


def _get_message_type_category(msg_type: str) -> str:
    """Categoriza o tipo de mensagem."""
    categories = {
        "Conversation": "text",
        "ExtendedTextMessage": "text",
        "imageMessage": "image",
        "ImageMessage": "image",
        "audioMessage": "audio",
        "AudioMessage": "audio",
        "videoMessage": "video",
        "documentMessage": "document",
        "DocumentMessage": "document",
        "locationMessage": "location",
        "contactMessage": "contact",
        "stickerMessage": "sticker",
        "reactionMessage": "reaction",
    }
    return categories.get(msg_type, "unknown")


def _should_process_message(msg_type: str) -> bool:
    """Define quais tipos devem ser processados pelo agent."""
    processable = [
        "Conversation",
        "ExtendedTextMessage",
        "audioMessage",
        "AudioMessage",
        "imageMessage",
        "ImageMessage",
        "documentMessage",
        "DocumentMessage",
    ]
    return msg_type in processable


async def handle_message(message_data: dict) -> MessageInfo:
    """
    Processa uma mensagem e retorna informações estruturadas.

    Args:
        message_data: Dicionário com dados da mensagem do webhook

    Returns:
        MessageInfo com texto, tipo, caminho da mídia e se deve processar
    """
    try:
        content = message_data.get("content")
        msg_type = message_data.get("messageType", "unknown")
        message_id = message_data.get("id", "")

        # Extrai texto inicial
        text, detected_type = _extract_text_from_content(content, msg_type)

        # Categoriza
        category = _get_message_type_category(msg_type)

        # Verifica se deve processar
        should_process = _should_process_message(msg_type) and bool(text.strip())

        # --- NOVO: Extração de Mensagem Citada (Reply) ---
        quoted_text = ""
        try:
            # Caminho no JSON: content -> contextInfo -> quotedMessage -> conversation
            ctx_info = (
                content.get("contextInfo", {}) if isinstance(content, dict) else {}
            )
            quoted_msg = ctx_info.get("quotedMessage", {})

            # Tenta pegar texto da conversa citada
            q_text = quoted_msg.get("conversation") or quoted_msg.get(
                "extendedTextMessage", {}
            ).get("text")

            if q_text:
                quoted_text = f' [Respondendo a: "{q_text[:200]}..."]'  # Limita tamanho para não poluir
        except Exception:
            pass  # Ignora falhas na extração de quote

        if quoted_text and text:
            text += quoted_text
            logger.info(f"✅ Contexto de resposta adicionado: {quoted_text}")
        # ----------------------------------------------------

        # Processa mídia
        media_path = None
        if category in ["image", "audio", "video", "document"]:
            # ← NOVO: Chamada unificada
            extracted_text, media_path = await download_and_process_media(
                message_id, category, message_data
            )

            if extracted_text:
                text = extracted_text
                should_process = True
            else:
                text = f"[{category.upper()} não pôde ser processado]"
                should_process = False

        logger.info(
            f"✅ Mensagem processada: "
            f"type={msg_type}, category={category}, "
            f"text={text[:60]}..., process={should_process}"
        )

        return MessageInfo(
            text=text,
            message_type=msg_type,
            media_path=media_path,
            should_process=should_process,
        )

    except Exception as e:
        logger.error(f"❌ Erro ao processar mensagem: {e}", exc_info=True)
        return MessageInfo(
            text="", message_type="error", media_path=None, should_process=False
        )
