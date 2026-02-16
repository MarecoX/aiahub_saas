from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File
from typing import List, Dict, Any
import shutil
import os
import logging
from api.models import ClientCreate, ClientUpdate, ToolsConfigUpdate
from api.dependencies import verify_token
from saas_db import (
    create_client_db,
    update_client_db,
    get_client_config,
    get_all_clients_db,
    update_tools_config_db,
    delete_client_db,
    upsert_provider_config,
)
from api.services.gemini_service import service as gemini_service


router = APIRouter(
    tags=["Clients"],  # Standardized Tag
    dependencies=[Depends(verify_token)],
)

logger = logging.getLogger("API_Clients")


@router.get("/", response_model=List[Dict[str, Any]])
def list_clients():
    """Lista todos os clientes cadastrados."""
    clients = get_all_clients_db()
    return clients


@router.post("/", status_code=201)
def create_client(client: ClientCreate, x_admin_user: str = Header("admin")):
    """Cria um novo cliente."""
    # 1. Verifica duplicidade
    existing = get_client_config(client.token)
    if existing:
        raise HTTPException(status_code=400, detail="Cliente já existe com este token.")

    # 2. Auto-Criação do Gemini Store (RAG)
    store_id = client.gemini_store_id
    if not store_id:
        logger.info(f"Criando Gemini Store automático para: {client.name}")
        store, err = gemini_service.get_or_create_vector_store(
            f"Store-{client.name.replace(' ', '-')}"
        )
        if store:
            store_id = store.name
            logger.info(f"✅ Store criado: {store_id}")
        else:
            logger.warning(f"⚠️ Falha ao criar Store automático: {err}")

    # 3. Cria no Banco
    from scripts.shared.auth_utils import hash_password

    # Gera senha temporária que deverá ser alterada
    temp_password = f"temp_{client.name.lower().replace(' ', '')}"
    pwd_hash = hash_password(temp_password)

    new_id = create_client_db(
        name=client.name,
        token=client.token,
        prompt=client.system_prompt,
        username=f"{client.name.lower().replace(' ', '')}_user",  # Auto-gen username
        password_hash=pwd_hash,
        api_url=client.api_url,
        timeout=client.human_attendant_timeout,
        store_id=store_id,
        whatsapp_provider=client.whatsapp_provider or "none",
    )

    if not new_id:
        raise HTTPException(
            status_code=400,
            detail="Erro ao criar cliente (Possível duplicidade de NOME ou USERNAME). Verifique se já não existe um cliente com este nome.",
        )

    # 4. Cria provider em client_providers se fornecido
    provider_id = None
    if client.provider_config:
        provider_id = upsert_provider_config(
            client_id=str(new_id),
            provider_type=client.provider_config.provider_type,
            config=client.provider_config.config,
            instance_name=client.provider_config.instance_name,
            is_active=True,
            is_default=True,
        )
        if provider_id:
            logger.info(f"✅ Provider {client.provider_config.provider_type} criado para cliente {new_id}")
        else:
            logger.warning(f"⚠️ Cliente criado mas falha ao criar provider")

    return {
        "id": new_id,
        "message": "Cliente criado com sucesso",
        "gemini_store_id": store_id,
        "temp_password": temp_password,
        "provider_id": provider_id,
    }


@router.delete("/{token}", status_code=204)
def delete_client(token: str, x_admin_user: str = Header("admin")):
    """Remove um cliente e seus dados."""
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # DB Delete logic would go here. Importing/Checking if db function exists.
    # Assuming delete_client_db exists or we need to add it to saas_db.
    # Since we can't edit saas_db easily in one go, checking imports first.
    # Actually, let's implement the SQL directly here or add to saas_db.
    # We will assume saas_db needs update.
    # For now, let's fail if not implemented.
    success = delete_client_db(client["id"])
    if not success:
        raise HTTPException(status_code=500, detail="Erro ao deletar cliente")
    return


@router.get("/{token}")
def get_client(token: str):
    """Busca configurações de um cliente específico pelo Token."""
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return client


@router.put("/{token}")
def update_client(token: str, update_data: ClientUpdate):
    """Atualiza dados básicos do cliente."""
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Converte Pydantic para dict sem Nones
    data_dict = update_data.model_dump(exclude_unset=True)

    success = update_client_db(client["id"], data_dict)
    if not success:
        raise HTTPException(status_code=500, detail="Falha ao atualizar banco de dados")

    return {"message": "Cliente atualizado"}


