from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum


# --- Provider Types ---


class ProviderType(str, Enum):
    uazapi = "uazapi"
    meta = "meta"
    lancepilot = "lancepilot"


# --- Provider Models ---


class ProviderConfigCreate(BaseModel):
    """Configuração de um provider WhatsApp."""

    provider_type: ProviderType = Field(..., description="Tipo do provider: uazapi, meta, lancepilot")
    config: Dict[str, Any] = Field(
        ...,
        description="Credenciais do provider. Uazapi: {url, token}. Meta: {access_token, phone_id, waba_id}. LancePilot: {token, workspace_id}",
    )
    instance_name: str = Field("Principal", description="Nome da instância (ex: 'Loja Centro', 'Filial 2')")
    is_default: bool = Field(False, description="Se é o provider padrão para envio")


class ProviderConfigUpdate(BaseModel):
    """Atualização parcial de um provider."""

    config: Optional[Dict[str, Any]] = Field(None, description="Novas credenciais")
    instance_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class ProviderConfigResponse(BaseModel):
    """Resposta com dados do provider."""

    id: str
    provider_type: str
    instance_name: str
    config: Dict[str, Any]
    is_active: bool
    is_default: bool


# --- Client Models ---


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
        None, description="(Legado) URL da API Uazapi. Prefira usar provider_config.",
    )
    human_attendant_timeout: Optional[int] = Field(
        3600, description="Tempo de silêncio (segundos) após intervenção humana"
    )
    whatsapp_provider: Optional[str] = Field(
        "none", description="Provider WhatsApp: none, uazapi, meta, lancepilot"
    )
    business_type: Optional[str] = Field(
        "generic",
        description="Tipo de negócio: generic, isp, varejo, servicos, food, saude",
    )


class ClientCreate(ClientBase):
    """Criação de cliente com provider opcional."""

    provider_config: Optional[ProviderConfigCreate] = Field(
        None,
        description="Configuração do provider WhatsApp. Se informado, cria entrada em client_providers automaticamente.",
    )


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    human_attendant_timeout: Optional[int] = None
    active: Optional[bool] = None
    business_type: Optional[str] = None


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


class ToolUpdate(BaseModel):
    """Atualiza uma tool individual do cliente."""

    active: bool = Field(..., description="Se a tool está ativa ou não")
    config: Optional[Dict[str, Any]] = Field(
        None,
        description="Configuração da tool (credenciais, parâmetros). Os campos variam por tool — consulte GET /tools/catalog",
    )
    instructions: Optional[str] = Field(
        None,
        description="Instruções customizadas para a IA (quando has_instructions=true no catálogo)",
    )


class OAuthCode(BaseModel):
    code: str
    client_id: str = Field(
        ..., alias="token", description="UUID do Cliente (aceita 'token' como alias)"
    )  # Aceita 'token' para compatibilidade
    waba_id: Optional[str] = None
    phone_id: Optional[str] = None

    class Config:
        populate_by_name = True  # Permite usar tanto 'client_id' quanto 'token'
