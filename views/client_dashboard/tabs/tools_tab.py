"""
tools_tab.py - UI de Ferramentas e Integracoes (Auto-gerada do TOOL_REGISTRY)

Este modulo renderiza a aba de "Ferramentas" no dashboard do cliente.
A UI e gerada dinamicamente a partir do TOOL_REGISTRY, eliminando codigo duplicado.
Secoes especiais (LancePilot, WhatsApp Avancado, Seguranca, Debug) permanecem manuais.
"""

import os
import sys
import json
import streamlit as st

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import (  # noqa: E402
    get_connection,
    get_provider_config,
    upsert_provider_config,
)
from scripts.shared.tool_registry import TOOL_REGISTRY, get_tools_for_business_type  # noqa: E402

# Backward compat: Map de keys antigas -> keys novas
_KEY_ALIASES = {
    "consultar_erp": "consultar_produtos_betel",  # UI antiga salvava com esse nome
}


# ─── Generic Field Renderer ───────────────────────────────────────────────


def _render_config_fields(
    tool_name: str, config_fields: dict, current_cfg: dict
) -> dict:
    """
    Renderiza campos de configuracao baseado nos metadados do registry.
    Retorna dict com os valores preenchidos pelo usuario.

    Suporta tipos: text, password, textarea, number, select, toggle
    """
    values = {}
    field_items = list(config_fields.items())

    # Agrupa campos em colunas de 2 (exceto textarea/toggle que ocupa linha inteira)
    i = 0
    while i < len(field_items):
        field_name, field_meta = field_items[i]
        ftype = field_meta.get("type", "text")
        wkey = f"{tool_name}_{field_name}"  # Unique Streamlit widget key

        if ftype in ("textarea",):
            values[field_name] = st.text_area(
                field_meta.get("label", field_name),
                value=current_cfg.get(field_name, ""),
                height=field_meta.get("height", 80),
                placeholder=field_meta.get("placeholder", ""),
                help=field_meta.get("help", None),
                key=wkey,
            )
            i += 1

        elif ftype == "toggle":
            values[field_name] = st.toggle(
                field_meta.get("label", field_name),
                value=current_cfg.get(field_name, field_meta.get("default", False)),
                help=field_meta.get("help", None),
                key=wkey,
            )
            i += 1

        elif ftype == "select":
            options = field_meta.get("options", [])
            current_val = current_cfg.get(
                field_name, field_meta.get("default", options[0] if options else "")
            )
            idx = options.index(current_val) if current_val in options else 0
            values[field_name] = st.selectbox(
                field_meta.get("label", field_name),
                options=options,
                index=idx,
                help=field_meta.get("help", None),
                key=wkey,
            )
            i += 1

        elif ftype == "number":
            values[field_name] = st.number_input(
                field_meta.get("label", field_name),
                min_value=field_meta.get("min", 0),
                max_value=field_meta.get("max", 9999),
                value=int(current_cfg.get(field_name, field_meta.get("default", 0))),
                help=field_meta.get("help", None),
                key=wkey,
            )
            i += 1

        else:
            # text or password: try to pair with next field for 2-column layout
            if i + 1 < len(field_items) and field_items[i + 1][1].get(
                "type", "text"
            ) in ("text", "password"):
                next_name, next_meta = field_items[i + 1]
                next_key = f"{tool_name}_{next_name}"
                col1, col2 = st.columns(2)
                with col1:
                    values[field_name] = st.text_input(
                        field_meta.get("label", field_name),
                        value=current_cfg.get(field_name, ""),
                        type="password" if ftype == "password" else "default",
                        help=field_meta.get("help", None),
                        placeholder=field_meta.get("placeholder", ""),
                        key=wkey,
                    )
                with col2:
                    ntype = next_meta.get("type", "text")
                    values[next_name] = st.text_input(
                        next_meta.get("label", next_name),
                        value=current_cfg.get(next_name, ""),
                        type="password" if ntype == "password" else "default",
                        help=next_meta.get("help", None),
                        placeholder=next_meta.get("placeholder", ""),
                        key=next_key,
                    )
                i += 2
            else:
                values[field_name] = st.text_input(
                    field_meta.get("label", field_name),
                    value=current_cfg.get(field_name, ""),
                    type="password" if ftype == "password" else "default",
                    help=field_meta.get("help", None),
                    placeholder=field_meta.get("placeholder", ""),
                    key=wkey,
                )
                i += 1

    return values


