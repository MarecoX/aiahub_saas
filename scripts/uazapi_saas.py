import httpx
import os
import logging

logger = logging.getLogger(__name__)

# Configuração Padrão (Fallback)
DEFAULT_UAZAPI_URL = os.getenv("UAZAPI_URL")
DEFAULT_UAZAPI_KEY = os.getenv("UAZAPI_KEY")

async def send_whatsapp_message(number: str, text: str, api_key: str = None, base_url: str = None) -> dict:
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
                json={
                    "number": number,
                    "text": text
                },
                headers={"token": f"{token}"},
                timeout=5.0
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
