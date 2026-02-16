from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging

from api.models import ProviderConfigCreate, ProviderConfigUpdate, ProviderConfigResponse
from api.dependencies import verify_token
from saas_db import (
    get_client_config,
    get_provider_config,
    list_client_providers,
    upsert_provider_config,
)

router = APIRouter(
    tags=["Providers"],
    dependencies=[Depends(verify_token)],
)

logger = logging.getLogger("API_Providers")


def _get_client_or_404(token: str) -> dict:
    """Busca cliente pelo token ou retorna 404."""
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return client


@router.get("/", response_model=List[ProviderConfigResponse])
def list_providers(token: str):
    """Lista todos os providers configurados para um cliente."""
    client = _get_client_or_404(token)
    providers = list_client_providers(str(client["id"]))
    return [
        ProviderConfigResponse(
            id=str(p["id"]),
            provider_type=p["provider_type"],
            instance_name=p["instance_name"] or "Principal",
            config=p["config"] or {},
            is_active=p["is_active"],
            is_default=p["is_default"],
        )
        for p in providers
    ]


@router.get("/{provider_type}", response_model=ProviderConfigResponse)
def get_provider(token: str, provider_type: str):
    """Busca configuração de um provider específico."""
    client = _get_client_or_404(token)
    config = get_provider_config(str(client["id"]), provider_type)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_type}' não configurado para este cliente",
        )
    # get_provider_config retorna só o config dict, precisamos buscar o registro completo
    providers = list_client_providers(str(client["id"]))
    for p in providers:
        if p["provider_type"] == provider_type:
            return ProviderConfigResponse(
                id=str(p["id"]),
                provider_type=p["provider_type"],
                instance_name=p["instance_name"] or "Principal",
                config=p["config"] or {},
                is_active=p["is_active"],
                is_default=p["is_default"],
            )
    raise HTTPException(status_code=404, detail=f"Provider '{provider_type}' não encontrado")


@router.post("/", status_code=201)
def create_provider(token: str, provider: ProviderConfigCreate):
    """
    Cria ou atualiza um provider para o cliente.

    Configs esperadas por provider_type:
    - **uazapi**: `{"url": "https://...", "token": "abc123"}`
    - **meta**: `{"access_token": "EAA...", "phone_id": "123...", "waba_id": "..."}`
    - **lancepilot**: `{"token": "...", "workspace_id": "..."}`
    """
    client = _get_client_or_404(token)
    client_id = str(client["id"])

    # Valida campos mínimos por provider
    _validate_provider_config(provider.provider_type, provider.config)

    provider_id = upsert_provider_config(
        client_id=client_id,
        provider_type=provider.provider_type,
        config=provider.config,
        instance_name=provider.instance_name,
        is_active=True,
        is_default=provider.is_default,
    )

    if not provider_id:
        raise HTTPException(status_code=500, detail="Erro ao salvar provider")

    return {
        "id": provider_id,
        "message": f"Provider {provider.provider_type} configurado com sucesso",
    }


@router.put("/{provider_type}")
def update_provider(token: str, provider_type: str, update: ProviderConfigUpdate):
    """Atualiza configuração de um provider existente."""
    client = _get_client_or_404(token)
    client_id = str(client["id"])

    existing = get_provider_config(client_id, provider_type)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_type}' não encontrado. Use POST para criar.",
        )

    # Merge config
    new_config = existing.copy()
    if update.config:
        new_config.update(update.config)

    provider_id = upsert_provider_config(
        client_id=client_id,
        provider_type=provider_type,
        config=new_config,
        instance_name=update.instance_name or "Principal",
        is_active=update.is_active if update.is_active is not None else True,
        is_default=update.is_default if update.is_default is not None else False,
    )

    if not provider_id:
        raise HTTPException(status_code=500, detail="Erro ao atualizar provider")

    return {"message": f"Provider {provider_type} atualizado"}


@router.post("/{provider_type}/test")
def test_provider(token: str, provider_type: str):
    """
    Testa a conexão com um provider configurado.
    Verifica se as credenciais são válidas sem enviar mensagens.
    """
    client = _get_client_or_404(token)
    config = get_provider_config(str(client["id"]), provider_type)
    if not config:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_type}' não configurado")

    import httpx

    try:
        if provider_type == "uazapi":
            url = config.get("url", "").rstrip("/")
            tkn = config.get("token", "")
            resp = httpx.get(
                f"{url}/instance/status",
                headers={"token": tkn},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return {"status": "connected", "provider": "uazapi", "details": resp.json()}
            return {"status": "error", "provider": "uazapi", "http_code": resp.status_code}

        elif provider_type == "meta":
            access_token = config.get("access_token") or config.get("token", "")
            phone_id = config.get("phone_id", "")
            resp = httpx.get(
                f"https://graph.facebook.com/v23.0/{phone_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return {"status": "connected", "provider": "meta", "details": resp.json()}
            return {"status": "error", "provider": "meta", "http_code": resp.status_code}

        elif provider_type == "lancepilot":
            tkn = config.get("token", "")
            resp = httpx.get(
                "https://lancepilot.com/api/v3/workspaces",
                headers={"Authorization": f"Bearer {tkn}", "Accept": "application/json"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return {"status": "connected", "provider": "lancepilot", "workspaces": len(resp.json().get("data", []))}
            return {"status": "error", "provider": "lancepilot", "http_code": resp.status_code}

        else:
            raise HTTPException(status_code=400, detail=f"Provider '{provider_type}' não suportado para teste")

    except httpx.TimeoutException:
        return {"status": "timeout", "provider": provider_type}
    except Exception as e:
        return {"status": "error", "provider": provider_type, "detail": str(e)}


def _validate_provider_config(provider_type: str, config: dict):
    """Valida campos obrigatórios por tipo de provider."""
    if provider_type == "uazapi":
        if not config.get("url") or not config.get("token"):
            raise HTTPException(
                status_code=422,
                detail="Uazapi requer 'url' e 'token' no config. Ex: {\"url\": \"https://...\", \"token\": \"abc\"}",
            )
    elif provider_type == "meta":
        if not (config.get("access_token") or config.get("token")):
            raise HTTPException(
                status_code=422,
                detail="Meta requer 'access_token' (ou 'token') no config",
            )
        if not config.get("phone_id"):
            raise HTTPException(
                status_code=422,
                detail="Meta requer 'phone_id' no config",
            )
    elif provider_type == "lancepilot":
        if not config.get("token") or not config.get("workspace_id"):
            raise HTTPException(
                status_code=422,
                detail="LancePilot requer 'token' e 'workspace_id' no config",
            )
