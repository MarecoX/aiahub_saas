import os
import sys
import streamlit as st

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import (
    get_connection,
    get_provider_config,
    upsert_provider_config,
)  # noqa: E402


def render_tools_tab(user_data):
    st.header("Ferramentas e Integrações")
    st.info("Conecte seu assistente a sistemas externos.")

    # Load Config
    t_config = user_data.get("tools_config", {})
    if not t_config:
        t_config = {}

    # --- Kommo CRM ---
    st.subheader("Kommo CRM")
    kommo_cfg = t_config.get("qualificado_kommo_provedor", {})
    if isinstance(kommo_cfg, bool):
        kommo_cfg = {"active": kommo_cfg}

    c_kommo_active = st.toggle(
        "Ativar Integração Kommo CRM", value=kommo_cfg.get("active", False)
    )

    if c_kommo_active:
        k1, k2 = st.columns(2)
        k_url = k1.text_input(
            "URL Base (ex: https://dominio.kommo.com)",
            value=kommo_cfg.get("url", ""),
        )
        k_token = k2.text_input(
            "Token de Autorização (Bearer ...)",
            value=kommo_cfg.get("token", ""),
            type="password",
        )

        k3, k4 = st.columns(2)
        k_pipeline = k3.text_input(
            "Pipeline ID (Opcional)", value=str(kommo_cfg.get("pipeline_id", ""))
        )
        k_status = k4.text_input(
            "Status ID (Lead Qualificado)",
            value=str(kommo_cfg.get("status_id", "")),
        )

        st.caption(
            "Ao preencher o Status ID, o assistente moverá o card automaticamente quando qualificado."
        )
    else:
        k_url, k_token, k_pipeline, k_status = "", "", "", ""

    st.divider()

    # --- LancePilot ---
    st.subheader("LancePilot (WhatsApp Oficial)")

    # Buscar de client_providers (novo) com fallback para colunas (legado)
    lp_cfg = get_provider_config(str(user_data["id"]), "lancepilot") or {}
    if not lp_cfg:
        lp_cfg = {
            "token": user_data.get("lancepilot_token", "") or "",
            "workspace_id": user_data.get("lancepilot_workspace_id", "") or "",
            "number": user_data.get("lancepilot_number", "") or "",
            "active": user_data.get("lancepilot_active", False),
        }

    c_lp_active = st.toggle(
        "Ativar Integração LancePilot",
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
            "Número Conectado (Ex: 5561999999999)",
            value=lp_number,
            help="Este número será usado para identificar a origem das mensagens se o Webhook não tiver token.",
        )

        # Privacy: Search Term Required
        lp_search = st.text_input(
            "Nome do Workspace (Filtro Obrigatório)",
            help="Digite o nome exato para buscar seu workspace.",
        )

        # Fetch Workspaces Button
        if lp_token:
            if st.button("🔄 Carregar Workspaces"):
                if not lp_search:
                    st.warning("⚠️ Digite o nome do Workspace para buscar.")
                else:
                    try:
                        # Lazy import to avoid circular dependency
                        try:
                            from scripts.lancepilot.client import LancePilotClient
                        except ImportError:
                            import sys

                            sys.path.append(root_dir)
                            from scripts.lancepilot.client import LancePilotClient

                        client = LancePilotClient(token=lp_token)
                        # Pass search term!
                        data = client.get_workspaces(search_query=lp_search)
                        st.session_state[f"lp_workspaces_{user_data['id']}"] = data
                        if data:
                            st.success(f"Encontrado: {len(data)} workspace(s).")
                        else:
                            st.warning("Nenhum workspace encontrado com este nome.")
                    except Exception as e:
                        st.error(f"Erro ao buscar workspaces: {e}")

        # Dropdown for Workspace
        saved_ws_list = st.session_state.get(f"lp_workspaces_{user_data['id']}", [])

        if saved_ws_list:
            ws_options = {
                w["id"]: f"{w['attributes']['name']} ({w['id']})" for w in saved_ws_list
            }

            # Default index
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
            st.markdown("#### 🔗 Webhook de Integração")
            st.info(
                "Copie a URL abaixo e configure no LancePilot (Settings > Webhook):"
            )

            # Tenta adivinhar a URL base (ou usa placeholder)
            base_kestra = user_data.get("api_url") or "https://SEU-KESTRA-URL.com"
            if "/api" in base_kestra:
                base_kestra = base_kestra.split("/api")[0]

            # URL do Webhook do Flow 'lancepilot_native'
            webhook_url = f"{base_kestra}/api/v1/executions/webhook/company.team/lancepilot_native/lp_webhook"

            st.code(webhook_url, language="text")
            st.caption(
                f"Token do Cliente: {user_data.get('token')} | Identificação via Número: {lp_number}"
            )

    st.divider()

    # --- Betel ERP ---
    st.subheader("Betel ERP (Consulta de Produtos)")
    betel_cfg = t_config.get("consultar_produtos_betel", {})
    if isinstance(betel_cfg, bool):
        betel_cfg = {"active": betel_cfg}

    c_betel_active = st.toggle(
        "Ativar Integração Betel ERP", value=betel_cfg.get("active", False)
    )

    b_loja = betel_cfg.get("loja_id", "")
    b_access = betel_cfg.get("access_token", "")
    b_secret = betel_cfg.get("secret_token", "")

    if c_betel_active:
        b_loja = st.text_input("ID da Loja", value=b_loja)
        b1, b2 = st.columns(2)
        b_access = b1.text_input("Access Token", value=b_access, type="password")
        b_secret = b2.text_input("Secret Token", value=b_secret, type="password")

    st.divider()

    # --- Consulta CEP ---
    st.subheader("📍 Consulta CEP (Correios/ViaCEP)")
    cep_cfg = t_config.get("consultar_cep", {})
    if isinstance(cep_cfg, bool):
        cep_cfg = {"active": cep_cfg}

    c_cep_active = st.toggle(
        "Ativar Consulta de CEP",
        value=cep_cfg.get("active", False),
        help="Permite que a IA consulte endereços automaticamente a partir do CEP informado pelo cliente.",
    )

    if c_cep_active:
        st.caption(
            "Esta integração utiliza serviços públicos (ViaCEP/BrasilAPI). Nenhuma configuração extra é necessária."
        )

    st.divider()
    st.subheader("📤 Enviar Relatório para Grupo")
    relatorio_cfg = t_config.get("enviar_relatorio", {})
    if isinstance(relatorio_cfg, bool):
        relatorio_cfg = {"active": relatorio_cfg}

    c_relatorio_active = st.toggle(
        "Habilitar Envio de Relatórios", value=relatorio_cfg.get("active", False)
    )

    r_grupo = relatorio_cfg.get("grupo_id", "")
    r_instructions = relatorio_cfg.get("instructions", "")
    r_template = relatorio_cfg.get("template", "")

    if c_relatorio_active:
        r_grupo = st.text_input(
            "ID do Grupo WhatsApp",
            value=r_grupo,
            help="Ex: 5511999999999-1234567890@g.us (obtenha via Uazapi)",
        )
        r_instructions = st.text_area(
            "Quando enviar relatório?",
            value=r_instructions,
            height=100,
            placeholder="Ex: Envie relatório quando o cliente confirmar pedido, reservar produto, ou fechar negócio...",
        )
        r_template = st.text_area(
            "Template da Mensagem (Opcional)",
            value=r_template,
            height=80,
            placeholder="Ex: *Novo Pedido* \\n Cliente: {{nome}} \\n Produto: {{produto}}",
            help="Use {{campo}} para inserir dados. Se vazio, usa formato padrão.",
        )

    st.divider()

    # --- Atendimento Humano ---
    st.subheader("🧑‍💼 Atendimento Humano")
    handoff_cfg = t_config.get("atendimento_humano", {})
    if isinstance(handoff_cfg, bool):
        handoff_cfg = {"active": handoff_cfg}

    c_handoff_active = st.toggle(
        "Habilitar Atendimento Humano", value=handoff_cfg.get("active", False)
    )

    h_timeout = handoff_cfg.get("timeout_minutes", 60)
    h_instructions = handoff_cfg.get("instructions", "")

    if c_handoff_active:
        h_timeout = st.number_input(
            "Duração do Modo Humano (minutos)",
            min_value=5,
            max_value=1440,
            value=int(h_timeout),
            help="Tempo que a IA ficará pausada após transferir para humano.",
        )
        h_instructions = st.text_area(
            "Quando ativar o Atendimento Humano?",
            value=h_instructions,
            height=120,
            placeholder="Ex: Transfira para humano quando o cliente pedir entrega, solicitar desconto, ou perguntar sobre garantia...",
            help="Essas instruções serão adicionadas ao prompt da IA.",
        )

    st.divider()

    # --- Desativar IA (Opt-out) ---
    st.subheader("🛑 Desativar IA (Opt-out)")
    stop_cfg = t_config.get("desativar_ia", {})
    if isinstance(stop_cfg, bool):
        stop_cfg = {"active": stop_cfg}

    c_stop_active = st.toggle(
        "Habilitar Desativação Permanente",
        value=stop_cfg.get("active", False),
        help="Permite que o cliente pare a IA definitivamente com um comando ou emoji.",
    )

    s_instructions = stop_cfg.get("instructions", "")

    if c_stop_active:
        s_instructions = st.text_area(
            "Gatilhos de Parada (Emojis ou Frases)",
            value=s_instructions,
            height=100,
            placeholder="Ex: Se o cliente enviar 🛑, PARE ou STOP, desative a IA permanentemente.",
            help="Defina aqui quais intenções ou símbolos devem matar o bot.",
        )

    st.divider()
    if st.button("💾 Salvar Integrações"):
        new_tools_config = t_config.copy()
        # Save Kommo
        new_tools_config["qualificado_kommo_provedor"] = {
            "active": c_kommo_active,
            "url": k_url if c_kommo_active else "",
            "token": k_token if c_kommo_active else "",
            "pipeline_id": k_pipeline if c_kommo_active else "",
            "status_id": k_status if c_kommo_active else "",
        }
        # Save Betel
        new_tools_config["consultar_produtos_betel"] = {
            "active": c_betel_active,
            "loja_id": b_loja if c_betel_active else "",
            "access_token": b_access if c_betel_active else "",
            "secret_token": b_secret if c_betel_active else "",
        }
        # Save CEP
        new_tools_config["consultar_cep"] = {"active": c_cep_active}
        # Save Enviar Relatório
        new_tools_config["enviar_relatorio"] = {
            "active": c_relatorio_active,
            "grupo_id": r_grupo if c_relatorio_active else "",
            "instructions": r_instructions if c_relatorio_active else "",
            "template": r_template if c_relatorio_active else "",
        }
        # Save Atendimento Humano
        new_tools_config["atendimento_humano"] = {
            "active": c_handoff_active,
            "timeout_minutes": h_timeout if c_handoff_active else 60,
            "instructions": h_instructions if c_handoff_active else "",
        }
        # Save Desativar IA
        new_tools_config["desativar_ia"] = {
            "active": c_stop_active,
            "instructions": s_instructions if c_stop_active else "",
        }

        try:
            import json

            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Save tools_config JSON (without channels)
                    cur.execute(
                        "UPDATE clients SET tools_config = %s WHERE id = %s",
                        (json.dumps(new_tools_config), user_data["id"]),
                    )
            # Salvar LancePilot em client_providers
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
            st.success("Configurações salvas!")
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
