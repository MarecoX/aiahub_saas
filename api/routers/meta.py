from fastapi import APIRouter, Request, Query, HTTPException, Depends
from fastapi.responses import PlainTextResponse
import logging

from scripts.meta.meta_manager import verify_webhook_challenge, process_incoming_webhook
from scripts.meta.meta_client import MetaClient
from scripts.shared.saas_db import get_client_config

router = APIRouter(prefix="/api/v1/meta", tags=["Meta WhatsApp Official"])
logger = logging.getLogger(__name__)


@router.get("/webhook/{client_verify_token}")
async def meta_webhook_challenge(
    client_verify_token: str,
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
):
    """
    Endpoint para validação do domínio pela Meta (Handshake).
    A Meta exige que isso retorne o hub.challenge em *plaintext*.
    """
    # Em produção real, o 'client_verify_token' na URL pode ser ignorado
    # se usarmos um token fixo global, ou validado.
    # Neste design, o verify_token é fixo no código do manager.

    challenge = verify_webhook_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge:
        # Retorna PlainText como exigido exatamento pela Meta
        return PlainTextResponse(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification Failed")


@router.post("/webhook/{client_verify_token}")
async def meta_webhook_event(client_verify_token: str, request: Request):
    """
    Recebe eventos de mensagem (POST).
    """
    # A validação de assinatura X-Hub-Signature-256 deveria ocorrer aqui para segurança máxima.
    # Por enquanto, confiamos no payload struct.

    try:
        data = await request.json()
        logger.info(f"🔔 WEBHOOK POST RECEBIDO: {data}")
        # Processa assincronamente (Fire-and-forget ou await dependendo da carga)
        await process_incoming_webhook(data)

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro no webhook POST: {e}")
        # Sempre retorne 200 para a Meta não ficar reenviando
        return {"status": "error", "detail": str(e)}


@router.get("/templates")
async def list_templates(client_token: str):
    """
    Lista templates aprovados para um cliente.
    """
    client = get_client_config(client_token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    tools = client.get("tools_config", {})
    waba = tools.get("whatsapp_official", {})

    if not waba.get("active"):
        raise HTTPException(status_code=400, detail="Integração Meta não ativa")

    try:
        meta = MetaClient(waba["token"], waba["phone_id"])
        templates = await meta.get_templates(waba["waba_id"])  # Requer WABA ID
        return templates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
