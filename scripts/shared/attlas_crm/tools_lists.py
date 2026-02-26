"""
tools_lists.py - Tools de gestão de Listas (Colunas/Etapas) do Attlas CRM.

Endpoints cobertos:
  GET   /projetos/{project}/listas                   - Listar colunas
  POST  /listas/{project}/criar                      - Criar coluna
  PATCH /listas/{project}/reordenar                  - Reordenar colunas
  PATCH /listas/atualizar-nome/{list}                - Atualizar nome
  PATCH /listas/atualizar-descricao/{list}           - Atualizar descricao
  PATCH /listas/atualizar-cor/{list}                 - Atualizar cor
  PATCH /listas/atualizar-periodo-vencimento/{list}  - Prazo automatico
  PATCH /listas/atualizar-responsavel/{list}         - Responsavel padrao
  PATCH /listas/atualizar-fluxo/{list}               - Marcar como final
  PATCH /listas/atualizar-permissoes/{list}          - Permissoes
  PATCH /listas/atualizar-alertas/{list}             - Alertas
  PATCH /listas/atualizar-etapa-funil/{list}         - Etapa do funil
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_colunas(
        project_uuid: str = Field(description="UUID do projeto"),
    ) -> str:
        """Lista todas as colunas (listas/etapas) de um projeto com id, nome, ordem, is_start e is_end."""
        data = client.get(f"/projetos/{project_uuid}/listas")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_coluna(
        project_uuid: str = Field(description="UUID do projeto"),
        name: str = Field(description="Nome da coluna (min 3 caracteres)"),
    ) -> str:
        """Cria uma nova coluna (etapa) no projeto."""
        data = client.post(f"/listas/{project_uuid}/criar", {"name": name})
        return json.dumps(data, ensure_ascii=False, default=str)

    def reordenar_colunas(
        project_uuid: str = Field(description="UUID do projeto"),
        lists_order: str = Field(
            description='JSON array com nova ordem. Ex: [{"id": 10, "order": 0}, {"id": 12, "order": 1}]'
        ),
    ) -> str:
        """Reordena as colunas de um projeto (arrastar colunas no Kanban)."""
        data = client.patch(f"/listas/{project_uuid}/reordenar", {"lists": json.loads(lists_order)})
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_coluna(
        list_id: int = Field(description="ID da lista/coluna"),
        campo: str = Field(
            description="Campo a atualizar: 'nome', 'descricao', 'cor', 'periodo_vencimento', "
            "'responsavel', 'fluxo', 'permissoes', 'alertas' ou 'etapa_funil'"
        ),
        valor: str = Field(
            description="Valor no formato JSON. Exemplos por campo: "
            "nome: {\"name\": \"Novo Nome\"} | "
            "descricao: {\"description\": \"Texto\"} | "
            "cor: {\"bg_color\": \"#FF5733\"} | "
            "periodo_vencimento: {\"due_days\": 7, \"due_time\": \"18:00\"} | "
            "responsavel: {\"responsible_id\": 42} | "
            "fluxo: {\"is_end\": true} | "
            "permissoes: {\"allow_new_cards\": true, \"hidden_to_roles\": [3, 5]} | "
            "alertas: {\"responsible\": true, \"creator\": false, \"participants\": true} | "
            "etapa_funil: {\"funnel_stage\": \"negociacao\"}"
        ),
    ) -> str:
        """Atualiza uma configuracao especifica de uma coluna/lista do Kanban.
        Campos disponiveis: nome, descricao, cor, periodo_vencimento, responsavel,
        fluxo, permissoes, alertas, etapa_funil."""
        campo_map = {
            "nome": "atualizar-nome",
            "descricao": "atualizar-descricao",
            "cor": "atualizar-cor",
            "periodo_vencimento": "atualizar-periodo-vencimento",
            "responsavel": "atualizar-responsavel",
            "fluxo": "atualizar-fluxo",
            "permissoes": "atualizar-permissoes",
            "alertas": "atualizar-alertas",
            "etapa_funil": "atualizar-etapa-funil",
        }
        endpoint = campo_map.get(campo)
        if not endpoint:
            return json.dumps({"error": True, "message": f"Campo invalido: {campo}. Use: {list(campo_map.keys())}"})
        body = json.loads(valor)
        data = client.patch(f"/listas/{endpoint}/{list_id}", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_colunas, name="attlas_listar_colunas"),
        StructuredTool.from_function(criar_coluna, name="attlas_criar_coluna"),
        StructuredTool.from_function(reordenar_colunas, name="attlas_reordenar_colunas"),
        StructuredTool.from_function(atualizar_coluna, name="attlas_atualizar_coluna"),
    ]
