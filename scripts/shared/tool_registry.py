"""
tool_registry.py - Catalogo Declarativo de Tools do SaaS

PRINCIPIO: Toda metadata de uma tool fica AQUI.
A UI (tools_tab.py) e o backend (get_enabled_tools) leem deste registro.

Estrutura de cada entrada:
  - label: Nome amigavel para exibir na UI
  - category: Categoria logica (generic, crm, isp, rag, scheduling, workflow)
  - applicable_to: Lista de business_types que podem usar. ["*"] = todos
  - has_instructions: Se a UI deve mostrar campo "Instrucoes para a IA"
  - config_fields: Campos de configuracao que aparecem na UI quando ativo
  - credential_source: De onde vem as credenciais:
      - None: Sem credenciais
      - "config": Credenciais ficam dentro do proprio tools_config[tool_name]
      - "provider:<type>": Credenciais do client_providers (ex: "provider:uazapi")
  - wrapper_type: Como o wrapper eh criado em get_enabled_tools:
      - "simple": Tool sem dependencias, ativa diretamente
      - "inject_config": Injeta config_dict na kwarg especifica (ex: kommo_config)
      - "inject_runtime": Injeta chat_id, redis_url, client_id em runtime
      - "custom": Wrapper complexo demais, mantem logica dedicada
  - inject_kwarg_name: Para wrapper_type="inject_config", nome da kwarg
  - runtime_kwargs: Para wrapper_type="inject_runtime", quais kwargs de runtime injetar
  - provider_badge: Compatibilidade com providers (exibido na UI)
"""

import logging

logger = logging.getLogger("KestraToolRegistry")


# Tipos de negocio suportados
BUSINESS_TYPES = {
    "generic": "\U0001f527 Generico",
    "isp": "\U0001f310 Provedor de Internet (ISP)",
    "varejo": "\U0001f6d2 Varejo / Loja",
    "servicos": "\U0001f4bc Servicos / Consultoria",
    "food": "\U0001f355 Foodservice / Restaurante",
    "saude": "\U0001f3e5 Saude / Clinica",
}