def _render_tool_section(tool_name: str, meta: dict, t_config: dict) -> tuple:
    """
    Renderiza uma secao de tool completa (header, toggle, campos, instrucoes).
    Retorna (is_active, config_dict) para salvar depois.
    """
    # Load existing config (com backward compat para keys antigas)
    current_cfg = t_config.get(tool_name, {})
    if not current_cfg and tool_name in _KEY_ALIASES:
        current_cfg = t_config.get(_KEY_ALIASES[tool_name], {})
    if isinstance(current_cfg, bool):
        current_cfg = {"active": current_cfg}

    # Special: RAG has default=True
    default_active = meta.get("default_active", False)

    # Header
    st.subheader(meta["label"])

    # Provider badge
    badge = meta.get("provider_badge")
    if badge:
        st.caption(badge)

    # Toggle
    is_active = st.toggle(
        f"Ativar {meta['label']}",
        value=current_cfg.get("active", default_active),
        help=meta.get("ui_help", None),
        key=f"toggle_{tool_name}",
    )

    # Config fields + instructions (shown only when active)
    field_values = {}
    instructions_value = ""

    if is_active:
        # Active info
        active_info = meta.get("ui_active_info")
        if active_info:
            st.info(active_info)

        # Config fields
        if meta.get("config_fields"):
            field_values = _render_config_fields(
                tool_name, meta["config_fields"], current_cfg
            )

        # Instructions field
        if meta.get("has_instructions"):
            instructions_label = meta.get("instructions_label", "Instrucoes para a IA")
            instructions_value = st.text_area(
                instructions_label,
                value=current_cfg.get("instructions", ""),
                height=100,
                placeholder=meta.get("instructions_placeholder", ""),
                help="Essas instrucoes serao adicionadas ao prompt da IA.",
                key=f"instructions_{tool_name}",
            )

        # Caption
        caption = meta.get("ui_caption")
        if caption:
            st.caption(caption)
    else:
        # When inactive, use empty/default values
        for field_name, field_meta in meta.get("config_fields", {}).items():
            ftype = field_meta.get("type", "text")
            if ftype == "toggle":
                field_values[field_name] = field_meta.get("default", False)
            elif ftype == "number":
                field_values[field_name] = field_meta.get("default", 0)
            elif ftype == "select":
                field_values[field_name] = field_meta.get("default", "")
            else:
                field_values[field_name] = ""

    # Build save dict
    save_dict = {"active": is_active, **field_values}
    if meta.get("has_instructions"):
        save_dict["instructions"] = instructions_value if is_active else ""

    return is_active, save_dict


# ─── Special Sections (not in registry) ───────────────────────────────────


