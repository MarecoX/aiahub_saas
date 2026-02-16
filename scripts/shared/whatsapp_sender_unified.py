"""
Resolução centralizada de provider WhatsApp.

Usa `client_providers` como single source of truth para credenciais.
Cada worker/sender continua usando seu próprio mecanismo de envio.

Uso:
    from scripts.shared.whatsapp_sender_unified import resolve_provider

    provider_type, config = resolve_provider(client_id, client_config)
    # provider_type: "uazapi" | "lancepilot" | "meta"
    # config: {"url": "...", "token": "..."} (varia por provider)
"""

import logging
import os
from typing import Tuple

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
