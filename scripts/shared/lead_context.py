"""
lead_context.py - Contexto de Lead por Conversa (Redis)

Quando um formulário externo envia dados (nome, telefone, respostas),
este módulo armazena o contexto no Redis vinculado ao chat_id.

O rag_worker.py lê esse contexto e injeta no system_prompt antes
de chamar a IA, para que ela saiba o que a pessoa já preencheu.

Chave Redis: lead_context:{client_id}:{chat_id}
TTL padrão: 48 horas (configurável)
"""

import json
import logging
from typing import Optional

import redis

logger = logging.getLogger("LeadContext")

# TTL padrão: 48 horas
DEFAULT_TTL = 48 * 60 * 60

_KEY_PREFIX = "lead_context"


def _key(client_id: str, chat_id: str) -> str:
    return f"{_KEY_PREFIX}:{client_id}:{chat_id}"


def save_lead_context(
    redis_url: str,
    client_id: str,
    chat_id: str,
    context_data: dict,
    ttl: int = DEFAULT_TTL,
) -> bool:
    """
    Salva contexto do lead no Redis.

    Args:
        redis_url: URL de conexão Redis
        client_id: ID do cliente (tenant) no aiahub
        chat_id: ID do chat WhatsApp (telefone)
        context_data: Dict com dados do formulário. Exemplo:
            {
                "nome": "João Silva",
                "source": "Landing Page Vendas",
                "respostas": {
                    "Interesse": "Plano Premium",
                    "Orçamento": "R$ 5.000",
                    "Prazo": "Este mês"
                }
            }
        ttl: Tempo de vida em segundos (padrão: 48h)

    Returns:
        True se salvou com sucesso
    """
    try:
        r = redis.Redis.from_url(redis_url, decode_responses=True)
        key = _key(client_id, chat_id)
        r.set(key, json.dumps(context_data, ensure_ascii=False), ex=ttl)
        r.close()
        logger.info(f"📋 Contexto salvo para {chat_id} (client {client_id}, TTL={ttl}s)")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao salvar contexto do lead: {e}")
        return False


def get_lead_context(
    redis_url: str,
    client_id: str,
    chat_id: str,
) -> Optional[dict]:
    """
    Lê o contexto do lead do Redis (se existir).

    Returns:
        Dict com os dados ou None se não houver contexto.
    """
    try:
        r = redis.Redis.from_url(redis_url, decode_responses=True)
        key = _key(client_id, chat_id)
        raw = r.get(key)
        r.close()
        if raw:
            return json.loads(raw)
        return None
    except Exception as e:
        logger.error(f"❌ Erro ao ler contexto do lead: {e}")
        return None


def clear_lead_context(
    redis_url: str,
    client_id: str,
    chat_id: str,
) -> bool:
    """Remove o contexto do lead do Redis."""
    try:
        r = redis.Redis.from_url(redis_url, decode_responses=True)
        key = _key(client_id, chat_id)
        r.delete(key)
        r.close()
        logger.info(f"🗑️ Contexto removido para {chat_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao remover contexto: {e}")
        return False


def format_context_for_prompt(context_data: dict) -> str:
    """
    Formata o contexto do lead para injeção no system_prompt.

    Transforma o dict em texto legível para a IA.
    """
    parts = []
    parts.append("📋 **CONTEXTO DO LEAD (Formulário Preenchido)**")
    parts.append("O usuário já preencheu um formulário ANTES de iniciar esta conversa.")
    parts.append("Use essas informações para dar continuidade — NÃO pergunte o que ele já respondeu.\n")

    nome = context_data.get("nome")
    if nome:
        parts.append(f"**Nome:** {nome}")

    source = context_data.get("source")
    if source:
        parts.append(f"**Origem:** {source}")

    # Respostas do formulário
    respostas = context_data.get("respostas", {})
    if respostas:
        parts.append("\n**Respostas do Formulário:**")
        if isinstance(respostas, dict):
            for campo, valor in respostas.items():
                parts.append(f"  - {campo}: {valor}")
        elif isinstance(respostas, str):
            # Suporte a form_data como string formatada (Campo::Valor)
            for line in respostas.split("\n"):
                line = line.strip()
                if line:
                    parts.append(f"  - {line}")

    # Campos extras (qualquer chave que não seja nome/source/respostas)
    extras = {
        k: v
        for k, v in context_data.items()
        if k not in ("nome", "source", "respostas") and v
    }
    if extras:
        parts.append("\n**Dados Adicionais:**")
        for campo, valor in extras.items():
            parts.append(f"  - {campo}: {valor}")

    parts.append("\n👉 Continue o atendimento a partir dessas informações.")
    return "\n".join(parts)
