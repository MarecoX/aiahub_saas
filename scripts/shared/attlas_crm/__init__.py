"""
attlas_crm - Módulo de integração com o Attlas CRM.

Permite que a IA controle todo o CRM de um cliente via API REST:
  - Projetos (pipelines/funis)
  - Listas (colunas/etapas do Kanban)
  - Cards (leads/tarefas) - CRUD completo + bulk ops
  - Lead Scoring (pontuação manual + histórico)
  - Comentários (threads, menções)
  - Tags (etiquetas)
  - Participantes de cards
  - Vínculos entre cards
  - Checklists + templates
  - Produtos (criar, vincular/confirmar venda)
  - Workflows (automações com regras e ações)
  - Integrações API (tokens, webhooks)

Total: 62 tools organizadas em 13 módulos (inclui 4 atalhos compostos).

Uso:
    from attlas_crm import get_attlas_crm_tools
    tools = get_attlas_crm_tools({"base_url": "https://empresa.attlascrm.com", "token": "..."})
"""

import logging
from .client import build_client

logger = logging.getLogger("AttlasCRM")


def get_attlas_crm_tools(config: dict) -> list:
    """
    Retorna todas as LangChain tools do Attlas CRM.

    Args:
        config: Dict com:
            - base_url (str): URL base do tenant (ex: https://empresa.attlascrm.com)
            - token (str): Token Sanctum (Bearer)

    Returns:
        Lista de StructuredTool prontas para o LLM
    """
    client = build_client(config)
    tools = []

    # Import e carregamento de cada módulo
    modules = [
        "tools_projects",
        "tools_lists",
        "tools_cards",
        "tools_score",
        "tools_comments",
        "tools_tags",
        "tools_participants",
        "tools_bindings",
        "tools_checklists",
        "tools_products",
        "tools_workflows",
        "tools_integrations",
        "tools_shortcuts",
    ]

    for module_name in modules:
        try:
            mod = __import__(f"attlas_crm.{module_name}", fromlist=["_get_tools"])
            module_tools = mod._get_tools(client)
            tools.extend(module_tools)
            logger.info(f"✅ AttlasCRM.{module_name}: {len(module_tools)} tools carregadas")
        except Exception as e:
            logger.error(f"❌ AttlasCRM.{module_name}: Falha ao carregar - {e}")

    logger.info(f"🏢 AttlasCRM: Total de {len(tools)} tools carregadas")
    return tools
