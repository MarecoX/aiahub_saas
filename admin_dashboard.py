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
                    INSERT INTO public.clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url)
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

# ... (Imports)
# Importação direta (já que scripts tem __init__.py agora)
try:
    from scripts import gemini_manager
except ImportError as e:
    st.error(f"Erro ao importar Gemini Manager: {e} | Verifique se a pasta 'scripts' tem __init__.py")

# ... (Connection functions remain same)

def list_clients():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Add gemini_store_id
                cur.execute("SELECT id, name, token, system_prompt, human_attendant_timeout, api_url, gemini_store_id, created_at FROM clients ORDER BY created_at DESC")
                rows = cur.fetchall()
                if rows:
                    df = pd.DataFrame(rows)
                    # Convert id to string to avoid Arrow/Streamlit UUID issues
                    if 'id' in df.columns:
                        df['id'] = df['id'].astype(str)
                    return df
                else:
                    return pd.DataFrame(columns=["id", "name", "token", "system_prompt", "human_attendant_timeout", "api_url", "gemini_store_id", "created_at"])
    except Exception as e:
        st.error(f"Erro ao listar: {e}")
        return pd.DataFrame()

def update_store_id(client_id, new_store_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE clients SET gemini_store_id = %s WHERE id = %s", (new_store_id, client_id))
        return True
    except Exception as e:
        st.error(f"Erro no update store: {e}")
        return False

# ... (Rest of update_client_config)

# ... (UI Tabs)
tab1, tab2, tab3, tab4, tab5 = st.tabs(["➕ Novo Cliente", "📋 Lista de Clientes", "⚙️ Configurações", "🛠️ Debug", "📚 Base de Conhecimento"])

# ... (Tabs 1, 2, 3, 4 standard logic...)

with tab5:
    st.header("📚 Gestão de Arquivos (RAG)")
    df_kb = list_clients()
    
    if not df_kb.empty:
        # Select Client
        kb_opts = {f"{row['name']}": index for index, row in df_kb.iterrows()}
        kb_sel = st.selectbox("Selecione o Cliente para Upload:", list(kb_opts.keys()), key="kb_select")
        
        row_idx = kb_opts[kb_sel]
        client_data = df_kb.iloc[row_idx]
        c_store_id = client_data['gemini_store_id']
        c_id = client_data['id']
        
        st.info(f"Store ID Atual: {c_store_id}")
        
        # Check Status (IDs da V1 Enterprise contém 'fileSearchStores/' ou 'corpora/')
        is_real_vector_store = c_store_id and ("fileSearchStores/" in c_store_id or "corpora/" in c_store_id or "vector-" in c_store_id)
        
        if not is_real_vector_store:
            st.warning("⚠️ Este cliente ainda usa um ID lógico local. É preciso inicializar o Vector Store no Gemini.")
            if st.button("🚀 Inicializar Vector Store (Gemini)"):
                with st.spinner("Criando Store no Google..."):
                    # Tenta criar (retorna tupla vs, error)
                    # Se c_store_id for None, passamos o Nome do Cliente para ser o Título
                    target_name = c_store_id if c_store_id else f"{client_data['name']}"
                    
                    vs, error_msg = gemini_manager.get_or_create_vector_store(target_name)
                    
                    if vs:
                        # Update DB with REAL ID (vs.name é o ID oficial)
                        if update_store_id(c_id, vs.name):
                            st.success(f"✅ Store Criado! Novo ID: {vs.name}")
                            st.rerun()
                    else:
                        st.error(f"Falha ao criar Vector Store: {error_msg}")
        else:
            st.success("✅ Conectado ao Gemini Vector Store (Enterprise).")
            
            # File Upload
            uploaded_files = st.file_uploader("Enviar PDFs/TXTs/Css", accept_multiple_files=True)
            
            if st.button("📤 Enviar Arquivos para IA"):
                if uploaded_files:
                    progress_bar = st.progress(0)
                    for i, file in enumerate(uploaded_files):
                        # 1. Save temp
                        temp_path = f"temp_{file.name}"
                        with open(temp_path, "wb") as f:
                            f.write(file.getbuffer())
                            
                        # 2. Upload DIRETO pro Store (Manager v2)
                        st.write(f"Enviando {file.name}...")
                        op, error = gemini_manager.upload_file_to_store(
                            temp_path, 
                            c_store_id, 
                            custom_display_name=file.name
                        )
                        
                        if op:
                            st.write(f"✅ {file.name} indexado com sucesso!")
                        else:
                            st.error(f"Erro ao enviar {file.name}: {error}")
                            
                        # Cleanup
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                            
                        progress_bar.progress((i + 1) / len(uploaded_files))
                        
                    st.success("Operação Finalizada!")
                else:
                    st.warning("Selecione arquivos.")
            
            st.divider()
            st.subheader("📂 Arquivos no Gemini")
            
            # Listar
            files = gemini_manager.list_files_in_store(c_store_id)
            # files é um generator/iterator
            
            if files:
                for f in files:
                    col_name, col_del = st.columns([4, 1])
                    with col_name:
                        # Exibe nome e ID
                        # Nota: f.display_name pode ser vazio se não definido no upload, fallback para name
                        d_name = f.display_name if hasattr(f, 'display_name') and f.display_name else "Sem Nome"
                        st.text(f"📄 {d_name} \n   ({f.name})")
                        
                    with col_del:
                        if st.button("🗑️", key=f"del_{f.name}"):
                            if gemini_manager.delete_file(f.name):
                                st.success("Deletado!")
                                st.rerun()
                            else:
                                st.error("Erro ao deletar.")
            else:
                st.info("Nenhum arquivo encontrado neste Store.")
    else:
        st.warning("Sem clientes.")

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