def _render_lancepilot_section(user_data: dict):
    """Renderiza secao LancePilot (provider especial, nao e tool do registry)."""
    st.subheader("LancePilot (WhatsApp Oficial)")

    lp_cfg = get_provider_config(str(user_data["id"]), "lancepilot") or {}
    if not lp_cfg:
        lp_cfg = {
            "token": user_data.get("lancepilot_token", "") or "",
            "workspace_id": user_data.get("lancepilot_workspace_id", "") or "",
            "number": user_data.get("lancepilot_number", "") or "",
            "active": user_data.get("lancepilot_active", False),
        }

    c_lp_active = st.toggle(
        "Ativar Integracao LancePilot",
        value=lp_cfg.get("active", False),
    )

    lp_token = lp_cfg.get("token", "") or ""
    lp_workspace_id = lp_cfg.get("workspace_id", "") or ""
    lp_number = lp_cfg.get("number", "") or ""

    if c_lp_active:
        lp_token = st.text_input(
            "Token LancePilot (API v3)", value=lp_token, type="password"
        )
        lp_number = st.text_input(
            "Numero Conectado (Ex: 5561999999999)",
            value=lp_number,
            help="Este numero sera usado para identificar a origem das mensagens se o Webhook nao tiver token.",
        )

        lp_search = st.text_input(
            "Nome do Workspace (Filtro Obrigatorio)",
            help="Digite o nome exato para buscar seu workspace.",
        )

        if lp_token:
            if st.button("Carregar Workspaces"):
                if not lp_search:
                    st.warning("Digite o nome do Workspace para buscar.")
                else:
                    try:
                        try:
                            from scripts.lancepilot.client import LancePilotClient
                        except ImportError:
                            sys.path.append(root_dir)
                            from scripts.lancepilot.client import LancePilotClient

                        client = LancePilotClient(token=lp_token)
                        data = client.get_workspaces(search_query=lp_search)
                        st.session_state[f"lp_workspaces_{user_data['id']}"] = data
                        if data:
                            st.success(f"Encontrado: {len(data)} workspace(s).")
                        else:
                            st.warning("Nenhum workspace encontrado com este nome.")
                    except Exception as e:
                        st.error(f"Erro ao buscar workspaces: {e}")

        saved_ws_list = st.session_state.get(f"lp_workspaces_{user_data['id']}", [])

        if saved_ws_list:
            ws_options = {
                w["id"]: f"{w['attributes']['name']} ({w['id']})" for w in saved_ws_list
            }
            def_idx = 0
            keys = list(ws_options.keys())
            if lp_workspace_id in keys:
                def_idx = keys.index(lp_workspace_id)

            selected_ws = st.selectbox(
                "Selecione o Workspace",
                options=keys,
                format_func=lambda x: ws_options[x],
                index=def_idx,
            )
            lp_workspace_id = selected_ws
        else:
            lp_workspace_id = st.text_input(
                "ID do Workspace",
                value=lp_workspace_id,
                help="Use a busca acima para preencher.",
            )

        if c_lp_active:
            st.markdown("#### Webhook de Integracao")
            st.info(
                "Copie a URL abaixo e configure no LancePilot (Settings > Webhook):"
            )

            base_kestra = user_data.get("api_url") or "https://SEU-KESTRA-URL.com"
            if "/api" in base_kestra:
                base_kestra = base_kestra.split("/api")[0]

            webhook_url = f"{base_kestra}/api/v1/executions/webhook/company.team/lancepilot_native/lp_webhook"
            st.code(webhook_url, language="text")
            st.caption(
                f"Token do Cliente: {user_data.get('token')} | Identificacao via Numero: {lp_number}"
            )

    return c_lp_active, lp_token, lp_workspace_id, lp_number


