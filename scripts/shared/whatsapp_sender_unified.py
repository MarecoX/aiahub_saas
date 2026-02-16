"""
Camada de abstração unificada para envio de mensagens WhatsApp.

Centraliza o envio de mensagens independente do provider (Uazapi, LancePilot, Meta).
Usa `client_providers` como single source of truth para credenciais.

Uso:
    from scripts.shared.whatsapp_sender_unified import send_text, resolve_provider

    # Envia para qualquer provider configurado
    result = await send_text(client_id="abc-123", to="5511999999999", text="Olá!")

    # Ou resolve manualmente
    provider_type, config = resolve_provider(client_id, client_config)
"""

import httpx
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def resolve_provider(client_id: str, client_config: dict = None) -> Tuple[str, dict]:
    """
    Resolve o provider e credenciais para um cliente.

    Ordem de prioridade:
        1. client_config.whatsapp_provider -> client_providers
        2. client_providers.is_default = true
        3. client_providers provider_type='uazapi' (legacy)
        4. Fallback: colunas legadas da tabela clients

    Returns:
        (provider_type, config) ex: ("uazapi", {"url": "...", "token": "..."})
    """
    from scripts.shared.saas_db import get_provider_config, get_default_provider

    provider_type = None
    config = {}

    if not client_id:
        return ("uazapi", _fallback_env())

    try:
        # 1. Provider explícito configurado no cliente
        if client_config:
            wp = client_config.get("whatsapp_provider", "")
            if wp:
                cfg = get_provider_config(client_id, wp)
                if cfg and _has_credentials(wp, cfg):
                    logger.info(f"🔗 Provider resolvido via whatsapp_provider: {wp}")
                    return (wp, cfg)

        # 2. Provider default na tabela client_providers
        def_type, def_cfg = get_default_provider(client_id)
        if def_type and def_cfg and _has_credentials(def_type, def_cfg):
            logger.info(f"🔗 Provider resolvido via default: {def_type}")
            return (def_type, def_cfg)

        # 3. Fallback: buscar uazapi explicitamente
        uaz_cfg = get_provider_config(client_id, "uazapi")
        if uaz_cfg and uaz_cfg.get("url") and uaz_cfg.get("token"):
            logger.info("🔗 Provider resolvido via fallback uazapi")
            return ("uazapi", uaz_cfg)

        # 4. Fallback: colunas legadas da tabela clients
        if client_config:
            legacy_url = client_config.get("api_url", "")
            legacy_token = client_config.get("token", "")
            if legacy_url and legacy_token:
                logger.info("🔗 Provider resolvido via colunas legadas (clients table)")
                return ("uazapi", {"url": legacy_url, "token": legacy_token})

            # LancePilot legacy
            lp_token = client_config.get("lancepilot_token", "")
            lp_workspace = client_config.get("lancepilot_workspace_id", "")
            if lp_token and lp_workspace:
                logger.info("🔗 Provider resolvido via colunas legadas lancepilot")
                return ("lancepilot", {"token": lp_token, "workspace_id": lp_workspace})

        # 5. Fallback final: env vars
        return ("uazapi", _fallback_env())

    except Exception as e:
        logger.error(f"❌ Erro ao resolver provider: {e}")
        return ("uazapi", _fallback_env())


def _has_credentials(provider_type: str, config: dict) -> bool:
    """Verifica se o config tem credenciais mínimas para o provider."""
    if provider_type == "uazapi":
        return bool(config.get("url") and config.get("token"))
    elif provider_type == "lancepilot":
        return bool(config.get("token") and config.get("workspace_id"))
    elif provider_type == "meta":
        return bool(
            (config.get("access_token") or config.get("token"))
            and config.get("phone_id")
        )
    return False


def _fallback_env() -> dict:
    """Credenciais via env vars (fallback final)."""
    return {
        "url": os.getenv("UAZAPI_URL", ""),
        "token": os.getenv("UAZAPI_TOKEN", ""),
    }


