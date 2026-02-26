"""
tools_comments.py - Tools de Comentários do Attlas CRM.

Endpoints cobertos:
  GET    /cards/{card}/comentarios      - Listar comentarios
  POST   /cards/{card}/comentarios      - Criar comentario
  DELETE /cards/comentarios/{comment}   - Excluir comentario
"""

import json
from typing import Optional
from langchain_core.tools import StructuredTool
from pydantic import Field

from .client import AttlasCRMClient


def _get_tools(client: AttlasCRMClient) -> list:

    def listar_comentarios(
        card_uuid: str = Field(description="UUID do card"),
    ) -> str:
        """Lista todos os comentarios de um card, incluindo respostas, mencoes e reacoes."""
        data = client.get(f"/cards/{card_uuid}/comentarios")
        return json.dumps(data, ensure_ascii=False, default=str)

    def criar_comentario(
        card_uuid: str = Field(description="UUID do card"),
        content: str = Field(description="Conteudo do comentario"),
        replying_to: Optional[int] = Field(None, description="ID do comentario sendo respondido (para threads)"),
        mentions: Optional[str] = Field(None, description="JSON array de IDs de usuarios mencionados"),
        is_external: bool = Field(False, description="Se o comentario e externo/publico"),
    ) -> str:
        """Cria um comentario em um card. Suporta respostas em thread, mencoes e marcacao como externo."""
        body: dict = {"content": content}
        if replying_to:
            body["replyingTo"] = replying_to
        if mentions:
            body["mentions"] = json.loads(mentions)
        if is_external:
            body["is_external"] = True
        data = client.post(f"/cards/{card_uuid}/comentarios", body)
        return json.dumps(data, ensure_ascii=False, default=str)

    def excluir_comentario(
        comment_id: int = Field(description="ID do comentario a excluir"),
    ) -> str:
        """Exclui um comentario e todas as suas respostas. Apenas o autor pode excluir."""
        data = client.delete(f"/cards/comentarios/{comment_id}")
        return json.dumps(data, ensure_ascii=False, default=str)

    return [
        StructuredTool.from_function(listar_comentarios, name="attlas_listar_comentarios"),
        StructuredTool.from_function(criar_comentario, name="attlas_criar_comentario"),
        StructuredTool.from_function(excluir_comentario, name="attlas_excluir_comentario"),
    ]