def _render_whatsapp_advanced_section(t_config: dict, user_data: dict):
    """Renderiza secao WhatsApp Avancado (Reactions, Humanizado, Seguranca)."""
    st.header("WhatsApp Avancado")
    st.caption("Configure comportamento, reacoes e seguranca do seu numero.")

    # Reactions is in the registry but rendered in a special section
    react_cfg = t_config.get("whatsapp_reactions", {})
    if isinstance(react_cfg, bool):
        react_cfg = {"active": react_cfg}

    with st.expander("Reacoes e Interatividade", expanded=True):
        c_react_active = st.toggle(
            "Ativar Reacoes (Emojis)",
            value=react_cfg.get("active", False),
            help="Permite que a IA reaja as mensagens do cliente com emojis.",
        )
        react_instructions = react_cfg.get("instructions", "")
        if c_react_active:
            react_instructions = st.text_area(
                "Quando reagir?",
                value=react_instructions,
                height=80,
                placeholder="Ex: Reaja com emojis em toda mensagem nova. Use positivo quando cliente confirmar algo.",
                help="Instrua a IA sobre quando e qual emoji usar.",
            )

    # Modo Humanizado
    wa_config = t_config.get("whatsapp", {})
    if t_config.get("split_by_paragraph"):
        wa_config["split_by_paragraph"] = True

    with st.expander("Modo Humanizado (Estilo de Escrita)", expanded=True):
        c_split_active = st.toggle(
            "Picotar Mensagens (Dividir em paragrafos)",
            value=wa_config.get("split_by_paragraph", False),
            help="Se ativado, envia varias mensagens curtas. Se desativado, envia blocos maiores.",
        )
        if c_split_active:
            st.caption(
                "Ativado: Quebra paragrafos (somente quando tiver quebra dupla)."
            )
        else:
            st.caption(
                "Desativado: Agrupa o texto (Listas e quebras simples continuam juntos)."
            )

    # Seguranca
    security_cfg = t_config.get("security_lists", {})
    with st.expander("Seguranca e Controle (Whitelist/Blocklist)", expanded=False):
        col_sec1, col_sec2 = st.columns(2)
        with col_sec1:
            s_whitelist = st.text_area(
                "Permitir APENAS estes (Whitelist)",
                value=security_cfg.get("allowed_numbers", ""),
                placeholder="Ex: 5511999999999",
                help="Se tiver numeros aqui, o robo IGNORA todo o resto.",
                height=100,
            )
        with col_sec2:
            s_blocklist = st.text_area(
                "Bloquear estes (Blocklist)",
                value=security_cfg.get("blocked_numbers", ""),
                placeholder="Ex: 5511777777777",
                help="Estes numeros nunca serao atendidos.",
                height=100,
            )

    return {
        "whatsapp_reactions": {
            "active": c_react_active,
            "instructions": react_instructions if c_react_active else "",
        },
        "whatsapp": {"split_by_paragraph": c_split_active},
        "security_lists": {
            "allowed_numbers": s_whitelist,
            "blocked_numbers": s_blocklist,
        },
    }


def _render_debug_section(user_data: dict):
    """Renderiza secao de debug/teste manual."""
    with st.expander("Ferramentas de Debug / Teste Manual", expanded=False):
        st.write("**Teste de Reacao (Uazapi)**")
        t_chat_id = st.text_input(
            "Chat ID / Remote JID", placeholder="5511999999999@s.whatsapp.net"
        )
        t_msg_id = st.text_input("Message ID", placeholder="3EB0...")
        t_emoji = st.text_input("Emoji", placeholder="")

        if st.button("Enviar Reacao Manual"):
            if not t_chat_id or not t_msg_id:
                st.error("Preencha Chat ID e Message ID.")
            else:
                try:
                    import asyncio

                    try:
                        from scripts.uazapi.uazapi_saas import send_whatsapp_reaction
                    except ImportError:
                        sys.path.append(os.path.join(root_dir, "scripts", "uazapi"))
                        from uazapi_saas import send_whatsapp_reaction

                    api_key = None
                    api_url = None
                    prov = get_provider_config(str(user_data["id"]), "uazapi")
                    if prov:
                        api_key = prov.get("token") or prov.get("key")
                        api_url = prov.get("url")
                    if not api_key:
                        api_key = user_data.get("token")
                        api_url = user_data.get("api_url")

                    st.info(f"Usando URL: {api_url} | Token: ...{str(api_key)[-4:]}")
                    res = asyncio.run(
                        send_whatsapp_reaction(
                            number=t_chat_id,
                            message_id=t_msg_id,
                            emoji=t_emoji,
                            api_key=api_key,
                            base_url=api_url,
                        )
                    )
                    st.success(f"Resultado: {res}")
                except Exception as e:
                    st.error(f"Erro ao enviar: {e}")


# ─── Render Order: defines which registry tools appear in which order ──────

# Tools rendered via registry (in display order)
REGISTRY_TOOL_ORDER = [
    "rag_active",
    "qualificado_kommo_provedor",
    "consultar_erp",
    "consultar_cep",
    "enviar_relatorio",
    "atendimento_humano",
    "desativar_ia",
    "criar_lembrete",
    "consultar_viabilidade_hubsoft",
    "consultar_cliente_hubsoft",
    "consultar_financeiro_hubsoft",
    "desbloqueio_de_confianca_hubsoft",
    "cal_dot_com",
    "sgp_tools",
    "form_context",
    # whatsapp_reactions is rendered in the WhatsApp Advanced section
]