@router.get("/tools/catalog", response_model=Dict[str, Any])
def list_tools_catalog(business_type: str = "generic"):
    """
    Retorna o catálogo completo de tools disponíveis, filtrado por business_type.

    Cada tool inclui: label, category, config_fields (campos de credencial/config),
    credential_source, provider_badge, etc.

    Query params:
        business_type: Filtra tools aplicáveis ao tipo de negócio (default: generic)
    """
    from scripts.shared.tool_registry import TOOL_REGISTRY, get_tools_for_business_type, BUSINESS_TYPES

    filtered = get_tools_for_business_type(business_type)

    return {
        "business_types": BUSINESS_TYPES,
        "current_filter": business_type,
        "tools": {
            tool_id: {
                "label": meta.get("label", tool_id),
                "category": meta.get("category", "generic"),
                "applicable_to": meta.get("applicable_to", ["*"]),
                "config_fields": meta.get("config_fields", {}),
                "has_instructions": meta.get("has_instructions", False),
                "credential_source": meta.get("credential_source"),
                "provider_badge": meta.get("provider_badge", ""),
                "ui_help": meta.get("ui_help", ""),
                "ui_caption": meta.get("ui_caption", ""),
                "instructions_placeholder": meta.get("instructions_placeholder", ""),
            }
            for tool_id, meta in filtered.items()
        },
        "total": len(filtered),
    }


@router.get("/{token}/tools")
def get_client_tools(token: str):
    """
    Retorna as tools configuradas para um cliente, com o catálogo mesclado.

    Para cada tool do catálogo, retorna se está ativa e sua config atual.
    """
    from scripts.shared.tool_registry import get_tools_for_business_type

    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    business_type = client.get("business_type", "generic")
    catalog = get_tools_for_business_type(business_type)
    current_tools = client.get("tools_config") or {}

    result = {}
    for tool_id, meta in catalog.items():
        tool_config = current_tools.get(tool_id)
        is_active = False
        config_data = {}

        if isinstance(tool_config, bool):
            is_active = tool_config
        elif isinstance(tool_config, dict):
            is_active = tool_config.get("active", False)
            config_data = {k: v for k, v in tool_config.items() if k != "active"}

        result[tool_id] = {
            "label": meta.get("label", tool_id),
            "category": meta.get("category"),
            "is_active": is_active,
            "config": config_data,
            "config_fields": meta.get("config_fields", {}),
            "has_instructions": meta.get("has_instructions", False),
            "credential_source": meta.get("credential_source"),
            "provider_badge": meta.get("provider_badge", ""),
        }

    return result


@router.put("/{token}/tools")
def update_client_tools(token: str, tools_update: ToolsConfigUpdate):
    """
    Atualiza configuração de ferramentas (LancePilot, etc).
    Faz merge com o config existente.
    """
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    current_tools = client.get("tools_config") or {}

    # Atualiza LancePilot se enviado
    if tools_update.lancepilot:
        current_tools["lancepilot"] = tools_update.lancepilot.model_dump()

    # Generic Tools
    if tools_update.consultar_cep is not None:
        current_tools["consultar_cep"] = tools_update.consultar_cep

    if tools_update.atendimento_humano is not None:
        current_tools["atendimento_humano"] = tools_update.atendimento_humano

    # Follow-Up (Loop)
    if tools_update.followup is not None:
        current_tools["followup"] = tools_update.followup

    # Custom Tools (Make-like)
    if tools_update.custom_tools is not None:
        current_tools["custom_tools"] = tools_update.custom_tools

    success = update_tools_config_db(client["id"], current_tools)
    if not success:
        raise HTTPException(status_code=500, detail="Falha ao salvar tools_config")

    return {"message": "Tools atualizadas", "config": current_tools}


# --- ARQUIVOS / RAG ---


@router.post("/{token}/files")
def upload_file(token: str, file: UploadFile = File(...)):
    """Upload de arquivo para a Knowledge Base do cliente."""
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    store_id = client.get("gemini_store_id")
    if not store_id:
        raise HTTPException(
            status_code=400,
            detail="Cliente não possui Vector Store configurado (gemini_store_id).",
        )

    # Save temp
    temp_filename = f"temp_{file.filename}"
    try:
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Upload to Gemini
        # TODO: Detectar MIME Type real
        mime_type = file.content_type or "application/pdf"
        uploaded, error = gemini_service.upload_file(temp_filename, mime_type, store_id)

        if error:
            raise HTTPException(status_code=500, detail=f"Erro no Gemini: {error}")

        return {
            "filename": file.filename,
            "status": "uploaded",
            "gemini_info": str(uploaded),
        }

    except Exception as e:
        logger.error(f"Erro upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)


@router.get("/{token}/files")
def list_files(token: str):
    """Lista arquivos na Knowledge Base."""
    client = get_client_config(token)
    if not client:
        raise HTTPException(status_code=404)

    store_id = client.get("gemini_store_id")
    if not store_id:
        return []

    return gemini_service.list_files(store_id)


@router.delete("/{token}/files/{filename}")
def delete_file(token: str, filename: str):
    """Remove arquivo (Nota: Gemini requer 'name' interno, aqui assumimos display name por enquanto ou precisa de mapping)."""
    # Simplificação: Tentar deletar pelo nome se o service suportar lookup
    success = gemini_service.delete_file(filename)
    if not success:
        raise HTTPException(
            status_code=400, detail="Falha ao deletar (ou arquivo não encontrado)"
        )
    return {"status": "deleted"}
