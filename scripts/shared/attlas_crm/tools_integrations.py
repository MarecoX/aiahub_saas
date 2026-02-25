"""
tools_integrations.py - Tools de Integrações de Projeto do Attlas CRM.

Endpoints cobertos:
  GET    /projetos/{project}/integracoes                          - Listar integracoes
  POST   /projetos/{project}/integracoes                          - Criar integracao
  PUT    /projetos/{project}/integracoes/{integration}            - Atualizar integracao
  DELETE /projetos/{project}/integracoes/{integration}            - Revogar integracao
  PATCH  /projetos/{project}/integracoes/{integration}/toggle     - Ativar/desativar
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_integracoes(
        project_uuid: str = Field(description="UUID do projeto"),
    ) -> str:
        """Lista todas as integracoes API de um projeto com tokens, URLs e headers."""
        data = client.get(f"/projetos/{project_uuid}/integracoes")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_integracao(
        project_uuid: str = Field(description="UUID do projeto"),
        name: str = Field(description="Nome da integracao (ex: 'Formulario do Site')"),
        description: Optional[str] = Field(None, description="Descricao da integracao"),
    ) -> str:
        """Cria uma nova integracao API para o projeto. Gera automaticamente um token Bearer."""
        body: dict = {"name": name}
        if description:
            body["description"] = description
        data = client.post(f"/projetos/{project_uuid}/integracoes", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_integracao(
        project_uuid: str = Field(description="UUID do projeto"),
        integration_id: int = Field(description="ID da integracao"),
        name: str = Field(description="Novo nome"),
        description: Optional[str] = Field(None, description="Nova descricao"),
    ) -> str:
        """Atualiza nome e descricao de uma integracao. O token nao e alterado."""
        body: dict = {"name": name}
        if description:
            body["description"] = description
        data = client.put(f"/projetos/{project_uuid}/integracoes/{integration_id}", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def revogar_integracao(
        project_uuid: str = Field(description="UUID do projeto"),
        integration_id: int = Field(description="ID da integracao"),
    ) -> str:
        """Revoga (deleta) permanentemente uma integracao e invalida seu token. IRREVERSIVEL."""
        data = client.delete(f"/projetos/{project_uuid}/integracoes/{integration_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def toggle_integracao(
        project_uuid: str = Field(description="UUID do projeto"),
        integration_id: int = Field(description="ID da integracao"),
    ) -> str:
        """Ativa ou desativa uma integracao. Integracoes inativas nao aceitam requisicoes."""
        data = client.patch(f"/projetos/{project_uuid}/integracoes/{integration_id}/toggle")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_integracoes, name="attlas_listar_integracoes"),
        StructuredTool.from_function(criar_integracao, name="attlas_criar_integracao"),
        StructuredTool.from_function(atualizar_integracao, name="attlas_atualizar_integracao"),
        StructuredTool.from_function(revogar_integracao, name="attlas_revogar_integracao"),
        StructuredTool.from_function(toggle_integracao, name="attlas_toggle_integracao"),
    ]
