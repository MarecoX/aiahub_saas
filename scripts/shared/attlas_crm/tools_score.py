"""
tools_score.py - Tools de Lead Scoring do Attlas CRM.

Endpoints cobertos:
  POST /cards/{card}/score          - Adicionar pontuacao manual
  GET  /cards/{card}/score/history  - Historico de pontuacao
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def adicionar_pontuacao(
        card_uuid: str = Field(description="UUID do card"),
        points: int = Field(description="Pontos a adicionar (positivo ou negativo)"),
        reason: str = Field(description="Motivo da pontuacao (ex: 'Ligacao muito produtiva')"),
    ) -> str:
        """Adiciona pontuacao manual ao Lead Score de um card.
        Pontos positivos aquecem o lead, negativos esfriam.
        Retorna novo score total e temperatura (frio/morno/quente)."""
        body = {"points": points, "reason": reason}
        data = client.post(f"/cards/{card_uuid}/score", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def historico_pontuacao(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Retorna o historico completo de alteracoes de pontuacao de um lead,
        incluindo score total atual e todos os eventos (data, pontos, motivo)."""
        data = client.get(f"/cards/{card_uuid}/score/history")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(adicionar_pontuacao, name="attlas_adicionar_pontuacao"),
        StructuredTool.from_function(historico_pontuacao, name="attlas_historico_pontuacao"),
    ]
