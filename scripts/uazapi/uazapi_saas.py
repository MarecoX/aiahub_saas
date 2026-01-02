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

async def connect_instance(phone: str = None, api_key: str = None, base_url: str = None) -> dict:
    """
    Inicia conexão (QR Code ou Pairing Code).
    """
    url = base_url or DEFAULT_UAZAPI_URL
    token = api_key or DEFAULT_UAZAPI_KEY
    if not url or not token: return {"error": "Credenciais não definidas"}

    payload = {}
    if phone: payload["phone"] = phone
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}/instance/connect",
                json=payload,
                headers={"token": f"{token}"},
                timeout=15.0 
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
    if not url or not token: return {"error": "Credenciais não definidas"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}/instance/status",
                headers={"token": f"{token}"},
                timeout=5.0
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
    if not url or not token: return {"error": "Credenciais não definidas"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{url}/instance/logout",
                headers={"token": f"{token}"},
                timeout=10.0
            )
            return resp.json()
    except Exception as e:
        logger.error(f"Erro Logout Instance: {e}")
        return {"error": str(e)}
