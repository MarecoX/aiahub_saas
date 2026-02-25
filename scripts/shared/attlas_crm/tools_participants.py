"""
tools_participants.py - Tools de Participantes de Cards do Attlas CRM.

Endpoints cobertos:
  POST   /participantes/{card}        - Adicionar participante
  DELETE /participantes/{card}/{user}  - Remover participante
"""

import json
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def adicionar_participante(
        card_uuid: str = Field(description="UUID do card"),
        user_id: int = Field(description="ID do usuario a adicionar como participante"),
    ) -> str:
        """Adiciona um usuario como participante de um card. Retorna lista atualizada de participantes."""
        data = client.post(f"/participantes/{card_uuid}", {"user": user_id})
        return json.dumps(data, ensure_ascii=False, default=str)

    def remover_participante(
        card_uuid: str = Field(description="UUID do card"),
        user_id: int = Field(description="ID do usuario a remover"),
    ) -> str:
        """Remove um usuario dos participantes de um card."""
        data = client.delete(f"/participantes/{card_uuid}/{user_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(adicionar_participante, name="attlas_adicionar_participante"),
        StructuredTool.from_function(remover_participante, name="attlas_remover_participante"),
    ]
