"""
tools_bindings.py - Tools de Vínculos entre Cards do Attlas CRM.

Endpoints cobertos:
  GET    /vinculos/{card}              - Listar vinculos
  POST   /vinculos/{card}/{project}    - Criar vinculo
  DELETE /vinculos/{binding}           - Remover vinculo
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_vinculos(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Lista todos os vinculos (relacionamentos) de um card com outros cards."""
        data = client.get(f"/vinculos/{card_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_vinculo(
        card_uuid: str = Field(description="UUID do card de origem"),
        project_uuid: str = Field(description="UUID do projeto do card de destino"),
        to_card_uuid: str = Field(description="UUID do card de destino"),
        with_comments: bool = Field(False, description="Sincronizar comentarios"),
        with_description: bool = Field(False, description="Sincronizar descricao"),
        with_priority: bool = Field(False, description="Sincronizar prioridade"),
        with_due_dates: bool = Field(False, description="Sincronizar datas de vencimento"),
        with_form: bool = Field(False, description="Sincronizar formularios"),
    ) -> str:
        """Cria um vinculo/relacionamento entre dois cards, com opcoes de sincronizacao."""
        body = {
            "toCardUuid": to_card_uuid,
            "withComments": with_comments,
            "withDescription": with_description,
            "withPriority": with_priority,
            "withDueDates": with_due_dates,
            "withForm": with_form,
        }
        data = client.post(f"/vinculos/{card_uuid}/{project_uuid}", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def remover_vinculo(
        binding_id: int = Field(description="ID do vinculo a remover"),
    ) -> str:
        """Remove um vinculo entre dois cards. Nao afeta os dados dos cards."""
        data = client.delete(f"/vinculos/{binding_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_vinculos, name="attlas_listar_vinculos"),
        StructuredTool.from_function(criar_vinculo, name="attlas_criar_vinculo"),
        StructuredTool.from_function(remover_vinculo, name="attlas_remover_vinculo"),
    ]
