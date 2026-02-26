"""
tools_products.py - Tools de Produtos do Attlas CRM.

Endpoints cobertos:
  POST /cards/{card}/produtos/criar     - Criar produtos
  POST /cards/{card}/produtos/vincular  - Vincular produtos (confirmar venda)
"""

import json
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def criar_produtos(
        card_uuid: str = Field(description="UUID do card"),
        products: str = Field(
            description='JSON array de produtos. Cada produto: '
            '{"name": "Produto X", "price": 100.0, "quantity": 2, "discount_percentage": 10, "total_value": 180.0}'
        ),
    ) -> str:
        """Cria e associa produtos a um card com status 'em fila' (cotado).
        Calcula automaticamente desconto e atualiza valor de oportunidade."""
        body = {"products": json.loads(products)}
        data = client.post(f"/cards/{card_uuid}/produtos/criar", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def vincular_produtos(
        card_uuid: str = Field(description="UUID do card"),
        ids: str = Field(description="JSON array de IDs dos produtos a vincular (ex: [1, 2, 3])"),
    ) -> str:
        """Vincula produtos ao card (muda status de 'em fila' para 'vinculado').
        Confirma a venda: atualiza valor de oportunidade e registra resultado como 'ganho'."""
        body = {"ids": json.loads(ids)}
        data = client.post(f"/cards/{card_uuid}/produtos/vincular", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(criar_produtos, name="attlas_criar_produtos"),
        StructuredTool.from_function(vincular_produtos, name="attlas_vincular_produtos"),
    ]
