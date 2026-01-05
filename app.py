"""
AIAHUB CENTER - Entry Point com Login
"""

import streamlit as st
import mimetypes

# FORÇAR MIME TYPES (Correção para Docker Slim / Streamlit Static)
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
import os
import sys

# Adiciona diretório raiz ao path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from scripts.shared.saas_db import get_connection

# Configuração da Página
st.set_page_config(page_title="AIAHUB CENTER", layout="wide", page_icon="🚀")


def verify_login(username: str, password: str):
    """Verifica credenciais e retorna dados do usuário se válido."""
    try:
        from scripts.shared.auth_utils import verify_password, is_bcrypt_hash
        import hashlib

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, username, password_hash, is_admin, system_prompt, gemini_store_id, api_url, tools_config, human_attendant_timeout, token FROM clients WHERE username = %s",
                    (username,),
                )
                user = cur.fetchone()

                if user and user["password_hash"]:
                    stored_hash = user["password_hash"]

                    # Suporta bcrypt e SHA-256 (legado)
                    if is_bcrypt_hash(stored_hash):
                        valid = verify_password(password, stored_hash)
                    else:
                        # Fallback SHA-256 (legado)
                        valid = (
                            stored_hash == hashlib.sha256(password.encode()).hexdigest()
                        )

                    if valid:
                        return {
                            "id": str(user["id"]),
                            "name": user["name"],
                            "username": user["username"],
                            "token": user["token"],  # Token for API calls
                            "is_admin": user.get("is_admin", False),
                            "system_prompt": user.get("system_prompt", ""),
                            "store_id": user.get(
                                "gemini_store_id", ""
                            ),  # Mapeia para store_id
                            "api_url": user.get("api_url", ""),
                            "tools_config": user.get("tools_config", {}),
                            "timeout": user.get("human_attendant_timeout", 60),
                        }
        return None
    except Exception as e:
        st.error(f"Erro no login: {e}")
        return None


def render_login():
    """Renderiza tela de login."""
    st.title("🚀 AIAHUB CENTER")
    st.subheader("Faça login para continuar")

    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")

        if submitted:
            if username and password:
                user_data = verify_login(username, password)
                if user_data:
                    st.session_state["logged_in"] = True
                    st.session_state["user_data"] = user_data
                    st.session_state["user_name"] = user_data["name"]
                    st.session_state["is_admin"] = user_data.get("is_admin", False)
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos!")
            else:
                st.warning("Preencha usuário e senha.")

    st.markdown("---")
    st.caption("AIAHUB CENTER")


def main():
    # Verifica se está logado
    if not st.session_state.get("logged_in"):
        render_login()
        return

    # Carrega view apropriada
    try:
        user_data = st.session_state.get("user_data", {})
        is_admin = st.session_state.get("is_admin", False)

        if is_admin:
            # Admin Dashboard
            from views.admin_view import render_admin_view

            render_admin_view()
        else:
            # Client Dashboard
            from views.client_view import render_client_view

            render_client_view(user_data)

    except Exception as e:
        st.error(f"Erro crítico ao carregar painel: {e}")
        import traceback

        st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
