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
from views.client_dashboard.tabs.monitoring_tab import render_monitoring_tab

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def render_client_dashboard(user_data):
    """
    Main Entry Point for the Client Dashboard (Modularized).
    Refactored to use Sidebar Navigation for a cleaner SaaS look.
    """
    # 1. Initialize Services (Gemini)
    gemini_manager = None
    try:
        from api.services.gemini_service import GeminiService

        gemini_manager = GeminiService()
    except Exception as e:
        logger.error(f"Failed to initialize GeminiService: {e}")
        st.error(f"Erro ao inicializar IA: {e}")

    # --- SIDEBAR NAVIGATION ---
    with st.sidebar:
        # User Profile Header
        st.title("🤖 AIAHUB")
        st.caption(f"Bem-vindo, {user_data.get('name')}")
        st.divider()

        # Navigation Menu
        # Grouped for better UX
        st.subheader("Navegação")

        selected_page = st.radio(
            "Menu Principal",
            [
                "🟢 WhatsApp Oficial",
                "📂 Meus Arquivos (RAG)",
                "🧠 Personalidade (Prompt)",
                "💬 Testar Assistente",
                "🔗 Integrações",
                "📷 WhatsApp (Legacy/QR)",
                "⏰ Follow-up Autônomo",
                "📊 Monitoramento",
            ],
            index=0,  # Default to WhatsApp Official as it's the main focus
            label_visibility="collapsed",
        )

        st.divider()

        # Global Controls
        st.subheader("Controles Globais")
        # AI Toggle
        tools_cfg = user_data.get("tools_config", {})
        current_ai_status = tools_cfg.get("ai_active", True)

        new_ai_status = st.toggle(
            "Respostas Automáticas (IA)",
            value=bool(current_ai_status),
        )

        if new_ai_status != current_ai_status:
            from scripts.shared.saas_db import update_tools_config_db

            tools_cfg["ai_active"] = new_ai_status
            update_tools_config_db(user_data["id"], tools_cfg)
            user_data["tools_config"] = tools_cfg
            st.session_state["user_data"] = user_data
            st.rerun()

        st.divider()
        if st.button("🚪 Sair"):
            st.session_state.clear()
            st.rerun()

    # --- MAIN CONTENT AREA ---
    # Render based on selection

    # Header Info (Store ID)
    st.caption(f"Knowledge Base ID: {user_data.get('store_id', 'Não configurado')}")

    if selected_page == "📂 Meus Arquivos (RAG)":
        st.title("📂 Meus Arquivos")
        if gemini_manager:
            render_files_tab(user_data, gemini_manager)
        else:
            st.warning("Serviço de IA indisponível.")

    elif selected_page == "🧠 Personalidade (Prompt)":
        render_prompt_tab(user_data)

    elif selected_page == "💬 Testar Assistente":
        render_simulator_tab(user_data)

    elif selected_page == "🔗 Integrações":
        render_tools_tab(user_data)

    elif selected_page == "🟢 WhatsApp Oficial":
        # Whatsapp Tab already has its own headers/sub-tabs
        render_whatsapp_tab(user_data)

    elif selected_page == "📷 WhatsApp (Legacy/QR)":
        render_connection_tab(user_data)

    elif selected_page == "⏰ Follow-up Autônomo":
        render_followup_tab(user_data)

    elif selected_page == "📊 Monitoramento":
        render_monitoring_tab(user_data)
