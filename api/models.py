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
    whatsapp_provider: Optional[str] = Field(
        "none", description="Provider WhatsApp: none, uazapi, meta, lancepilot"
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
    # Generic Tools
    consultar_cep: Optional[bool] = None
    atendimento_humano: Optional[dict] = None  # {"active": true, "timeout_minutes": 60}

    # Follow-Up (Loop)
    followup: Optional[dict] = None  # {"active": true, "interval_hours": 24}

    # Custom (Make-like)
    custom_tools: Optional[list] = None  # List of JSON Tool Definitions


class OAuthCode(BaseModel):
    code: str
    token: str  # Token do Cliente para vincular
    waba_id: Optional[str] = None
    phone_id: Optional[str] = None