# ─── Main Entry Point ─────────────────────────────────────────────────────


def render_tools_tab(user_data):
    st.header("Ferramentas e Integracoes")
    st.info("Conecte seu assistente a sistemas externos.")

    t_config = user_data.get("tools_config", {})
    if not t_config:
        t_config = {}

    # Filtra tools pelo business_type do cliente
    # Se nao vier do banco (None), assume mode permissivo (mostra tudo) para nao sumir tools
    raw_btype = user_data.get("business_type")

    if raw_btype:
        allowed_tools = get_tools_for_business_type(raw_btype)
        force_show_all = False
    else:
        # Legacy/Migration mode: mostra tudo se nao tiver tipo definido
        allowed_tools = {}
        force_show_all = True

    # Dict to collect all save configs
    save_configs = {}

    # ── Registry Tools (filtradas por business_type) ──
    for tool_name in REGISTRY_TOOL_ORDER:
        if tool_name not in TOOL_REGISTRY:
            continue

        # Smart Fallback: Mostra tool se ja tiver config salva (mesmo que filtro esconda)
        has_saved_config = bool(t_config.get(tool_name))

        if (
            not force_show_all
            and tool_name not in allowed_tools
            and not has_saved_config
        ):
            continue  # Nao aplicavel a esse tipo de negocio

        meta = TOOL_REGISTRY[tool_name]
        is_active, tool_save_dict = _render_tool_section(tool_name, meta, t_config)
        save_configs[tool_name] = tool_save_dict

        # Form Context: mostra webhook URL quando ativo
        if tool_name == "form_context" and is_active:
            st.markdown("#### Webhook de Formulario")
            st.info("Copie a URL abaixo e configure no seu formulario externo (Typeform, landing page, etc.):")
            api_base = os.getenv("API_BASE_URL", "https://api.aiahub.com.br")
            form_webhook_url = f"{api_base}/api/v1/forms/{user_data.get('token')}/submit"
            st.code(form_webhook_url, language="text")
            st.caption(
                "**Metodo:** POST | **Content-Type:** application/json | "
                "**Requisito:** Incluir campo de telefone (phone, telefone, whatsapp, celular)"
            )
            with st.expander("Exemplo de payload", expanded=False):
                st.code(
                    '{\n'
                    '  "nome": "Joao Silva",\n'
                    '  "telefone": "11999999999",\n'
                    '  "interesse": "Plano Premium",\n'
                    '  "orcamento": "R$ 5.000"\n'
                    '}',
                    language="json",
                )

        st.divider()

    # ── LancePilot (special section) ──
    c_lp_active, lp_token, lp_workspace_id, lp_number = _render_lancepilot_section(
        user_data
    )
    st.divider()

    # ── WhatsApp Advanced (reactions, humanized, security) ──
    wa_save = _render_whatsapp_advanced_section(t_config, user_data)
    save_configs.update(wa_save)
    st.divider()

    # ── Debug Section ──
    _render_debug_section(user_data)

    # ── Save Button ──
    if st.button("Salvar Integracoes"):
        new_tools_config = t_config.copy()

        # Merge registry tool configs
        for tool_name, cfg in save_configs.items():
            new_tools_config[tool_name] = cfg

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET tools_config = %s WHERE id = %s",
                        (json.dumps(new_tools_config), user_data["id"]),
                    )

            # Save LancePilot in client_providers
            upsert_provider_config(
                client_id=str(user_data["id"]),
                provider_type="lancepilot",
                config={
                    "token": lp_token if c_lp_active else "",
                    "workspace_id": lp_workspace_id if c_lp_active else "",
                    "number": lp_number if c_lp_active else "",
                    "active": c_lp_active,
                },
                is_active=c_lp_active,
                is_default=(user_data.get("whatsapp_provider") == "lancepilot"),
            )

            user_data["tools_config"] = new_tools_config
            st.success("Configuracoes salvas!")
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
