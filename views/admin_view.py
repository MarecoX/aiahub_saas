import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
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
                        "SELECT id, name, token, username, is_admin, gemini_store_id, tools_config, human_attendant_timeout, api_url, created_at, whatsapp_provider FROM clients ORDER BY created_at DESC"
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

    def create_client(name, prompt, username, password, timeout=60):
        from scripts.shared.auth_utils import hash_password

        try:
            store_id = f"store_{uuid.uuid4().hex[:8]}"
            pwd_hash = hash_password(password)

            with get_connection() as conn:
                with conn.cursor() as cur:
                    sql = """
                        INSERT INTO clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, username, password_hash, whatsapp_provider)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """
                    tools_config = '{"consultar_cep": true}'
                    cur.execute(
                        sql,
                        (
                            name,
                            None,  # Token opcional (NULL)
                            prompt,
                            store_id,
                            tools_config,
                            timeout,
                            username,
                            pwd_hash,
                            "none",  # whatsapp_provider - configurado depois
                        ),
                    )
                    new_client_id = cur.fetchone()["id"]
            st.success(
                f"✅ Cliente '{name}' criado! Configure o WhatsApp no painel do cliente."
            )
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
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "➕ Criar Cliente",
            "📋 Lista Geral",
            "🔐 Acessos",
            "⚙️ Config Avançada",
            "📊 Consumo",
            "🛠️ Debug",
        ]
    )

    with tab1:
        st.header("Novo Cliente SaaS")
        st.info(
            "💡 Crie o cliente primeiro. O WhatsApp será configurado depois na aba 'Conexão' do painel do cliente."
        )

        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Nome da Empresa")
            user = st.text_input("Username de Login (Ex: empresa1)")
            pwd = st.text_input("Senha Inicial", type="password")
        with c2:
            prompt = st.text_area(
                "Prompt Inicial", height=150, value="Você é um assistente útil."
            )

        if st.button("💾 Cadastrar"):
            if name and user and pwd:
                create_client(name, prompt, user, pwd)
            else:
                st.warning("Preencha: Nome, Username e Senha.")

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

            # --- System Prompt Edit ---
            sys_prompt = st.text_area(
                "System Prompt", value=row.get("system_prompt") or "", height=200
            )

            if st.button("Salvar Config"):
                # Update Configs + Prompt
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            # Update Tools/Timeout/URL
                            cur.execute(
                                "UPDATE clients SET tools_config = %s, human_attendant_timeout = %s, api_url = %s, system_prompt = %s WHERE id = %s",
                                (
                                    cfg_txt,
                                    to_val,
                                    url_val if url_val else None,
                                    sys_prompt,
                                    row["id"],
                                ),
                            )
                    st.success("✅ Configurações e Prompt salvos!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

    with tab5:
        st.header("📊 Consumo de IA por Cliente")
        st.caption("Monitoramento de custos de OpenAI, Gemini e Whisper")

        # Filtros
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("De", value=datetime.now() - timedelta(days=30))
        with col2:
            end_date = st.date_input("Até", value=datetime.now())

        # Query agregada
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT 
                            c.name as cliente,
                            u.provider,
                            COUNT(DISTINCT u.chat_id) as atendimentos,
                            SUM(u.openai_input_tokens + u.openai_output_tokens) as tokens_openai,
                            SUM(u.gemini_input_tokens + u.gemini_output_tokens) as tokens_gemini,
                            SUM(u.whisper_seconds) as segundos_audio,
                            SUM(u.images_count) as imagens,
                            ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                            ROUND(SUM(u.cost_usd * 6)::numeric, 2) as custo_brl
                        FROM usage_tracking u
                        JOIN clients c ON u.client_id = c.id
                        WHERE u.created_at BETWEEN %s AND %s
                        GROUP BY c.name, u.provider
                        ORDER BY custo_usd DESC
                    """,
                        (start_date, end_date),
                    )
                    rows = cur.fetchall()
                    if rows:
                        df_usage = pd.DataFrame(rows)
                        st.dataframe(df_usage, use_container_width=True)

                        # Totais
                        total_usd = df_usage["custo_usd"].sum()
                        total_brl = df_usage["custo_brl"].sum()
                        st.metric(
                            "💰 Custo Total",
                            f"R$ {total_brl:.2f}",
                            f"USD {total_usd:.4f}",
                        )

                        # Gráfico
                        if len(df_usage) > 1:
                            st.bar_chart(df_usage.set_index("cliente")["custo_brl"])
                    else:
                        st.info("💭 Nenhum dado de consumo encontrado no período.")
        except Exception as e:
            st.warning(f"⚠️ Tabela usage_tracking não existe ou erro: {e}")
            st.info("Execute o SQL de criação da tabela no Supabase.")

    with tab6:
        st.header("Debug")
        st.info("Limpeza de Chat")
        cid = st.text_input("Chat ID")
        if st.button("Limpar"):
            clear_chat_history(cid)
            st.success("Limpo.")
