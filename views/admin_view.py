import streamlit as st
import pandas as pd
import json
import uuid
import os
import sys

# Adiciona diretório raiz ao path para imports funcionarem
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection, clear_chat_history

try:
    from api.services import gemini_service as gemini_manager
except ImportError:
    gemini_manager = None


def render_admin_view():
    st.title("🏭 Kestra SaaS | Painel Admin")
    st.caption(f"Logado como: {st.session_state.get('user_name', 'Admin')}")

    if st.button("Sair"):
        st.session_state.clear()
        st.rerun()

    # --- FUNÇÕES DE BD (Simplificadas aqui ou importadas) ---
    def list_clients():
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, token, username, is_admin, gemini_store_id, tools_config, human_attendant_timeout, api_url, created_at FROM clients ORDER BY created_at DESC"
                    )
                    rows = cur.fetchall()
                    if rows:
                        df = pd.DataFrame(rows)
                        if "id" in df.columns:
                            df["id"] = df["id"].astype(str)
                        return df
                    return pd.DataFrame()
        except:
            return pd.DataFrame()

    def create_client(
        name, token, prompt, username, password, api_url=None, timeout=60
    ):
        from scripts.shared.auth_utils import hash_password

        try:
            store_id = f"store_{uuid.uuid4().hex[:8]}"
            pwd_hash = hash_password(password)

            with get_connection() as conn:
                with conn.cursor() as cur:
                    sql = """
                        INSERT INTO clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, api_url, username, password_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    tools_config = '{"consultar_cep": true}'
                    data_url = api_url if api_url and api_url.strip() else None
                    cur.execute(
                        sql,
                        (
                            name,
                            token,
                            prompt,
                            store_id,  # Use the potentially updated store_id
                            tools_config,
                            timeout,
                            data_url,
                            username,
                            pwd_hash,
                        ),
                    )
            st.success(f"✅ Cliente '{name}' criado (User: {username})!")
            return True
        except Exception as e:
            st.error(f"Erro: {e}")
            return False

    def update_config(c_id, config_str, timeout, url):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET tools_config = %s, human_attendant_timeout = %s, api_url = %s WHERE id = %s",
                        (config_str, timeout, url if url else None, c_id),
                    )
            st.success("Salvo!")
            return True
        except Exception as e:
            st.error(f"Erro: {e}")
            return False

    def update_access(c_id, new_user, new_pass):
        from scripts.shared.auth_utils import hash_password

        try:
            updates = []
            params = []

            if new_user and new_user.strip():
                updates.append("username = %s")
                params.append(new_user)

            if new_pass and new_pass.strip():
                updates.append("password_hash = %s")
                params.append(hash_password(new_pass))

            if not updates:
                st.warning("Nada para atualizar.")
                return False

            params.append(c_id)
            sql = f"UPDATE clients SET {', '.join(updates)} WHERE id = %s"

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, tuple(params))
            st.success("✅ Acesso Atualizado!")
            return True
        except Exception as e:
            st.error(f"Erro ao atualizar: {e}")
            return False

    # --- UI ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "➕ Criar Cliente",
            "📋 Lista Geral",
            "🔐 Acessos",
            "⚙️ Config Avançada",
            "🛠️ Debug",
        ]
    )

    with tab1:
        st.header("Novo Cliente SaaS")
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Nome da Empresa")
            token = st.text_input("Token Uazapi / InstanceID")
            url = st.text_input("API URL (Opcional)")
        with c2:
            prompt = st.text_area(
                "Prompt Inicial", height=100, value="Assistente útil."
            )
            user = st.text_input("Username de Login (Ex: empresa1)")
            pwd = st.text_input("Senha Inicial", type="password")

        if st.button("💾 Cadastrar"):
            if name and token and user and pwd:
                create_client(name, token, prompt, user, pwd, url)
            else:
                st.warning("Preencha todos os campos obrigatórios.")

    with tab2:
        st.dataframe(list_clients(), width="stretch")
        if st.button("🔄 Atualizar"):
            st.rerun()

    with tab3:
        st.header("🔐 Gerenciar Login/Senha")
        st.caption(
            "Use isso para definir acessos de clientes antigos (ex: Algar) ou resetar senhas."
        )

        df = list_clients()
        if not df.empty:
            sel_cli = st.selectbox(
                "Selecione o Cliente para editar:",
                df["name"].tolist(),
                key="sel_access",
            )
            row_cli = df[df["name"] == sel_cli].iloc[0]

            st.info(
                f"Usuário Atual: {row_cli['username'] if 'username' in row_cli and row_cli['username'] else 'Sem usuário definido'}"
            )

            c_new_user = st.text_input(
                "Novo Username (Opcional)", placeholder="Deixe vazio para manter"
            )
            c_new_pass = st.text_input(
                "Nova Senha (Opcional)",
                type="password",
                placeholder="Deixe vazio para manter",
            )

            if st.button("💾 Atualizar Acesso"):
                update_access(row_cli["id"], c_new_user, c_new_pass)

    with tab4:
        st.header("Editar Configs JSON")
        df = list_clients()
        if not df.empty:
            sel = st.selectbox(
                "Cliente", df["name"].tolist(), key="sel_cfg"
            )  # Unique key
            row = df[df["name"] == sel].iloc[0]

            cfg_txt = st.text_area(
                "JSON Tools", value=json.dumps(row.get("tools_config", {}), indent=2)
            )
            to_val = st.number_input(
                "Timeout", value=row.get("human_attendant_timeout", 60)
            )
            url_val = st.text_input("URL Override", value=row.get("api_url") or "")

            if st.button("Salvar Config"):
                update_config(row["id"], cfg_txt, to_val, url_val)

    with tab5:
        st.header("Debug")
        st.info("Limpeza de Chat")
        cid = st.text_input("Chat ID")
        if st.button("Limpar"):
            clear_chat_history(cid)
            st.success("Limpo.")
