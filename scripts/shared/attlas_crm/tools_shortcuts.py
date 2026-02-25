"""
tools_shortcuts.py - Tools compostas (atalhos) para operacoes frequentes no Attlas CRM.

Resolvem gargalos onde a API requer multiplas chamadas para uma unica acao logica:
  - Preencher todos os dados CRM de uma vez (em vez de 4 chamadas separadas)
  - Adicionar multiplas tags de uma vez
  - Qualificar lead: mover + registrar resultado em uma unica tool
  - Mover card de forma simplificada (sem precisar montar cards_order manualmente)
"""

import json
import logging
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient

logger = logging.getLogger("AttlasCRM.Shortcuts")


def _get_tools(client: AttlasCRMClient) -> list:

    def preencher_crm(
        card_uuid: str = Field(description="UUID do card"),
        client_name: Optional[str] = Field(None, description="Nome do cliente"),
        client_phone: Optional[str] = Field(None, description="Telefone do cliente"),
        client_email: Optional[str] = Field(None, description="Email do cliente"),
        client_company: Optional[str] = Field(None, description="Empresa do cliente"),
    ) -> str:
        """Preenche todos os dados CRM de um card de uma vez (nome, telefone, email, empresa).
        Envia apenas os campos informados. Muito mais eficiente que atualizar campo a campo."""
        fields = {}
        if client_name is not None:
            fields["client_name"] = client_name
        if client_phone is not None:
            fields["client_phone"] = client_phone
        if client_email is not None:
            fields["client_email"] = client_email
        if client_company is not None:
            fields["client_company"] = client_company

        if not fields:
            return json.dumps({"error": True, "message": "Informe pelo menos um campo CRM."})

        results = {}
        errors = []
        for field_name, value in fields.items():
            resp = client.patch(
                f"/cards/mudar-crm-details/{card_uuid}",
                {"field": field_name, "value": value},
            )
            if isinstance(resp, dict) and resp.get("error"):
                errors.append(f"{field_name}: {resp.get('message', 'erro')}")
            else:
                results[field_name] = value

        output = {
            "success": len(errors) == 0,
            "updated_fields": results,
            "total_updated": len(results),
        }
        if errors:
            output["errors"] = errors
        return json.dumps(output, ensure_ascii=False, default=str)

    def adicionar_tags(
        card_uuid: str = Field(description="UUID do card"),
        tag_ids: str = Field(description="JSON array de IDs das tags a adicionar (ex: [1, 3, 5])"),
    ) -> str:
        """Adiciona multiplas tags a um card de uma vez.
        Mais eficiente que adicionar uma por uma."""
        ids = json.loads(tag_ids)
        results = []
        errors = []
        for tag_id in ids:
            resp = client.post(f"/tags/{card_uuid}/{tag_id}")
            if isinstance(resp, dict) and resp.get("error"):
                errors.append(f"tag {tag_id}: {resp.get('message', 'erro')}")
            else:
                results.append(tag_id)

        output = {
            "success": len(errors) == 0,
            "tags_added": results,
            "total_added": len(results),
        }
        if errors:
            output["errors"] = errors
        # Retorna as tags atuais do card (ultima resposta da API)
        if isinstance(resp, list):
            output["current_tags"] = resp
        return json.dumps(output, ensure_ascii=False, default=str)

    def mover_card_simples(
        card_uuid: str = Field(description="UUID do card a mover"),
        project_uuid: str = Field(description="UUID do projeto"),
        list_id_destino: int = Field(description="ID da lista/coluna de destino"),
    ) -> str:
        """Move um card para outra coluna do Kanban de forma simplificada.
        Busca automaticamente os cards da coluna de destino e monta a ordem.
        Nao precisa informar cards_order manualmente."""
        # 1. Busca o kanban para saber os cards da lista destino
        kanban = client.get(f"/cards/{project_uuid}/kanban", {"order": "asc"})
        if isinstance(kanban, dict) and kanban.get("error"):
            return json.dumps(kanban, ensure_ascii=False, default=str)

        # 2. Encontra os cards da lista destino
        target_cards = []
        lists_data = kanban.get("lists", kanban) if isinstance(kanban, dict) else kanban
        if isinstance(lists_data, dict):
            lists_data = lists_data.get("lists", [])

        for lst in lists_data:
            if lst.get("id") == list_id_destino:
                for c in lst.get("cards", []):
                    card_u = c.get("uuid", c.get("card_uuid", ""))
                    if card_u:
                        target_cards.append(card_u)
                break

        # 3. Monta a nova ordem: cards existentes + card movido no final
        cards_order = []
        order_idx = 1
        for existing_uuid in target_cards:
            if existing_uuid != card_uuid:  # Evita duplicar se ja estiver la
                cards_order.append({"uuid": existing_uuid, "order": order_idx})
                order_idx += 1
        cards_order.append({"uuid": card_uuid, "order": order_idx})

        # 4. Move
        data = client.patch(
            f"/cards/mover/{card_uuid}/{list_id_destino}",
            {"cards_order": cards_order},
        )
        return json.dumps(data, ensure_ascii=False, default=str)

    def qualificar_lead(
        card_uuid: str = Field(description="UUID do card/lead"),
        project_uuid: str = Field(description="UUID do projeto"),
        list_id_destino: int = Field(description="ID da lista/coluna de destino (ex: 'Ganho', 'Fechado')"),
        status: str = Field("ganho", description="Resultado: 'ganho' ou 'perdido'"),
        valor_oportunidade: Optional[float] = Field(None, description="Valor da oportunidade em R$"),
        tag_ids: Optional[str] = Field(None, description="JSON array de IDs de tags a adicionar (ex: [2, 5])"),
    ) -> str:
        """Qualifica um lead de forma completa em uma unica chamada:
        1. Move o card para a coluna de destino
        2. Registra o resultado (ganho/perdido) com valor
        3. Opcionalmente adiciona tags
        Ideal para quando o lead fecha negocio ou e descartado."""
        results = {"steps": []}

        # Step 1: Mover card (busca kanban automaticamente)
        kanban = client.get(f"/cards/{project_uuid}/kanban", {"order": "asc"})
        if isinstance(kanban, dict) and kanban.get("error"):
            return json.dumps({"error": True, "message": "Falha ao buscar kanban", "detail": kanban})

        target_cards = []
        lists_data = kanban.get("lists", kanban) if isinstance(kanban, dict) else kanban
        if isinstance(lists_data, dict):
            lists_data = lists_data.get("lists", [])

        for lst in lists_data:
            if lst.get("id") == list_id_destino:
                for c in lst.get("cards", []):
                    card_u = c.get("uuid", c.get("card_uuid", ""))
                    if card_u:
                        target_cards.append(card_u)
                break

        cards_order = []
        order_idx = 1
        for existing_uuid in target_cards:
            if existing_uuid != card_uuid:
                cards_order.append({"uuid": existing_uuid, "order": order_idx})
                order_idx += 1
        cards_order.append({"uuid": card_uuid, "order": order_idx})

        move_resp = client.patch(
            f"/cards/mover/{card_uuid}/{list_id_destino}",
            {"cards_order": cards_order},
        )
        results["steps"].append({"action": "mover", "success": not (isinstance(move_resp, dict) and move_resp.get("error"))})

        # Step 2: Registrar resultado
        resultado_body: dict = {"card_uuid": card_uuid, "status": status}
        if valor_oportunidade is not None:
            resultado_body["valor_oportunidade"] = valor_oportunidade
        resultado_resp = client.post("/cards/resultado", resultado_body)
        results["steps"].append({"action": "resultado", "success": not (isinstance(resultado_resp, dict) and resultado_resp.get("error"))})
        if isinstance(resultado_resp, dict) and not resultado_resp.get("error"):
            results["lead_resultado"] = resultado_resp.get("lead_resultado", resultado_resp)

        # Step 3: Tags (opcional)
        if tag_ids:
            ids = json.loads(tag_ids)
            tags_ok = 0
            for tid in ids:
                resp = client.post(f"/tags/{card_uuid}/{tid}")
                if not (isinstance(resp, dict) and resp.get("error")):
                    tags_ok += 1
            results["steps"].append({"action": "tags", "added": tags_ok, "total": len(ids)})

        results["success"] = all(s.get("success", True) for s in results["steps"])
        return json.dumps(results, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(preencher_crm, name="attlas_preencher_crm"),
        StructuredTool.from_function(adicionar_tags, name="attlas_adicionar_tags_batch"),
        StructuredTool.from_function(mover_card_simples, name="attlas_mover_card_simples"),
        StructuredTool.from_function(qualificar_lead, name="attlas_qualificar_lead"),
    ]
