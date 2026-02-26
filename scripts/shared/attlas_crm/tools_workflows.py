"""
tools_workflows.py - Tools de Workflows (Automações) do Attlas CRM.

Endpoints cobertos:
  GET    /workflows/{project}  - Listar workflows
  POST   /workflows            - Criar workflow
  PUT    /workflows/{workflow}  - Atualizar workflow
  DELETE /workflows/{workflow}  - Excluir workflow
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_workflows(
        project_uuid: str = Field(description="UUID do projeto"),
    ) -> str:
        """Lista todos os workflows (automacoes) de um projeto com triggers, condicoes e acoes."""
        data = client.get(f"/workflows/{project_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_workflow(
        name: str = Field(description="Nome do workflow"),
        project_uuid: str = Field(description="UUID do projeto"),
        active: bool = Field(True, description="Se o workflow esta ativo"),
        rules: str = Field(
            description='JSON array de regras. Cada regra: '
            '{"campo": "canal_aquisicao", "operador": "igual", "valor": "WhatsApp", '
            '"target_pipeline_uuid": "uuid-destino", "target_list_id": 1, '
            '"send_whatsapp_message": false, "template_id": null}. '
            "Operadores: igual, diferente, maior_que, menor_que, contem, nao_contem"
        ),
    ) -> str:
        """Cria um novo workflow de automacao com regras/condicoes e acoes.
        Permite automatizar movimentacao de cards e envio de WhatsApp."""
        body = {
            "name": name,
            "project_uuid": project_uuid,
            "active": active,
            "rules": json.loads(rules),
        }
        data = client.post("/workflows", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_workflow(
        workflow_id: int = Field(description="ID do workflow"),
        name: str = Field(description="Nome do workflow"),
        project_uuid: str = Field(description="UUID do projeto"),
        active: bool = Field(description="Se o workflow esta ativo"),
        rules: str = Field(description="JSON array de regras (mesmo formato da criacao)"),
    ) -> str:
        """Atualiza um workflow existente (nome, status ativo e regras)."""
        body = {
            "name": name,
            "project_uuid": project_uuid,
            "active": active,
            "rules": json.loads(rules),
        }
        data = client.put(f"/workflows/{workflow_id}", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def excluir_workflow(
        workflow_id: int = Field(description="ID do workflow"),
    ) -> str:
        """Exclui permanentemente um workflow. Acao irreversivel."""
        data = client.delete(f"/workflows/{workflow_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_workflows, name="attlas_listar_workflows"),
        StructuredTool.from_function(criar_workflow, name="attlas_criar_workflow"),
        StructuredTool.from_function(atualizar_workflow, name="attlas_atualizar_workflow"),
        StructuredTool.from_function(excluir_workflow, name="attlas_excluir_workflow"),
    ]
