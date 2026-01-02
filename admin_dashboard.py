import streamlit as st
import psycopg
from psycopg.rows import dict_row
import pandas as pd
import os
import uuid
import sys
import json
from dotenv import load_dotenv

# Adiciona scripts ao path para importar funcoes de DB
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))
try:
    from saas_db import clear_chat_history
except ImportError:
    # Fallback silencioso se o arquivo nao existir ainda
    def clear_chat_history(t_id): return False

# Carrega ambiente
load_dotenv(dotenv_path="../.env")

# Configuração da Página
st.set_page_config(page_title="Kestra 2.0 | Backoffice", layout="wide", page_icon="🏭")

# Conexão DB
DB_URL = os.getenv("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")

def get_connection():
    return psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True)

def create_client(name, token, prompt, api_url=None, timeout=60):
    try:
        store_id = f"store_{uuid.uuid4().hex[:8]}"
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                # Config padrão limpa
                tools_config = '{"consultar_cep": true}'
                
                # Se api_url for vazio string, grava NULL
                final_api_url = api_url if api_url and api_url.strip() else None
                
                cur.execute(sql, (name, token, prompt, store_id, tools_config, timeout, final_api_url))
                
        st.success(f"✅ Cliente '{name}' criado com sucesso!")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao criar: {e}")
        return False

def list_clients():
    try:
        with get_connection() as conn:
            df = pd.read_sql("SELECT id, name, token, system_prompt, human_attendant_timeout, api_url, created_at FROM clients ORDER BY created_at DESC", conn)
        return df
    except Exception as e:
        st.error(f"Erro ao listar: {e}")
        return pd.DataFrame()

def update_client_config(client_id, new_config_str, new_timeout, new_api_url):
    try:
        # Valida JSON
        config_json = json.loads(new_config_str)
        final_api_url = new_api_url if new_api_url and new_api_url.strip() else None
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                sql = "UPDATE clients SET tools_config = %s, human_attendant_timeout = %s, api_url = %s WHERE id = %s"
                cur.execute(sql, (json.dumps(config_json), new_timeout, final_api_url, client_id))
                
        st.success("✅ Configurações, Timeout e URL atualizados!")
        return True
    except json.JSONDecodeError:
        st.error("❌ JSON Inválido!")
        return False
    except Exception as e:
        st.error(f"❌ Erro ao atualizar: {e}")
        return False

# --- UI ---
st.title("🏭 Kestra 2.0 - SaaS Admin Panel")

tab1, tab2, tab3, tab4 = st.tabs(["➕ Novo Cliente", "📋 Lista de Clientes", "⚙️ Configurações", "🛠️ Debug & Manutenção"])

with tab1:
    st.header("Onboarding de Cliente")
    col1, col2 = st.columns(2)
    
    with col1:
        c_name = st.text_input("Nome da Empresa", placeholder="Ex: Pizzaria do Zé")
        c_token = st.text_input("Token / Instance ID (Uazapi)", placeholder="Ex: e1ab2...")
        c_url = st.text_input("API URL Dedicada [Opcional]", placeholder="https://api-cliente.com (Deixe vazio para usar Global)")
        c_timeout = st.number_input("⏳ Tempo Pause Trap (min)", min_value=1, value=60, help="Tempo que a IA fica pausada se o humano falar.")
    
    with col2:
        c_prompt = st.text_area("System Prompt (Personalidade)", height=200, 
                              value="Você é um assistente virtual útil e educado.")
    
    if st.button("💾 Cadastrar Cliente", type="primary"):
        if c_name and c_token:
            create_client(c_name, c_token, c_prompt, c_url, c_timeout)
        else:
            st.warning("Preencha Nome e Token!")

with tab2:
    st.header("Clientes Ativos")
    df = list_clients()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        if st.button("🔄 Atualizar Lista"):
            st.rerun()
    else:
        st.info("Nenhum cliente encontrado.")

with tab3:
    st.header("Editor de Ferramentas & Configs")
    df_clients = list_clients()
    
    if not df_clients.empty:
        client_opts = {f"{row['name']} ({row['token']})": row['id'] for index, row in df_clients.iterrows()}
        selected_label = st.selectbox("Selecione o Cliente:", list(client_opts.keys()))
        selected_id = client_opts[selected_label]
        
        # Carrega config atual
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT tools_config, human_attendant_timeout, api_url FROM clients WHERE id = %s", (selected_id,))
                res = cur.fetchone()
                current_config = res['tools_config']
                current_timeout = res['human_attendant_timeout']
                current_api_url = res['api_url'] or ""
        
        col_cfg, col_meta = st.columns([2, 1])
        
        with col_cfg:
            config_str = st.text_area("JSON de Configuração (Tools)", value=json.dumps(current_config, indent=2), height=250)
            st.caption("Exemplo: {\"consultar_cep\": true}")
            
        with col_meta:
            st.subheader("Infraestrutura")
            edit_timeout = st.number_input("⏳ Timeout Humano (min)", min_value=1, value=current_timeout or 60)
            edit_api_url = st.text_input("🌐 API URL (Override)", value=current_api_url, placeholder="Deixe vazio para usar ENV Global")
        
        if st.button("💾 Salvar Configurações"):
            update_client_config(selected_id, config_str, edit_timeout, edit_api_url)
    else:
        st.warning("Cadastre um cliente primeiro.")

with tab4:
    st.header("🛠️ Utilitários de Debug")
    
    st.markdown("### 🧹 Limpeza de Memória do Chat")
    st.info("Use isso se o chat travar com erro '400 Bad Request' ou 'tool_calls must be followed by tool messages'. Isso apaga o histórico de curto prazo do usuário.")
    
    chat_id_clean = st.text_input("Chat ID (Telefone/Session ID)", placeholder="Ex: 5511999999999")
    
    if st.button("🗑️ Limpar Histórico do Chat", type="primary"):
        if chat_id_clean:
            if clear_chat_history(chat_id_clean):
                st.success(f"Histórico de '{chat_id_clean}' limpo com sucesso! Pode testar novamente.")
            else:
                st.error("Falha ao limpar histórico. Verifique os logs.")
        else:
            st.warning("Digite um Chat ID.")

# Footer
st.markdown("---")
st.caption("Kestra 2.0 SaaS Architecture | Powered by Gemini & Postgres")
