"""
tools_projects.py - Tools de gestão de Projetos (Pipelines) do Attlas CRM.

Endpoints cobertos:
  GET    /projetos                              - Listar projetos
  POST   /projetos                              - Criar projeto
  PUT    /projetos/{project}                    - Atualizar projeto
  DELETE /projetos/{project}                    - Excluir projeto
  POST   /projetos/{project}/participantes      - Adicionar participante
  DELETE /projetos/{project}/participantes/{u}  - Remover participante
  POST   /projetos/{project}/definir-instancia-whatsapp
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:
    """Retorna lista de LangChain tools para gestão de projetos."""

    def listar_projetos() -> str:
        """Lista todos os projetos/pipelines do CRM que o usuario tem acesso.
        Retorna id, uuid, nome, grupo, quantidade de listas e cards."""
        data = client.get("/projetos")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_projeto(
        key: str = Field(description="Codigo unico do projeto (max 3 caracteres, ex: VND, MKT)"),
        name: str = Field(description="Nome do projeto (min 3 caracteres)"),
        lists: str = Field(
            description='JSON array de listas. Cada lista: {"name": "...", "is_start": bool, "is_end": bool}. '
            "Precisa de pelo menos 2 listas, sendo 1 de inicio e pelo menos 1 de fim."
        ),
        description: Optional[str] = Field(None, description="Descricao do projeto"),
        allow_external_requests: bool = Field(False, description="Permitir criacao de cards via API externa"),
    ) -> str:
        """Cria um novo projeto (pipeline/funil) no CRM com suas listas/colunas iniciais."""
        body = {
            "key": key,
            "name": name,
            "allow_external_requests": allow_external_requests,
            "lists": json.loads(lists),
        }
        if description:
            body["description"] = description
        data = client.post("/projetos", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_projeto(
        project_uuid: str = Field(description="UUID do projeto"),
        name: Optional[str] = Field(None, description="Novo nome"),
        description: Optional[str] = Field(None, description="Nova descricao"),
        key: Optional[str] = Field(None, description="Novo codigo (max 3 chars)"),
    ) -> str:
        """Atualiza dados de um projeto existente. Envie apenas os campos que deseja alterar."""
        body = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        if key:
            body["key"] = key
        data = client.put(f"/projetos/{project_uuid}", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def excluir_projeto(
        project_uuid: str = Field(description="UUID do projeto a excluir"),
    ) -> str:
        """Exclui permanentemente um projeto e todos os seus dados (listas, cards, automacoes)."""
        data = client.delete(f"/projetos/{project_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def adicionar_participante_projeto(
        project_uuid: str = Field(description="UUID do projeto"),
        user_id: int = Field(description="ID do usuario a adicionar"),
        roles: str = Field(description="JSON array de IDs de perfis de acesso (ex: [1, 2])"),
    ) -> str:
        """Adiciona um usuario como participante de um projeto com perfis de acesso especificos."""
        body = {"user": user_id, "roles": json.loads(roles)}
        data = client.post(f"/projetos/{project_uuid}/participantes", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def remover_participante_projeto(
        project_uuid: str = Field(description="UUID do projeto"),
        user_id: int = Field(description="ID do usuario a remover"),
    ) -> str:
        """Remove um usuario da lista de participantes do projeto."""
        data = client.delete(f"/projetos/{project_uuid}/participantes/{user_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def definir_instancia_whatsapp(
        project_uuid: str = Field(description="UUID do projeto"),
        whatsapp_instance_id: int = Field(description="ID da instancia WhatsApp"),
    ) -> str:
        """Associa uma instancia WhatsApp ao projeto para envio/recebimento de mensagens."""
        body = {
            "project_uuid": project_uuid,
            "whatsapp_instance_id": whatsapp_instance_id,
        }
        data = client.post(f"/projetos/{project_uuid}/definir-instancia-whatsapp", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_projetos, name="attlas_listar_projetos"),
        StructuredTool.from_function(criar_projeto, name="attlas_criar_projeto"),
        StructuredTool.from_function(atualizar_projeto, name="attlas_atualizar_projeto"),
        StructuredTool.from_function(excluir_projeto, name="attlas_excluir_projeto"),
        StructuredTool.from_function(adicionar_participante_projeto, name="attlas_adicionar_participante_projeto"),
        StructuredTool.from_function(remover_participante_projeto, name="attlas_remover_participante_projeto"),
        StructuredTool.from_function(definir_instancia_whatsapp, name="attlas_definir_instancia_whatsapp"),
    ]
