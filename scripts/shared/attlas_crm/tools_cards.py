"""
tools_cards.py - Tools de gestão de Cards (Leads/Tarefas) do Attlas CRM.

Endpoints cobertos:
  GET    /cards/{project}/kanban                  - Kanban completo com filtros
  GET    /cards/{card}                            - Detalhes de um card
  POST   /cards/{list}/criar                      - Criar card
  POST   /cards/duplicar/{card}                   - Duplicar card
  PATCH  /cards/mover/{card}/{list}               - Mover card
  PATCH  /cards/mudar-titulo/{card}               - Atualizar titulo
  PATCH  /cards/mudar-descricao/{card}            - Atualizar descricao
  PATCH  /cards/mudar-prioridade/{card}           - Atualizar prioridade
  PATCH  /cards/mudar-data-vencimento/{card}      - Atualizar data vencimento
  PATCH  /cards/mudar-crm-details/{card}          - Atualizar CRM details
  PATCH  /cards/canal-aquisicao                   - Atualizar canal aquisicao
  POST   /cards/{card}/responsavel/{user}         - Definir responsavel
  DELETE /cards/{card}/responsavel                - Remover responsavel
  POST   /cards/resultado                         - Registrar resultado (ganho/perdido)
  DELETE /cards/resultado/{leadResultado}          - Deletar resultado
  DELETE /cards/excluir/{card}                    - Excluir card
  DELETE /cards/bulk-delete                       - Excluir em massa
  DELETE /cards/bulk-archive                      - Arquivar em massa
  POST   /cards/bulk-restore                      - Restaurar em massa
  POST   /cards/iniciar-chat                      - Iniciar chat WhatsApp
  GET    /projetos/{project}/cards-updates        - Polling de atualizacoes
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def buscar_kanban(
        project_uuid: str = Field(description="UUID do projeto"),
        order: str = Field("desc", description="Ordem: 'asc' (mais antigos) ou 'desc' (mais novos)"),
        responsible_ids: Optional[str] = Field(None, description="JSON array de IDs de responsaveis para filtrar"),
        tags_ids: Optional[str] = Field(None, description="JSON array de IDs de tags para filtrar"),
        archived: bool = Field(False, description="Se true, retorna apenas cards arquivados"),
    ) -> str:
        """Busca o Kanban completo de um projeto com todas as colunas e cards.
        Suporta filtros por responsavel, tags e arquivados.
        Retorna listas com seus cards incluindo tags, chat, responsavel e contagem de comentarios."""
        params = {"order": order}
        if archived:
            params["archived"] = "true"
        if responsible_ids:
            for i, rid in enumerate(json.loads(responsible_ids)):
                params[f"responsible_ids[{i}]"] = rid
        if tags_ids:
            for i, tid in enumerate(json.loads(tags_ids)):
                params[f"tags_ids[{i}]"] = tid
        data = client.get(f"/cards/{project_uuid}/kanban", params)
        return json.dumps(data, ensure_ascii=False, default=str)

    def obter_card(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Retorna os detalhes completos de um card especifico, incluindo chat associado."""
        data = client.get(f"/cards/{card_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_card(
        list_id: int = Field(description="ID da lista/coluna onde o card sera criado"),
        title: Optional[str] = Field(None, description="Titulo do card"),
        client_name: Optional[str] = Field(None, description="Nome do cliente (CRM)"),
        client_phone: Optional[str] = Field(None, description="Telefone do cliente (CRM)"),
        client_email: Optional[str] = Field(None, description="Email do cliente (CRM)"),
        client_company: Optional[str] = Field(None, description="Empresa do cliente (CRM)"),
        opportunity_value: Optional[float] = Field(None, description="Valor da oportunidade em R$"),
    ) -> str:
        """Cria um novo card (lead) em uma lista especifica.
        Pode incluir detalhes CRM como nome, telefone, email, empresa e valor da oportunidade."""
        body: dict = {"list_id": list_id}
        if title:
            body["title"] = title
        crm = {}
        if client_name:
            crm["client_name"] = client_name
        if client_phone:
            crm["client_phone"] = client_phone
        if client_email:
            crm["client_email"] = client_email
        if client_company:
            crm["client_company"] = client_company
        if opportunity_value is not None:
            crm["opportunity_value"] = opportunity_value
        if crm:
            body["crm_details"] = crm
        data = client.post(f"/cards/{list_id}/criar", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def mover_card(
        card_uuid: str = Field(description="UUID do card a mover"),
        list_id: int = Field(description="ID da lista de destino"),
        cards_order: str = Field(
            description='JSON array da nova ordem dos cards na lista de destino. '
            'Ex: [{"uuid": "abc-123", "order": 1}, {"uuid": "def-456", "order": 2}]'
        ),
    ) -> str:
        """Move um card para outra lista/coluna do Kanban e reordena os cards."""
        body = {"cards_order": json.loads(cards_order)}
        data = client.patch(f"/cards/mover/{card_uuid}/{list_id}", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def duplicar_card(
        card_uuid: str = Field(description="UUID do card a duplicar"),
    ) -> str:
        """Cria uma copia completa de um card existente na mesma lista."""
        data = client.post(f"/cards/duplicar/{card_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_titulo(
        card_uuid: str = Field(description="UUID do card"),
        title: str = Field(description="Novo titulo"),
    ) -> str:
        """Atualiza o titulo de um card."""
        data = client.patch(f"/cards/mudar-titulo/{card_uuid}", {"title": title})
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_descricao(
        card_uuid: str = Field(description="UUID do card"),
        description: str = Field(description="Nova descricao"),
    ) -> str:
        """Atualiza a descricao de um card."""
        data = client.patch(f"/cards/mudar-descricao/{card_uuid}", {"description": description})
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_prioridade(
        card_uuid: str = Field(description="UUID do card"),
        priority: int = Field(description="Prioridade: 0=Sem, 1=Baixa, 2=Media, 3=Alta, 4=Urgente"),
    ) -> str:
        """Atualiza a prioridade de um card (0-4)."""
        data = client.patch(f"/cards/mudar-prioridade/{card_uuid}", {"priority": priority})
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_data_vencimento(
        card_uuid: str = Field(description="UUID do card"),
        due_date: Optional[str] = Field(None, description="Data de vencimento formato YYYY-MM-DD (null para remover)"),
    ) -> str:
        """Atualiza ou remove a data de vencimento de um card."""
        data = client.patch(f"/cards/mudar-data-vencimento/{card_uuid}", {"due_date": due_date})
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_crm_details(
        card_uuid: str = Field(description="UUID do card"),
        field: str = Field(
            description="Campo CRM: 'client_name', 'client_email', 'client_phone' ou 'client_company'"
        ),
        value: Optional[str] = Field(description="Novo valor (null para limpar)"),
    ) -> str:
        """Atualiza um campo especifico dos detalhes CRM do card (nome, email, telefone ou empresa)."""
        data = client.patch(f"/cards/mudar-crm-details/{card_uuid}", {"field": field, "value": value})
        return json.dumps(data, ensure_ascii=False, default=str)

    def atualizar_canal_aquisicao(
        card_uuid: str = Field(description="UUID do card"),
        canal_aquisicao: str = Field(description="Canal de aquisicao (ex: WhatsApp, Instagram, Facebook, Email, Site)"),
    ) -> str:
        """Atualiza o canal de aquisicao (origem) de um card."""
        data = client.patch("/cards/canal-aquisicao", {"card_uuid": card_uuid, "canal_aquisicao": canal_aquisicao})
        return json.dumps(data, ensure_ascii=False, default=str)

    def definir_responsavel(
        card_uuid: str = Field(description="UUID do card"),
        user_id: int = Field(description="ID do usuario responsavel"),
    ) -> str:
        """Define o responsavel por um card."""
        data = client.post(f"/cards/{card_uuid}/responsavel/{user_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def remover_responsavel(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Remove o responsavel de um card (seta como null)."""
        data = client.delete(f"/cards/{card_uuid}/responsavel")
        return json.dumps(data, ensure_ascii=False, default=str)

    def registrar_resultado(
        card_uuid: str = Field(description="UUID do card"),
        status: str = Field(description="Resultado: 'ganho' ou 'perdido'"),
        valor_oportunidade: Optional[float] = Field(None, description="Valor da oportunidade em R$"),
    ) -> str:
        """Registra o resultado de um lead/card como ganho ou perdido. Alimenta relatorios e metas."""
        body: dict = {"card_uuid": card_uuid, "status": status}
        if valor_oportunidade is not None:
            body["valor_oportunidade"] = valor_oportunidade
        data = client.post("/cards/resultado", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def deletar_resultado(
        lead_resultado_id: int = Field(description="ID do lead resultado a deletar"),
    ) -> str:
        """Remove o registro de resultado (ganho/perdido) de um card."""
        data = client.delete(f"/cards/resultado/{lead_resultado_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def excluir_card(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Exclui um card permanentemente. IRREVERSIVEL."""
        data = client.delete(f"/cards/excluir/{card_uuid}")
        return json.dumps(data, ensure_ascii=False, default=str)

    def arquivar_cards(
        card_uuids: str = Field(description="JSON array de UUIDs dos cards a arquivar"),
    ) -> str:
        """Arquiva (soft delete) um ou mais cards. Mantem historico e permite restauracao."""
        data = client.delete("/cards/bulk-archive", {"card_uuids": json.loads(card_uuids)})
        return json.dumps(data, ensure_ascii=False, default=str)

    def restaurar_cards(
        card_uuids: str = Field(description="JSON array de UUIDs dos cards a restaurar"),
    ) -> str:
        """Restaura (desarquiva) um ou mais cards previamente arquivados."""
        data = client.post("/cards/bulk-restore", {"card_uuids": json.loads(card_uuids)})
        return json.dumps(data, ensure_ascii=False, default=str)

    def iniciar_chat_whatsapp(
        card_uuid: str = Field(description="UUID do card"),
        numero: str = Field(description="Numero de telefone (apenas digitos, ex: 5511999998888)"),
        mensagem: str = Field(description="Mensagem inicial a enviar"),
    ) -> str:
        """Inicia uma conversa no WhatsApp a partir de um card. Valida o numero e envia a primeira mensagem."""
        body = {"card_uuid": card_uuid, "numero": numero, "mensagem": mensagem}
        data = client.post("/cards/iniciar-chat", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(buscar_kanban, name="attlas_buscar_kanban"),
        StructuredTool.from_function(obter_card, name="attlas_obter_card"),
        StructuredTool.from_function(criar_card, name="attlas_criar_card"),
        StructuredTool.from_function(mover_card, name="attlas_mover_card"),
        StructuredTool.from_function(duplicar_card, name="attlas_duplicar_card"),
        StructuredTool.from_function(atualizar_titulo, name="attlas_atualizar_titulo"),
        StructuredTool.from_function(atualizar_descricao, name="attlas_atualizar_descricao"),
        StructuredTool.from_function(atualizar_prioridade, name="attlas_atualizar_prioridade"),
        StructuredTool.from_function(atualizar_data_vencimento, name="attlas_atualizar_data_vencimento"),
        StructuredTool.from_function(atualizar_crm_details, name="attlas_atualizar_crm_details"),
        StructuredTool.from_function(atualizar_canal_aquisicao, name="attlas_atualizar_canal_aquisicao"),
        StructuredTool.from_function(definir_responsavel, name="attlas_definir_responsavel"),
        StructuredTool.from_function(remover_responsavel, name="attlas_remover_responsavel"),
        StructuredTool.from_function(registrar_resultado, name="attlas_registrar_resultado"),
        StructuredTool.from_function(deletar_resultado, name="attlas_deletar_resultado"),
        StructuredTool.from_function(excluir_card, name="attlas_excluir_card"),
        StructuredTool.from_function(arquivar_cards, name="attlas_arquivar_cards"),
        StructuredTool.from_function(restaurar_cards, name="attlas_restaurar_cards"),
        StructuredTool.from_function(iniciar_chat_whatsapp, name="attlas_iniciar_chat_whatsapp"),
    ]
