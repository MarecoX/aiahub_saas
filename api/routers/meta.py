from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import (
    PlainTextResponse,
    FileResponse,
    JSONResponse,
)
import logging
import os

from scripts.meta.meta_manager import verify_webhook_challenge, process_incoming_webhook
from scripts.meta.meta_client import MetaClient
from scripts.meta.meta_oauth import exchange_code_for_token
from scripts.shared.saas_db import (
    get_client_config,
    get_client_config_by_id,
    update_tools_config_db,
    get_connection,
    upsert_provider_config,
)
from api.models import OAuthCode
from api.services.meta_service import MetaService

router = APIRouter(tags=["Meta WhatsApp Official"])
logger = logging.getLogger(__name__)

# Instancia o serviço
meta_service = MetaService()


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
    waba = tools.get("whatsapp", {})

    # Check for both formats: old 'whatsapp_official' and new 'whatsapp'
    if not waba.get("mode") == "official" and not tools.get(
        "whatsapp_official", {}
    ).get("active"):
        # Try legacy key
        waba = tools.get("whatsapp_official", {})

    if not waba.get("active") and not waba.get("token"):
        raise HTTPException(status_code=400, detail="Integração Meta não ativa")

    try:
        meta = MetaClient(
            waba.get("token") or waba.get("access_token"), waba.get("phone_id")
        )
        templates = await meta.get_templates(waba.get("waba_id"))  # Requer WABA ID
        return templates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signup-static")
async def get_signup_static(
    app_id: str = None, config_id: str = None, version: str = None, token: str = None
):
    """
    Serve o arquivo estático com Headers Corretos + Cache Control.
    """
    file_path = "static/facebook-embedded-signup.html"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Static File not found")

    return FileResponse(
        file_path,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.post("/oauth_exchange")
async def meta_oauth_exchange(payload: OAuthCode):
    """
    Recebe o code da Meta (Client Side) + Client ID (UUID).
    Troca por Access Token e Salva no Banco.
    Recebe também waba_id e phone_id para salvar.
    """
    logger.info(f"🔄 [Meta OAuth] Iniciando troca para Client ID: {payload.client_id}")

    # 1. Busca configurações do cliente usando o ID (UUID)
    client_config = get_client_config_by_id(payload.client_id)

    if not client_config:
        logger.error(f"❌ Cliente não encontrado para o ID: {payload.client_id}")
        # Debug: List all clients or count them to see if DB is empty
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) as c FROM clients")
                    cnt = cur.fetchone()["c"]
                    logger.error(f"🔍 Debug: Total de clientes no banco: {cnt}")
        except Exception as db_e:
            logger.error(f"🔍 Debug: Erro ao contar clientes no banco: {db_e}")

        return JSONResponse(
            content={
                "status": "error",
                "message": f"Cliente não encontrado (ID: {payload.client_id})",
            },
            status_code=404,
        )

    logger.info(
        f"✅ Cliente identificado: {client_config.get('name')} (ID: {client_config.get('id')})"
    )

    # 2. Troca Code por Token da Meta
    token_data = exchange_code_for_token(payload.code)

    if not token_data or "access_token" not in token_data:
        raise HTTPException(
            status_code=400, detail="Falha ao obter Access Token da Meta"
        )

    long_lived_token = token_data.get("access_token")

    # 3. Salva no Banco de Dados (tools_config -> whatsapp)
    waba_id = payload.waba_id
    phone_id = payload.phone_id

    # Recupera config atual
    tools_config = client_config.get("tools_config") or {}

    # Atualiza apenas a sessão do WhatsApp
    tools_config["whatsapp"] = {
        "active": True,
        "mode": "official",
        "access_token": long_lived_token,
        "waba_id": waba_id,
        "phone_id": phone_id,
        "app_id": os.getenv("META_APP_ID"),
    }

    # Persiste
    success = update_tools_config_db(client_config["id"], tools_config)

    if success:
        logger.info(f"💾 Credenciais Meta salvas para cliente {client_config['id']}")

        # 3.5 Salvar em client_providers (nova estrutura)
        try:
            upsert_provider_config(
                client_id=str(client_config["id"]),
                provider_type="meta",
                config={
                    "access_token": long_lived_token,
                    "waba_id": waba_id,
                    "phone_id": phone_id,
                    "app_id": os.getenv("META_APP_ID"),
                    "active": True,
                },
                is_active=True,
                is_default=True,
            )
            logger.info(f"✅ Config Meta salva em client_providers")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao salvar em client_providers: {e}")

        # 3.6 Atualiza campo whatsapp_provider para 'meta'
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET whatsapp_provider = 'meta' WHERE id = %s",
                        (client_config["id"],),
                    )
            logger.info(f"✅ whatsapp_provider atualizado para 'meta'")
        except Exception as e:
            logger.warning(f"⚠️ Falha ao atualizar whatsapp_provider: {e}")

        # 4. Auto-Subscribe App to WABA (Webhooks)
        try:
            meta_client = MetaClient(long_lived_token, phone_id)
            subscribed = await meta_client.subscribe_app_to_waba(waba_id)
            if subscribed:
                logger.info(f"✅ Webhooks ativados automaticamente para WABA {waba_id}")
            else:
                logger.warning(
                    f"⚠️ Falha ao ativar webhooks automaticamente para WABA {waba_id}"
                )
        except Exception as e:
            logger.error(f"⚠️ Erro ao tentar auto-subscrição: {e}")

        return {"status": "success", "message": "Conectado com sucesso!"}
    else:
        logger.error(f"❌ Falha ao salvar DB para cliente {client_config['id']}")
        raise HTTPException(
            status_code=500, detail="Erro ao salvar credenciais no banco"
        )
