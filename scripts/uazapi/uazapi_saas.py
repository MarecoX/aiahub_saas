import httpx
import os
import logging

logger = logging.getLogger(__name__)

# Configuração Padrão (Fallback)
DEFAULT_UAZAPI_URL = os.getenv("UAZAPI_URL")
DEFAULT_UAZAPI_KEY = os.getenv("UAZAPI_KEY")


async def send_whatsapp_message(
    number: str, text: str, api_key: str = None, base_url: str = None
) -> dict:
    """
    Envia mensagem via WhatsApp de forma assíncrona (Versão SaaS).
    Aceita api_key e base_url dinâmicos por cliente.
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY

    if not url or not token:
        logger.error("❌ ERRO: URL ou Token do Uazapi não definidos!")
        raise ValueError("Uazapi Credentials Missing")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/send/text",
                json={"number": number, "text": text},
                headers={"token": f"{token}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            logger.info(f"✅ [SaaS] Mensagem enviada para {number}")
            return resp.json()

    except httpx.HTTPError as exc:
        logger.error(f"❌ Erro HTTP Uazapi: {exc.response.status_code}")
        raise RuntimeError(f"Erro ao enviar: {exc}") from exc
    except Exception as exc:
        logger.error(f"❌ Erro Genérico Uazapi: {exc}")
        raise RuntimeError(f"Erro ao enviar: {exc}") from exc


async def send_whatsapp_audio(
    number: str, audio_url: str, api_key: str = None, base_url: str = None
) -> dict:
    """
    Envia áudio via WhatsApp (por URL).
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY

    if not url or not token:
        logger.error("❌ ERRO: URL ou Token do Uazapi não definidos!")
        raise ValueError("Uazapi Credentials Missing")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/send/media",
                json={"number": number, "type": "audio", "file": audio_url},
                headers={"token": f"{token}"},
                timeout=15.0,
            )
            resp.raise_for_status()
            logger.info(f"🔊 [SaaS] Áudio enviado para {number}: {audio_url[:50]}...")
            return resp.json()

    except httpx.HTTPError as exc:
        logger.error(f"❌ Erro HTTP Uazapi (Audio): {exc}")
        raise RuntimeError(f"Erro ao enviar áudio: {exc}") from exc
    except Exception as exc:
        logger.error(f"❌ Erro Genérico Uazapi (Audio): {exc}")
        raise RuntimeError(f"Erro ao enviar áudio: {exc}") from exc


async def send_whatsapp_media(
    number: str,
    media_url: str,
    media_type: str = "image",
    caption: str = "",
    doc_name: str = None,
    api_key: str = None,
    base_url: str = None,
) -> dict:
    """
    Envia mídia genérica (imagem, vídeo, documento) via WhatsApp.
    API Specs:
      - file: URL or base64 (required)
      - text: Caption (optional)
      - docName: Filename for docs (optional)
      - type: image, video, document
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY

    if not url or not token:
        logger.error("❌ ERRO: URL ou Token do Uazapi não definidos!")
        raise ValueError("Uazapi Credentials Missing")

    # Mapeia tipos
    valid_types = [
        "image",
        "video",
        "document",
        "audio",
        "myaudio",
        "ptt",
        "ptv",
        "sticker",
    ]
    if media_type not in valid_types:
        if "pdf" in media_url or "doc" in media_url or "xls" in media_url:
            media_type = "document"
        else:
            media_type = "image"

    try:
        async with httpx.AsyncClient() as client:
            # Payload minimalista conforme documentação
            payload = {"number": number, "type": media_type, "file": media_url}

            if caption:
                payload["text"] = caption

            # Adiciona docName APENAS se for documento
            if media_type == "document":
                payload["docName"] = doc_name or "documento.pdf"

            endpoint = f"{url}/send/media"

            resp = await client.post(
                endpoint,
                json=payload,
                headers={"token": f"{token}"},
                timeout=60.0,
            )

            if resp.status_code >= 400:
                logger.error(f"❌ Erro API Uazapi: {resp.status_code} - {resp.text}")

            resp.raise_for_status()
            logger.info(f"🖼️ [SaaS] Mídia ({media_type}) enviada para {number}")
            return resp.json()

    except httpx.HTTPError as exc:
        logger.error(f"❌ Erro HTTP Uazapi (Media): {exc}")
        raise RuntimeError(f"Erro ao enviar mídia: {exc}") from exc
    except Exception as exc:
        logger.error(f"❌ Erro Genérico Uazapi (Media): {exc}")
        raise RuntimeError(f"Erro ao enviar mídia: {exc}") from exc


async def connect_instance(
    phone: str = None, api_key: str = None, base_url: str = None
) -> dict:
    """
    Inicia conexão (QR Code ou Pairing Code).
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY
    if not url or not token:
        return {"error": "Credenciais não definidas"}

    payload = {}
    if phone:
        payload["phone"] = phone

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/instance/connect",
                json=payload,
                headers={"token": f"{token}"},
                timeout=15.0,
            )
            # Retorna o JSON cru (pode conter base64 ou pairing code)
            return resp.json()
    except Exception as e:
        logger.error(f"Erro Connect Instance: {e}")
        return {"error": str(e)}


async def get_instance_status(api_key: str = None, base_url: str = None) -> dict:
    """
    Verifica status da instância.
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY
    if not url or not token:
        return {"error": "Credenciais não definidas"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}/instance/status", headers={"token": f"{token}"}, timeout=5.0
            )
            return resp.json()
    except Exception as e:
        logger.error(f"Erro Status Instance: {e}")
        return {"error": str(e)}


async def disconnect_instance(api_key: str = None, base_url: str = None) -> dict:
    """
    Desconecta a instância.
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY
    if not url or not token:
        return {"error": "Credenciais não definidas"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{url}/instance/logout", headers={"token": f"{token}"}, timeout=10.0
            )
            return resp.json()
    except Exception as e:
        logger.error(f"Erro Logout Instance: {e}")
        return {"error": str(e)}
