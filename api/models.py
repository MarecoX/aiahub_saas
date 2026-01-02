from pydantic import BaseModel, Field
from typing import Optional


class ClientBase(BaseModel):
    name: str = Field(..., description="Nome do Cliente (Empresa)")
    token: str = Field(..., description="Token Único de Identificação (Webhook)")
    system_prompt: Optional[str] = Field(
        None, description="Prompt do Sistema para o Agente"
    )
    gemini_store_id: Optional[str] = Field(
        None, description="ID do Vector Store no Gemini"
    )
    api_url: Optional[str] = Field(
        None, description="URL da API do Cliente (Webhook de Retorno)"
    )
    human_attendant_timeout: Optional[int] = Field(
        3600, description="Tempo de silêncio (segundos) após intervenção humana"
    )


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    human_attendant_timeout: Optional[int] = None
    active: Optional[bool] = None


class LancePilotConfig(BaseModel):
    active: bool = True
    token: str
    workspace_id: str
    number: Optional[str] = None  # Número conectado


class ToolsConfigUpdate(BaseModel):
    lancepilot: Optional[LancePilotConfig] = None
    # Adicionar uazapi/kommo depois se precisar
