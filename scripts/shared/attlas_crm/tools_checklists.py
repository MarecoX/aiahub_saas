"""
tools_checklists.py - Tools de Checklists do Attlas CRM.

Endpoints cobertos:
  GET  /cards/{card}/checklists                              - Listar checklists
  POST /cards/{card}/checklists                              - Criar checklist
  POST /cards/{card}/checklists/apply-template/{template}    - Aplicar template
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_checklists(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Lista todos os checklists de um card com seus itens e percentual de progresso."""
        data = client.get(f"/cards/{card_uuid}/checklists")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_checklist(
        card_uuid: str = Field(description="UUID do card"),
        name: str = Field(description="Nome do checklist (ex: 'Documentos Pendentes')"),
    ) -> str:
        """Cria um novo checklist vazio em um card. Retorna todos os checklists do card."""
        data = client.post(f"/cards/{card_uuid}/checklists", {"name": name})
        return json.dumps(data, ensure_ascii=False, default=str)

    def aplicar_template_checklist(
        card_uuid: str = Field(description="UUID do card"),
        template_id: int = Field(description="ID do template de checklist"),
    ) -> str:
        """Aplica um template de checklist a um card, copiando todos os itens do modelo."""
        data = client.post(f"/cards/{card_uuid}/checklists/apply-template/{template_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_checklists, name="attlas_listar_checklists"),
        StructuredTool.from_function(criar_checklist, name="attlas_criar_checklist"),
        StructuredTool.from_function(aplicar_template_checklist, name="attlas_aplicar_template_checklist"),
    ]
