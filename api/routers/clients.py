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
)
from api.services.gemini_service import service as gemini_service

router = APIRouter(
    prefix="/clients",
    tags=["clients"],
    dependencies=[Depends(verify_token)],  # Protege todas as rotas
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
        store_id=client.gemini_store_id,
    )

    if not new_id:
        raise HTTPException(
            status_code=400, detail="Erro ao criar cliente. Verifique logs."
        )

    return {"id": new_id, "message": "Cliente criado com sucesso"}


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

    # TODO: Outros tools

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
