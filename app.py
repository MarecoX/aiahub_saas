import streamlit as st
import os
import sys
from dotenv import load_dotenv

# Carrega Variaveis de Ambiente (DB_URL, Keys)
load_dotenv(dotenv_path="../.env")

# Setup Paths
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'views'))

try:
    from scripts.auth_manager import verify_login
    from views.admin_view import render_admin_view
    from views.client_view import render_client_view
except ImportError as e:
    st.error(f"Erro de Importação: {e}")

# Page Config
st.set_page_config(page_title="Kestra SaaS", page_icon="🤖", layout="wide")

# Session State Init
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

def login_page():
    # CSS Customizado
    st.markdown("""
        <style>
        .reportview-container {
            background: #0e1117;
        }
        .main {
            background-color: #0e1117; 
        }
        div[data-testid="stForm"] {
            border: 1px solid #333;
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0px 4px 15px rgba(0,0,0,0.5);
            background-color: #262730;
        }
        h1 {
            text-align: center;
            font-weight: 300 !important;
            letter-spacing: 2px;
        }
        .stButton>button {
            width: 100%;
            border-radius: 10px;
            height: 50px;
            font-weight: bold;
        }
        /* Esconde Header/Footer Padrão */
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

    st.title("🔐 Kestra SaaS")
    st.markdown("<h5 style='text-align: center; color: gray;'>Acesso Corporativo Seguro</h5><br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            st.markdown("### Credenciais")
            username = st.text_input("Usuário", placeholder="Digite seu usuário")
            password = st.text_input("Senha", type="password", placeholder="Digite sua senha")
            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Acessar Painel", type="primary")
            
            if submitted:
                user = verify_login(username, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user = user
                    st.success(f"Bem-vindo, {user['name']}!")
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")

def main():
    if not st.session_state.logged_in:
        login_page()
    else:
        user = st.session_state.user
        if user["is_admin"]:
            render_admin_view()
        else:
            render_client_view(user)

if __name__ == "__main__":
    main()
