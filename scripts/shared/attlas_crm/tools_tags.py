"""
tools_tags.py - Tools de Tags (Etiquetas) do Attlas CRM.

Endpoints cobertos:
  GET    /etiquetas/{project}        - Listar tags do projeto
  POST   /etiquetas/{project}/criar  - Criar tag
  POST   /tags/{card}/{tag}          - Adicionar tag ao card
  DELETE /tags/{card}/{tag}          - Remover tag do card
"""

import json
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_tags_projeto(
        project_uuid: str = Field(description="UUID do projeto"),
    ) -> str:
        """Lista todas as tags (etiquetas) disponiveis em um projeto com id, nome e cor."""
        data = client.get(f"/etiquetas/{project_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_tag(
        project_uuid: str = Field(description="UUID do projeto"),
        title: str = Field(description="Nome da tag (max 50 chars)"),
        class_name: str = Field(description="Classe CSS da cor (ex: bg-red-500, bg-blue-500, bg-green-500)"),
    ) -> str:
        """Cria uma nova tag (etiqueta) em um projeto. Retorna todas as tags atualizadas."""
        body = {"title": title, "class_name": class_name}
        data = client.post(f"/etiquetas/{project_uuid}/criar", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def adicionar_tag_card(
        card_uuid: str = Field(description="UUID do card"),
        tag_id: int = Field(description="ID da tag a adicionar"),
    ) -> str:
        """Adiciona uma tag existente a um card. Retorna todas as tags do card."""
        data = client.post(f"/tags/{card_uuid}/{tag_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def remover_tag_card(
        card_uuid: str = Field(description="UUID do card"),
        tag_id: int = Field(description="ID da tag a remover"),
    ) -> str:
        """Remove uma tag de um card. Retorna as tags restantes."""
        data = client.delete(f"/tags/{card_uuid}/{tag_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_tags_projeto, name="attlas_listar_tags"),
        StructuredTool.from_function(criar_tag, name="attlas_criar_tag"),
        StructuredTool.from_function(adicionar_tag_card, name="attlas_adicionar_tag"),
        StructuredTool.from_function(remover_tag_card, name="attlas_remover_tag"),
    ]