TOOL_REGISTRY = {
    # ── RAG (Base de Conhecimento) ──
    "rag_active": {
        "label": "\U0001f4da Base de Conhecimento (RAG)",
        "category": "rag",
        "applicable_to": ["*"],
        "has_instructions": False,
        "config_fields": {},
        "credential_source": None,
        "wrapper_type": "custom",
        "provider_badge": "\U0001f7e2 Todos",
        "default_active": True,
        "ui_help": "Se ativado, a IA consultara seus documentos (manuais, PDFs) antes de responder.",
        "ui_section": "header",
    },
    # ── Consulta CEP (Generico) ──
    "consultar_cep": {
        "label": "\U0001f4cd Consulta de Endereco (CEP)",
        "category": "generic",
        "applicable_to": ["*"],
        "has_instructions": False,
        "config_fields": {},
        "credential_source": None,
        "wrapper_type": "simple",
        "provider_badge": "\U0001f7e2 Todos",
        "ui_help": "Permite que a IA consulte enderecos automaticamente a partir do CEP informado pelo cliente.",
        "ui_caption": "Esta integracao utiliza servicos publicos (ViaCEP/BrasilAPI). Nenhuma configuracao extra e necessaria.",
    },
    # ── Relatorio (Semi-generico) ──
    "enviar_relatorio": {
        "label": "\U0001f4e4 Enviar Relatorio para Grupo",
        "category": "workflow",
        "applicable_to": ["*"],
        "has_instructions": True,
        "config_fields": {
            "grupo_id": {
                "type": "text",
                "label": "ID do Grupo WhatsApp",
                "help": "Ex: 5511999999999-1234567890@g.us (obtenha via Uazapi)",
            },
            "template": {
                "type": "textarea",
                "label": "Template da Mensagem (Opcional)",
                "placeholder": "Ex: *Novo Pedido* \\n Telefone: {{telefone}} \\n Resumo: {{resumo_da_solicitacao}}",
                "help": "Use {{campo}} para inserir dados. {{telefone}} e preenchido automaticamente. Minimo: 2 campos.",
            },
        },
        "credential_source": "provider:uazapi",
        "wrapper_type": "custom",
        "provider_badge": "\U0001f7e2 Uazapi",
        "instructions_placeholder": "Ex: Envie relatorio quando o cliente confirmar pedido, reservar produto, ou fechar negocio...",
    },
    # ── Atendimento Humano (Generico) ──
    "atendimento_humano": {
        "label": "\U0001f9d1\u200d\U0001f4bc Atendimento Humano",
        "category": "generic",
        "applicable_to": ["*"],
        "has_instructions": True,
        "config_fields": {
            "timeout_minutes": {
                "type": "number",
                "label": "Duracao do Modo Humano (minutos)",
                "default": 60,
                "min": 5,
                "max": 1440,
                "help": "Tempo que a IA ficara pausada apos transferir para humano.",
            },
            "permanent_on_human_reply": {
                "type": "toggle",
                "label": "Parar IA permanentemente ao responder",
                "default": False,
                "help": "Se ativado, quando o atendente humano enviar qualquer mensagem, a IA para PERMANENTEMENTE naquele chat (sem timeout). Para reativar, use #ativar.",
            },
        },
        "credential_source": None,
        "wrapper_type": "inject_runtime",
        "runtime_kwargs": {
            "chat_id": "chat_id",
            "timeout_minutes": "config:timeout_minutes",
            "redis_url": "env:REDIS_URL",
        },
        "provider_badge": "\U0001f7e2 Uazapi | \U0001f7e2 Meta | \U0001f7e2 Lancepilot",
        "instructions_placeholder": "Ex: Transfira para humano quando o cliente pedir entrega, solicitar desconto, ou perguntar sobre garantia...",
    },
    # ── Desativar IA (Generico) ──
    "desativar_ia": {
        "label": "\U0001f6d1 Desativar IA (Opt-out)",
        "category": "generic",
        "applicable_to": ["*"],
        "has_instructions": True,
        "config_fields": {},
        "credential_source": None,
        "wrapper_type": "inject_runtime",
        "runtime_kwargs": {
            "chat_id": "chat_id",
            "redis_url": "env:REDIS_URL",
        },
        "provider_badge": "\U0001f7e2 Uazapi | \U0001f7e1 Meta (parcial) | \U0001f7e1 Lancepilot (parcial)",
        "ui_help": "Permite que o cliente pare a IA definitivamente com um comando ou emoji.",
        "instructions_label": "Gatilhos de Parada (Emojis ou Frases)",
        "instructions_placeholder": "Ex: Se o cliente enviar PARE ou STOP, desative a IA permanentemente.",
    },
    # ── Criar Lembrete (Generico) ──
    "criar_lembrete": {
        "label": "\U0001f4c5 Criar Lembrete (Follow-up Agendado)",
        "category": "generic",
        "applicable_to": ["*"],
        "has_instructions": False,
        "config_fields": {},
        "credential_source": None,
        "wrapper_type": "inject_runtime",
        "runtime_kwargs": {
            "chat_id": "chat_id",
            "client_id": "client_id",
        },
        "provider_badge": "\U0001f7e2 Uazapi | \U0001f7e1 Meta (via Template) | \U0001f7e1 Lancepilot (via Template)",
        "ui_help": "Permite que a IA agende lembretes para retornar contato com o cliente.",
        "ui_active_info": "A IA entendera frases como: 'amanha', 'semana que vem', 'em 3 dias', 'dia 15'.",
    },
    # ── Kommo CRM (Provedores/Servicos) ──
    "qualificado_kommo_provedor": {
        "label": "\U0001f4ca Qualificacao de Lead (Kommo CRM)",
        "category": "crm",
        "applicable_to": ["isp", "servicos", "saude"],
        "has_instructions": False,
        "config_fields": {
            "url": {
                "type": "text",
                "label": "URL Base (ex: https://dominio.kommo.com)",
            },
            "token": {
                "type": "password",
                "label": "Token de Autorizacao (Bearer ...)",
            },
            "pipeline_id": {
                "type": "text",
                "label": "Pipeline ID (Opcional)",
            },
            "status_id": {
                "type": "text",
                "label": "Status ID (Lead Qualificado)",
            },
        },
        "credential_source": "config",
        "wrapper_type": "inject_config",
        "inject_kwarg_name": "kommo_config",
        "ui_caption": "Ao preencher o Status ID, o assistente movera o card automaticamente quando qualificado.",
    },
    # ── Betel ERP (Varejo) ──
    "consultar_erp": {
        "label": "\U0001f6d2 Betel ERP (Consulta de Produtos)",
        "category": "erp",
        "applicable_to": ["varejo"],
        "has_instructions": False,
        "config_fields": {
            "loja_id": {"type": "text", "label": "ID da Loja"},
            "access_token": {"type": "password", "label": "Access Token"},
            "secret_token": {"type": "password", "label": "Secret Token"},
        },
        "credential_source": "config",
        "wrapper_type": "inject_config",
        "inject_kwarg_name": "betel_config",
    },
    # ── HubSoft Viabilidade (ISP) ──
    "consultar_viabilidade_hubsoft": {
        "label": "\U0001f310 HubSoft - Consulta de Viabilidade",
        "category": "isp",
        "applicable_to": ["isp"],
        "has_instructions": False,
        "config_fields": {
            "api_url": {
                "type": "text",
                "label": "URL da API HubSoft",
                "placeholder": "https://api.seuprovedor.hubsoft.com.br",
            },
            "client_id": {"type": "text", "label": "Client ID"},
            "client_secret": {"type": "password", "label": "Client Secret"},
            "username": {"type": "text", "label": "Username (E-mail)"},
            "password": {"type": "password", "label": "Password"},
            "raio": {
                "type": "select",
                "label": "Raio de Busca (metros)",
                "options": [250, 500, 750, 1000, 1250, 1500],
                "default": 250,
            },
            "detalhar_portas": {
                "type": "toggle",
                "label": "Detalhar Portas",
                "default": False,
                "help": "Se ativado, retorna detalhes das portas disponiveis/ocupadas.",
            },
        },
        "credential_source": "config",
        "wrapper_type": "inject_config",
        "inject_kwarg_name": "hubsoft_config",
        "ui_caption": "Dica: Adicione no prompt da IA instrucoes para sempre perguntar o numero da residencia antes de consultar viabilidade.",
    },
    # ── HubSoft Consultar Cliente (ISP) ──
    "consultar_cliente_hubsoft": {
        "label": "\U0001f50d HubSoft - Consultar Cliente",
        "category": "isp",
        "applicable_to": ["isp"],
        "has_instructions": False,
        "config_fields": {},
        "credential_source": "config",
        "wrapper_type": "inject_config",
        "inject_kwarg_name": "hubsoft_config",
        "config_source": "consultar_viabilidade_hubsoft",
        "ui_help": "Consulta dados cadastrais do cliente por CPF/CNPJ via API HubSoft.",
        "ui_caption": "Usa as mesmas credenciais da ferramenta HubSoft Viabilidade.",
    },
    # ── HubSoft Consultar Financeiro (ISP) ──
    "consultar_financeiro_hubsoft": {
        "label": "\U0001f4b0 HubSoft - Consultar Financeiro",
        "category": "isp",
        "applicable_to": ["isp"],
        "has_instructions": False,
        "config_fields": {},
        "credential_source": "config",
        "wrapper_type": "inject_config",
        "inject_kwarg_name": "hubsoft_config",
        "config_source": "consultar_viabilidade_hubsoft",
        "ui_help": "Consulta faturas pendentes do cliente por CPF/CNPJ via API HubSoft.",
        "ui_caption": "Usa as mesmas credenciais da ferramenta HubSoft Viabilidade.",
    },
    # ── HubSoft Desbloqueio de Confianca (ISP) ──
    "desbloqueio_de_confianca_hubsoft": {
        "label": "\U0001f513 HubSoft - Desbloqueio de Confianca",
        "category": "isp",
        "applicable_to": ["isp"],
        "has_instructions": False,
        "config_fields": {
            "dias_desbloqueio": {
                "type": "select",
                "label": "Dias de Desbloqueio",
                "options": [1, 2, 3, 5, 7, 10, 15, 30],
                "default": 3,
                "help": "Quantidade de dias para o desbloqueio de confianca.",
            },
        },
        "credential_source": "config",
        "wrapper_type": "inject_config",
        "inject_kwarg_name": "hubsoft_config",
        "config_source": "consultar_viabilidade_hubsoft",
        "ui_help": "Realiza desbloqueio de confianca do servico do cliente.",
        "ui_caption": "Usa as mesmas credenciais da ferramenta HubSoft Viabilidade. O id_cliente_servico e obtido automaticamente pela consulta de cliente.",
    },
    # ── Cal.com (Agendamento) ──
    "cal_dot_com": {
        "label": "\U0001f4c5 Cal.com (Agendamento)",
        "category": "scheduling",
        "applicable_to": ["*"],
        "has_instructions": False,
        "config_fields": {
            "api_key": {
                "type": "password",
                "label": "API Key (v2)",
                "help": "Chave de API do Cal.com (Configuracoes > API Keys).",
            },
            "event_type_id": {
                "type": "text",
                "label": "Event Type ID",
                "help": "ID do tipo de evento a ser agendado.",
            },
        },
        "credential_source": "config",
        "wrapper_type": "custom",
        "ui_caption": "A IA podera: Consultar Agenda, Agendar, Remarcar e Cancelar.",
    },
    # ── WhatsApp Reactions (Generico) ──
    "whatsapp_reactions": {
        "label": "\U0001f44d Reacoes (Emojis)",
        "category": "whatsapp",
        "applicable_to": ["*"],
        "has_instructions": True,
        "config_fields": {},
        "credential_source": "provider:uazapi",
        "wrapper_type": "custom",
        "ui_section": "whatsapp_advanced",
        "ui_help": "Permite que a IA reaja as mensagens do cliente com emojis.",
        "instructions_placeholder": "Ex: Reaja com olhos em toda mensagem nova. Use positivo quando cliente confirmar algo.",
    },
    # ── SGP Tools (ISP) ──
    "sgp_tools": {
        "label": "\U0001f527 SGP (Vendas + Suporte)",
        "category": "isp",
        "applicable_to": ["isp"],
        "has_instructions": False,
        "config_fields": {
            "sgp_url": {"type": "text", "label": "URL do SGP"},
            "sgp_token": {"type": "password", "label": "Token SGP"},
            "sgp_app": {"type": "text", "label": "Nome do Aplicativo"},
        },
        "credential_source": "config",
        "wrapper_type": "custom",
        "ui_help": "Viabilidade, Pre-Cadastro, Verificar Cliente (CPF/CNPJ), Segunda Via de Fatura e PIX.",
    },
}


def get_tools_for_business_type(business_type: str) -> dict:
    """
    Filtra o registry retornando apenas tools aplicaveis ao tipo de negocio.

    Args:
        business_type: Tipo de negocio do cliente (ex: 'isp', 'food', 'generic')

    Returns:
        dict: Subconjunto do TOOL_REGISTRY filtrado
    """
    return {
        tool_id: meta
        for tool_id, meta in TOOL_REGISTRY.items()
        if "*" in meta["applicable_to"] or business_type in meta["applicable_to"]
    }