async def send_text(
    client_id: str,
    to: str,
    text: str,
    client_config: dict = None,
    provider_type: str = None,
    provider_config: dict = None,
) -> dict:
    """
    Envia mensagem de texto via WhatsApp usando o provider configurado.

    Args:
        client_id: UUID do cliente
        to: Número de destino (com DDI, ex: "5511999999999" ou "5511999999999@s.whatsapp.net")
        text: Texto da mensagem
        client_config: Config completa do cliente (opcional, evita query extra)
        provider_type: Força um provider específico (opcional)
        provider_config: Força config específica (opcional)

    Returns:
        dict com resultado do envio
    """
    # Resolve provider se não fornecido
    if not provider_type or not provider_config:
        provider_type, provider_config = resolve_provider(client_id, client_config)

    # Limpa número (remove @s.whatsapp.net se presente)
    to_clean = str(to).split("@")[0] if "@" in str(to) else str(to)

    logger.info(f"📤 Enviando via {provider_type} para {to_clean[:6]}...")

    if provider_type == "uazapi":
        return await _send_uazapi(provider_config, to_clean, text)
    elif provider_type == "lancepilot":
        return await _send_lancepilot(provider_config, to_clean, text)
    elif provider_type == "meta":
        return await _send_meta(provider_config, to_clean, text)
    else:
        logger.error(f"❌ Provider desconhecido: {provider_type}")
        return {"error": f"Provider desconhecido: {provider_type}"}


async def _send_uazapi(config: dict, to: str, text: str) -> dict:
    """Envia via Uazapi."""
    url = config.get("url", "").rstrip("/")
    token = config.get("token", "")

    if not url or not token:
        return {"error": "Credenciais Uazapi ausentes (url/token)"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/send/text",
            json={"number": to, "text": text},
            headers={"token": token},
            timeout=30.0,
        )
        if resp.status_code in [200, 201]:
            logger.info(f"✅ [Uazapi] Mensagem enviada para {to[:6]}...")
            return {"status": "sent", "provider": "uazapi", "response": resp.json()}
        else:
            logger.error(f"❌ [Uazapi] Erro: {resp.status_code} - {resp.text}")
            return {"error": f"Uazapi HTTP {resp.status_code}", "body": resp.text}


async def _send_lancepilot(config: dict, to: str, text: str) -> dict:
    """Envia via LancePilot."""
    token = config.get("token", "")
    workspace_id = config.get("workspace_id", "")

    if not token or not workspace_id:
        return {"error": "Credenciais LancePilot ausentes (token/workspace_id)"}

    lp_base = "https://lancepilot.com/api/v3"
    lp_url = f"{lp_base}/workspaces/{workspace_id}/contacts/number/{to}/messages/text"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            lp_url,
            json={"text": {"body": text}},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=15.0,
        )
        if resp.status_code in [200, 201]:
            logger.info(f"✅ [LancePilot] Mensagem enviada para {to[:6]}...")
            return {"status": "sent", "provider": "lancepilot", "response": resp.json()}
        else:
            logger.error(f"❌ [LancePilot] Erro: {resp.status_code} - {resp.text}")
            return {"error": f"LancePilot HTTP {resp.status_code}", "body": resp.text}


async def _send_meta(config: dict, to: str, text: str) -> dict:
    """Envia via Meta (WhatsApp Business API Oficial)."""
    access_token = config.get("access_token") or config.get("token", "")
    phone_id = config.get("phone_id", "")

    if not access_token or not phone_id:
        return {"error": "Credenciais Meta ausentes (access_token/phone_id)"}

    meta_url = f"https://graph.facebook.com/v23.0/{phone_id}/messages"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            meta_url,
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
        if resp.status_code in [200, 201]:
            logger.info(f"✅ [Meta] Mensagem enviada para {to[:6]}...")
            return {"status": "sent", "provider": "meta", "response": resp.json()}
        else:
            logger.error(f"❌ [Meta] Erro: {resp.status_code} - {resp.text}")
            return {"error": f"Meta HTTP {resp.status_code}", "body": resp.text}
