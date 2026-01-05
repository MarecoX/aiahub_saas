import streamlit as st
import logging

# Import Tab Renderers
from views.client_dashboard.tabs.files_tab import render_files_tab
from views.client_dashboard.tabs.prompt_tab import render_prompt_tab
from views.client_dashboard.tabs.simulator_tab import render_simulator_tab
from views.client_dashboard.tabs.tools_tab import render_tools_tab
from views.client_dashboard.tabs.whatsapp_tab import render_whatsapp_tab
from views.client_dashboard.tabs.connection_tab import render_connection_tab
from views.client_dashboard.tabs.followup_tab import render_followup_tab

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def render_client_dashboard(user_data):
    """
    Main Entry Point for the Client Dashboard (Modularized).
    """
    logger.info(
        f"Rendering Dashboard for User ID: {user_data.get('id')} - Name: {user_data.get('name')}"
    )

    # 1. Initialize Services (Gemini)
    gemini_manager = None
    try:
        from api.services.gemini_service import GeminiService

        gemini_manager = GeminiService()
    except Exception as e:
        logger.error(f"Failed to initialize GeminiService: {e}")
        st.error(f"Erro ao inicializar IA: {e}")

    # 2. Header / Logout
    st.title(f"🤖 AIAHUB CONECT | {user_data['name']}")

    # Sidebar Global Controls
    with st.sidebar:
        st.subheader("Controles Globais")
        # AI Toggle (Defaults to True)
        # Toggle logic with DB persistence (Using tools_config JSONB)
        tools_cfg = user_data.get("tools_config", {})
        current_ai_status = tools_cfg.get("ai_active", True)

        new_ai_status = st.toggle(
            "🤖 Ativar IA (Respostas Automáticas)",
            value=bool(current_ai_status),
        )

        if new_ai_status != current_ai_status:
            from scripts.shared.saas_db import update_tools_config_db

            # Update JSON structure
            tools_cfg["ai_active"] = new_ai_status

            # Save to DB (JSONB)
            update_tools_config_db(user_data["id"], tools_cfg)

            # Update Session State
            user_data["tools_config"] = tools_cfg
            st.session_state["user_data"] = user_data

            st.toast(f"IA {'Ativada' if new_ai_status else 'Desativada'}")

    col_info, col_logout = st.columns([4, 1])
    with col_info:
        st.caption(f"Knowledge Base ID: {user_data.get('store_id', 'Não configurado')}")
    with col_logout:
        if st.button("Sair"):
            st.session_state.clear()
            st.rerun()

    # 3. Main Tabs
    (
        tab_files,
        tab_prompt,
        tab_sim,
        tab_tools,
        tab_whatsapp_qr,
        tab_meta_official,
        tab_followup,
        # tab_inbox is now inside tab_meta_official (refactored requirement)
    ) = st.tabs(
        [
            "📂 Meus Arquivos (RAG)",
            "🧠 Personalidade (Prompt)",
            "💬 Testar Assistente",
            "🔗 Integrações e Ferramentas",
            "📷 WhatsApp (QR Code)",
            "🟢 WhatsApp Oficial",
            "⏰ Follow-up Autônomo",
        ]
    )

    # 4. Render Tabs
    with tab_files:
        if gemini_manager:
            render_files_tab(user_data, gemini_manager)
        else:
            st.warning("Serviço de IA indisponível para arquivos.")

    with tab_prompt:
        render_prompt_tab(user_data)

    with tab_sim:
        render_simulator_tab(user_data)

    with tab_tools:
        render_tools_tab(user_data)

    with tab_whatsapp_qr:
        render_connection_tab(user_data)

    with tab_meta_official:
        render_whatsapp_tab(user_data)

    with tab_followup:
        render_followup_tab(user_data)
