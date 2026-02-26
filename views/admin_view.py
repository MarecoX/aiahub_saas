import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import uuid
import os
import sys
import subprocess

# Adiciona diretório raiz ao path para imports funcionarem
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection, clear_chat_history
from scripts.shared.tool_registry import BUSINESS_TYPES

try:
    from api.services import gemini_service as gemini_manager
except ImportError:
    gemini_manager = None


def _sanitize_df(df):
    """Converte tipos incompatíveis com Arrow/Altair (Decimal→float, UUID→str)."""
    from decimal import Decimal as _Decimal

    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
            if sample is not None:
                if isinstance(sample, _Decimal):
                    df[col] = df[col].apply(lambda x: float(x) if x is not None else None)
                elif type(sample).__name__ == "UUID":
                    df[col] = df[col].astype(str)
    return df


def render_admin_view():
    st.title("🏭 Kestra SaaS | Painel Admin")
    st.caption(f"Logado como: {st.session_state.get('user_name', 'Admin')}")

    if st.button("Sair"):
        st.session_state.clear()
        st.rerun()

    # --- BARRA DE ATUALIZAÇÃO (Git Pull / Push) ---
    _repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with st.expander("🔄 Atualização do Sistema (Git)", expanded=False):
        gc1, gc2, gc3 = st.columns([1, 1, 2])

        with gc1:
            if st.button("📥 Git Pull (Atualizar)", key="git_pull_btn"):
                try:
                    result = subprocess.run(
                        ["git", "pull", "--ff-only"],
                        cwd=_repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0:
                        st.success(f"✅ Atualizado!\n```\n{result.stdout}\n```")
                    else:
                        st.error(f"❌ Erro no pull:\n```\n{result.stderr}\n```")
                except subprocess.TimeoutExpired:
                    st.error("⏰ Timeout: o pull demorou mais de 30s.")
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

        with gc2:
            if st.button("📊 Git Status", key="git_status_btn"):
                try:
                    # Branch atual
                    branch = subprocess.run(
                        ["git", "branch", "--show-current"],
                        cwd=_repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    # Status
                    status = subprocess.run(
                        ["git", "status", "--short"],
                        cwd=_repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    # Último commit
                    log = subprocess.run(
                        ["git", "log", "--oneline", "-3"],
                        cwd=_repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    st.info(f"**Branch:** `{branch.stdout.strip()}`")
                    if status.stdout.strip():
                        st.warning(f"**Alterações pendentes:**\n```\n{status.stdout}\n```")
                    else:
                        st.success("✅ Nenhuma alteração pendente.")
                    st.code(log.stdout, language="text")
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

        with gc3:
            st.caption(
                "📥 **Pull** atualiza o código do GitHub.\n\n"
                "⚠️ Após o pull, reinicie o Streamlit para aplicar mudanças."
            )

    # --- FUNÇÕES DE BD (Simplificadas aqui ou importadas) ---
    def list_clients():
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, token, username, is_admin, gemini_store_id, tools_config, human_attendant_timeout, api_url, created_at, whatsapp_provider, business_type FROM clients ORDER BY created_at DESC"
                    )
                    rows = cur.fetchall()
                    if rows:
                        df = _sanitize_df(pd.DataFrame(rows))

                        # Fix: Converte tools_config para string para evitar ArrowInvalid
                        if "tools_config" in df.columns:
                            df["tools_config"] = df["tools_config"].apply(
                                lambda x: (
                                    json.dumps(x)
                                    if isinstance(x, (dict, list))
                                    else (str(x) if x else "{}")
                                )
                            )

                        return df
                    return pd.DataFrame()
        except:
            return pd.DataFrame()

    def create_client(
        name, prompt, username, password, business_type="generic", timeout=60
    ):
        from scripts.shared.auth_utils import hash_password

        try:
            store_id = f"store_{uuid.uuid4().hex[:8]}"
            pwd_hash = hash_password(password)

            with get_connection() as conn:
                with conn.cursor() as cur:
                    sql = """
                        INSERT INTO clients (name, token, system_prompt, gemini_store_id, tools_config, human_attendant_timeout, username, password_hash, whatsapp_provider, business_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """
                    tools_config = '{"consultar_cep": true}'
                    cur.execute(
                        sql,
                        (
                            name,
                            uuid.uuid4().hex,  # Token gerado automaticamente
                            prompt,
                            store_id,
                            tools_config,
                            timeout,
                            username,
                            pwd_hash,
                            "none",  # whatsapp_provider - configurado depois
                            business_type,
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
            b_type = st.selectbox(
                "Tipo de Negócio",
                options=list(BUSINESS_TYPES.keys()),
                format_func=lambda x: BUSINESS_TYPES.get(x, x),
            )
        with c2:
            prompt = st.text_area(
                "Prompt Inicial", height=150, value="Você é um assistente útil."
            )

        if st.button("💾 Cadastrar"):
            if name and user and pwd:
                create_client(name, prompt, user, pwd, business_type=b_type)
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

            # Parseia string JSON de volta para dict para exibir formatado
            tools_val = row.get("tools_config", "{}")
            if isinstance(tools_val, str):
                try:
                    tools_val = json.loads(tools_val)
                except:
                    tools_val = {}

            cfg_txt = st.text_area("JSON Tools", value=json.dumps(tools_val, indent=2))

            # --- Business Type Edit ---
            curr_btype = row.get("business_type")
            if pd.isna(curr_btype) or curr_btype not in BUSINESS_TYPES:
                curr_btype = "generic"

            new_btype = st.selectbox(
                "Tipo de Negócio",
                options=list(BUSINESS_TYPES.keys()),
                index=list(BUSINESS_TYPES.keys()).index(curr_btype),
                key="edit_btype_tab4",
                format_func=lambda x: BUSINESS_TYPES.get(x, x),
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
                                "UPDATE clients SET tools_config = %s, human_attendant_timeout = %s, api_url = %s, system_prompt = %s, business_type = %s WHERE id = %s",
                                (
                                    cfg_txt,
                                    to_val,
                                    url_val if url_val else None,
                                    sys_prompt,
                                    new_btype,
                                    row["id"],
                                ),
                            )
                    st.success("✅ Configurações e Prompt salvos!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

    with tab5:
        # --- FILTROS GLOBAIS ---
        df_clients = list_clients()
        client_names = ["Todos"] + (
            df_clients["name"].tolist() if not df_clients.empty else []
        )

        fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
        with fcol1:
            selected_client = st.selectbox(
                "🏢 Filtrar por Cliente", client_names, key="consumo_filter"
            )
        with fcol2:
            start_date = st.date_input(
                "De", value=datetime.now() - timedelta(days=30), key="consumo_de"
            )
        with fcol3:
            end_date = st.date_input(
                "Até", value=datetime.now(), key="consumo_ate"
            )

        # end_date + 1 dia para incluir o dia completo (date sem hora = meia-noite)
        end_date_exclusive = end_date + timedelta(days=1)

        # ============================================================
        # SEÇÃO 1: ATENDIMENTO EM TEMPO REAL (24h)
        # ============================================================
        st.header("📞 Atendimento em Tempo Real (24h)")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    client_filter_sql = (
                        "AND c.name = %s" if selected_client != "Todos" else ""
                    )
                    params_attend = (
                        (selected_client,) if selected_client != "Todos" else ()
                    )

                    cur.execute(
                        f"""
                        SELECT
                            c.name as cliente,
                            COUNT(CASE WHEN ac.last_role = 'user' AND ac.last_message_at < NOW() - INTERVAL '5 minutes' THEN 1 END) as aguardando_resposta,
                            COUNT(CASE WHEN ac.last_role = 'human' THEN 1 END) as atendidos_humano,
                            COUNT(CASE WHEN ac.last_role = 'ai' THEN 1 END) as atendidos_ia,
                            COUNT(*) as total_conversas
                        FROM active_conversations ac
                        JOIN clients c ON ac.client_id = c.id
                        WHERE ac.status = 'active'
                        AND ac.last_message_at > NOW() - INTERVAL '24 hours'
                        {client_filter_sql}
                        GROUP BY c.name
                        ORDER BY aguardando_resposta DESC
                        """,
                        params_attend,
                    )
                    rows = cur.fetchall()

                    if rows:
                        df_attend = _sanitize_df(pd.DataFrame(rows))

                        total_aguardando = int(df_attend["aguardando_resposta"].sum())
                        total_humano = int(df_attend["atendidos_humano"].sum())
                        total_ia = int(df_attend["atendidos_ia"].sum())
                        total_all = int(df_attend["total_conversas"].sum())

                        mc1, mc2, mc3, mc4 = st.columns(4)
                        mc1.metric("🔴 Aguardando Humano", total_aguardando)
                        mc2.metric("👤 Atendidos por Humano", total_humano)
                        mc3.metric("🤖 Atendidos por IA", total_ia)
                        mc4.metric("💬 Total Conversas (24h)", total_all)

                        # Percentuais
                        if total_all > 0:
                            pct_ia = (total_ia / total_all) * 100
                            pct_humano = (total_humano / total_all) * 100
                            pct_aguardando = (total_aguardando / total_all) * 100
                            pc1, pc2, pc3 = st.columns(3)
                            pc1.metric("🤖 % IA", f"{pct_ia:.1f}%")
                            pc2.metric("👤 % Humano", f"{pct_humano:.1f}%")
                            pc3.metric("🔴 % Aguardando", f"{pct_aguardando:.1f}%")

                        st.dataframe(df_attend, width="stretch")
                    else:
                        st.info("Nenhuma conversa ativa nas últimas 24h.")
        except Exception as e:
            st.warning(f"⚠️ Erro ao buscar indicadores: {e}")
            st.caption(
                "Verifique se a tabela active_conversations existe e tem a coluna last_role."
            )

        st.divider()

        # ============================================================
        # SEÇÃO 2: GRÁFICO DE CUSTO DIÁRIO
        # ============================================================
        st.header("📈 Custo Diário (USD)")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    client_filter_sql2 = (
                        "AND u.client_id = c.id AND c.name = %s"
                        if selected_client != "Todos"
                        else ""
                    )
                    extra_join = (
                        "JOIN clients c ON u.client_id = c.id"
                        if selected_client != "Todos"
                        else ""
                    )
                    params_chart = (start_date, end_date_exclusive)
                    if selected_client != "Todos":
                        params_chart = (start_date, end_date_exclusive, selected_client)

                    cur.execute(
                        f"""
                        SELECT DATE(u.created_at) as dia,
                               ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                               ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                        FROM usage_tracking u
                        {extra_join}
                        WHERE u.created_at >= %s AND u.created_at < %s
                        {client_filter_sql2}
                        GROUP BY dia
                        ORDER BY dia
                        """,
                        params_chart,
                    )
                    chart_rows = cur.fetchall()

                    if chart_rows:
                        df_chart = _sanitize_df(pd.DataFrame(chart_rows))
                        df_chart["dia"] = pd.to_datetime(df_chart["dia"])
                        df_chart = df_chart.set_index("dia")
                        st.line_chart(df_chart[["custo_usd", "custo_brl"]])
                    else:
                        st.info("Sem dados de custo no período.")
        except Exception as e:
            st.warning(f"⚠️ Erro ao gerar gráfico diário: {e}")

        st.divider()

        # ============================================================
        # SEÇÃO 3: CONSUMO POR PROVIDER (OpenAI, Gemini, Whisper)
        # ============================================================
        st.header("📊 Consumo por Provider")
        st.caption("Monitoramento de custos de OpenAI, Gemini e Whisper")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if selected_client == "Todos":
                        cur.execute(
                            """
                            SELECT
                                c.name as cliente,
                                u.provider,
                                COUNT(DISTINCT u.chat_id) as atendimentos,
                                SUM(u.openai_input_tokens + u.openai_output_tokens) as tokens_openai,
                                SUM(u.gemini_input_tokens + u.gemini_output_tokens) as tokens_gemini,
                                SUM(u.whisper_seconds) as segundos_audio,
                                SUM(u.images_count) as imagens,
                                ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                                ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                            FROM usage_tracking u
                            JOIN clients c ON u.client_id = c.id
                            WHERE u.created_at >= %s AND u.created_at < %s
                            GROUP BY c.name, u.provider
                            ORDER BY custo_usd DESC
                        """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                c.name as cliente,
                                u.provider,
                                COUNT(DISTINCT u.chat_id) as atendimentos,
                                SUM(u.openai_input_tokens + u.openai_output_tokens) as tokens_openai,
                                SUM(u.gemini_input_tokens + u.gemini_output_tokens) as tokens_gemini,
                                SUM(u.whisper_seconds) as segundos_audio,
                                SUM(u.images_count) as imagens,
                                ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                                ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                            FROM usage_tracking u
                            JOIN clients c ON u.client_id = c.id
                            WHERE u.created_at >= %s AND u.created_at < %s
                            AND c.name = %s
                            GROUP BY c.name, u.provider
                            ORDER BY custo_usd DESC
                        """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    rows = cur.fetchall()
                    if rows:
                        df_usage = _sanitize_df(pd.DataFrame(rows))
                        st.dataframe(df_usage, width="stretch")

                        # Gráfico de barras por cliente
                        if len(df_usage) > 1:
                            st.bar_chart(df_usage.set_index("cliente")["custo_brl"])
                    else:
                        st.info("Nenhum dado de consumo por provider no período.")
        except Exception as e:
            st.warning(f"⚠️ Erro na tabela por provider: {e}")

        st.divider()

        # ============================================================
        # SEÇÃO 4: DETALHAMENTO DIÁRIO POR CLIENTE
        # ============================================================
        st.header("📋 Detalhamento Diário por Cliente")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if selected_client == "Todos":
                        cur.execute(
                            """
                            SELECT
                                c.name as cliente,
                                DATE(u.created_at) as dia,
                                COUNT(DISTINCT u.chat_id) as atendimentos,
                                SUM(u.openai_input_tokens + u.openai_output_tokens) as tokens_openai,
                                SUM(u.gemini_input_tokens + u.gemini_output_tokens) as tokens_gemini,
                                SUM(u.whisper_seconds) as segundos_audio,
                                SUM(u.images_count) as imagens,
                                ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                                ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                            FROM usage_tracking u
                            JOIN clients c ON u.client_id = c.id
                            WHERE u.created_at >= %s AND u.created_at < %s
                            GROUP BY c.name, dia
                            ORDER BY dia DESC, custo_usd DESC
                        """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                c.name as cliente,
                                DATE(u.created_at) as dia,
                                COUNT(DISTINCT u.chat_id) as atendimentos,
                                SUM(u.openai_input_tokens + u.openai_output_tokens) as tokens_openai,
                                SUM(u.gemini_input_tokens + u.gemini_output_tokens) as tokens_gemini,
                                SUM(u.whisper_seconds) as segundos_audio,
                                SUM(u.images_count) as imagens,
                                ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                                ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                            FROM usage_tracking u
                            JOIN clients c ON u.client_id = c.id
                            WHERE u.created_at >= %s AND u.created_at < %s
                            AND c.name = %s
                            GROUP BY c.name, dia
                            ORDER BY dia DESC, custo_usd DESC
                        """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    detail_rows = cur.fetchall()

                    if detail_rows:
                        df_detail = _sanitize_df(pd.DataFrame(detail_rows))
                        st.dataframe(
                            df_detail,
                            column_config={
                                "cliente": "Cliente",
                                "dia": st.column_config.DateColumn(
                                    "Data", format="DD/MM/YYYY"
                                ),
                                "atendimentos": st.column_config.NumberColumn(
                                    "Atendimentos", format="%d"
                                ),
                                "tokens_openai": st.column_config.NumberColumn(
                                    "Tokens OpenAI", format="%d"
                                ),
                                "tokens_gemini": st.column_config.NumberColumn(
                                    "Tokens Gemini", format="%d"
                                ),
                                "segundos_audio": st.column_config.NumberColumn(
                                    "Áudio (s)", format="%d"
                                ),
                                "imagens": st.column_config.NumberColumn(
                                    "Imagens", format="%d"
                                ),
                                "custo_usd": st.column_config.NumberColumn(
                                    "Custo (USD)", format="$%.4f"
                                ),
                                "custo_brl": st.column_config.NumberColumn(
                                    "Custo (BRL)", format="R$%.2f"
                                ),
                            },
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.info("Nenhum detalhe diário no período.")
        except Exception as e:
            st.warning(f"⚠️ Erro no detalhamento diário: {e}")

        st.divider()

        # ============================================================
        # SEÇÃO 5: TOTAIS CONSOLIDADOS
        # ============================================================
        st.header("💰 Resumo Consolidado")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if selected_client == "Todos":
                        cur.execute(
                            """
                            SELECT
                                COUNT(DISTINCT u.chat_id) as total_atendimentos,
                                ROUND(SUM(u.cost_usd)::numeric, 4) as total_usd,
                                ROUND(SUM(u.cost_usd * 12)::numeric, 2) as total_brl,
                                SUM(u.openai_input_tokens + u.openai_output_tokens) as total_tokens_openai,
                                SUM(u.gemini_input_tokens + u.gemini_output_tokens) as total_tokens_gemini,
                                SUM(u.whisper_seconds) as total_segundos_audio,
                                SUM(u.images_count) as total_imagens
                            FROM usage_tracking u
                            WHERE u.created_at >= %s AND u.created_at < %s
                        """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                COUNT(DISTINCT u.chat_id) as total_atendimentos,
                                ROUND(SUM(u.cost_usd)::numeric, 4) as total_usd,
                                ROUND(SUM(u.cost_usd * 12)::numeric, 2) as total_brl,
                                SUM(u.openai_input_tokens + u.openai_output_tokens) as total_tokens_openai,
                                SUM(u.gemini_input_tokens + u.gemini_output_tokens) as total_tokens_gemini,
                                SUM(u.whisper_seconds) as total_segundos_audio,
                                SUM(u.images_count) as total_imagens
                            FROM usage_tracking u
                            JOIN clients c ON u.client_id = c.id
                            WHERE u.created_at >= %s AND u.created_at < %s
                            AND c.name = %s
                        """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    totals = cur.fetchone()

                    if totals and totals.get("total_usd"):
                        t1, t2, t3 = st.columns(3)
                        t1.metric(
                            "💰 Custo Total",
                            f"R$ {float(totals['total_brl'] or 0):.2f}",
                            f"USD {float(totals['total_usd'] or 0):.4f}",
                        )
                        t2.metric(
                            "📞 Total Atendimentos",
                            int(totals["total_atendimentos"] or 0),
                        )
                        t3.metric(
                            "🖼️ Imagens Processadas",
                            int(totals["total_imagens"] or 0),
                        )

                        t4, t5 = st.columns(2)
                        t4.metric(
                            "🔤 Tokens OpenAI",
                            f"{int(totals['total_tokens_openai'] or 0):,}",
                        )
                        t5.metric(
                            "🔤 Tokens Gemini",
                            f"{int(totals['total_tokens_gemini'] or 0):,}",
                        )
                    else:
                        st.info("Nenhum dado consolidado no período.")
        except Exception as e:
            st.warning(f"⚠️ Erro ao calcular totais: {e}")

        st.divider()

        # ============================================================
        # SEÇÃO 6: MÉTRICAS DE TEMPO DE RESPOSTA DA IA
        # ============================================================
        st.header("⏱️ Tempo de Resposta da IA")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if selected_client == "Todos":
                        # Resumo geral
                        cur.execute(
                            """
                            SELECT
                                c.name as cliente,
                                ROUND(AVG(m.avg_response_time_ms)) as media_resposta_ms,
                                ROUND(AVG(m.avg_resolution_time_ms)) as media_resolucao_ms,
                                SUM(m.total_conversations) as total_conversas,
                                SUM(m.total_messages_in) as msgs_recebidas,
                                SUM(m.total_messages_out) as msgs_enviadas,
                                SUM(m.resolved_by_ai) as resolvidas_ia,
                                SUM(m.resolved_by_human) as resolvidas_humano,
                                SUM(m.human_takeovers) as transferencias_humano,
                                SUM(m.followups_sent) as followups_enviados,
                                SUM(m.followups_converted) as followups_convertidos
                            FROM metrics_daily m
                            JOIN clients c ON m.client_id = c.id
                            WHERE m.date >= %s AND m.date < %s
                            GROUP BY c.name
                            ORDER BY media_resposta_ms ASC
                        """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                c.name as cliente,
                                ROUND(AVG(m.avg_response_time_ms)) as media_resposta_ms,
                                ROUND(AVG(m.avg_resolution_time_ms)) as media_resolucao_ms,
                                SUM(m.total_conversations) as total_conversas,
                                SUM(m.total_messages_in) as msgs_recebidas,
                                SUM(m.total_messages_out) as msgs_enviadas,
                                SUM(m.resolved_by_ai) as resolvidas_ia,
                                SUM(m.resolved_by_human) as resolvidas_humano,
                                SUM(m.human_takeovers) as transferencias_humano,
                                SUM(m.followups_sent) as followups_enviados,
                                SUM(m.followups_converted) as followups_convertidos
                            FROM metrics_daily m
                            JOIN clients c ON m.client_id = c.id
                            WHERE m.date >= %s AND m.date < %s
                            AND c.name = %s
                            GROUP BY c.name
                            ORDER BY media_resposta_ms ASC
                        """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    metric_rows = cur.fetchall()

                    if metric_rows:
                        df_metrics = _sanitize_df(pd.DataFrame(metric_rows))

                        # Cards globais
                        avg_resp = df_metrics["media_resposta_ms"].mean()
                        avg_resol = df_metrics["media_resolucao_ms"].mean()
                        total_conv_m = int(df_metrics["total_conversas"].sum())
                        total_res_ia = int(df_metrics["resolvidas_ia"].sum())
                        total_res_hum = int(df_metrics["resolvidas_humano"].sum())
                        total_takeovers = int(df_metrics["transferencias_humano"].sum())
                        total_followups = int(df_metrics["followups_enviados"].sum())
                        total_fw_conv = int(df_metrics["followups_convertidos"].sum())

                        # Formatar tempo legível
                        def fmt_ms(ms):
                            if pd.isna(ms) or ms == 0:
                                return "N/A"
                            if ms < 1000:
                                return f"{int(ms)}ms"
                            return f"{ms / 1000:.1f}s"

                        r1, r2, r3 = st.columns(3)
                        r1.metric("⚡ Tempo Médio de Resposta", fmt_ms(avg_resp))
                        r2.metric("🏁 Tempo Médio de Resolução", fmt_ms(avg_resol))
                        r3.metric("📨 Total Conversas (período)", total_conv_m)

                        r4, r5, r6 = st.columns(3)
                        r4.metric("🤖 Resolvidas por IA", total_res_ia)
                        r5.metric("👤 Resolvidas por Humano", total_res_hum)
                        r6.metric("🔄 Transferências p/ Humano", total_takeovers)

                        # Taxa de resolução IA
                        total_resolved = total_res_ia + total_res_hum
                        if total_resolved > 0:
                            taxa_ia = (total_res_ia / total_resolved) * 100
                            r7, r8, r9 = st.columns(3)
                            r7.metric("🎯 Taxa Resolução IA", f"{taxa_ia:.1f}%")
                            if total_followups > 0:
                                taxa_fw = (total_fw_conv / total_followups) * 100
                                r8.metric("📤 Follow-ups Enviados", total_followups)
                                r9.metric("✅ Follow-ups Convertidos", f"{total_fw_conv} ({taxa_fw:.1f}%)")
                            else:
                                r8.metric("📤 Follow-ups Enviados", 0)
                                r9.metric("✅ Follow-ups Convertidos", 0)

                        # Tabela por cliente
                        st.dataframe(
                            df_metrics,
                            column_config={
                                "cliente": "Cliente",
                                "media_resposta_ms": st.column_config.NumberColumn(
                                    "Tempo Resposta (ms)", format="%d"
                                ),
                                "media_resolucao_ms": st.column_config.NumberColumn(
                                    "Tempo Resolução (ms)", format="%d"
                                ),
                                "total_conversas": st.column_config.NumberColumn(
                                    "Conversas", format="%d"
                                ),
                                "msgs_recebidas": st.column_config.NumberColumn(
                                    "Msgs In", format="%d"
                                ),
                                "msgs_enviadas": st.column_config.NumberColumn(
                                    "Msgs Out", format="%d"
                                ),
                                "resolvidas_ia": st.column_config.NumberColumn(
                                    "IA", format="%d"
                                ),
                                "resolvidas_humano": st.column_config.NumberColumn(
                                    "Humano", format="%d"
                                ),
                                "transferencias_humano": st.column_config.NumberColumn(
                                    "Takeovers", format="%d"
                                ),
                                "followups_enviados": st.column_config.NumberColumn(
                                    "Follow-ups", format="%d"
                                ),
                                "followups_convertidos": st.column_config.NumberColumn(
                                    "Convertidos", format="%d"
                                ),
                            },
                            hide_index=True,
                            width="stretch",
                        )

                        # Gráfico de tempo de resposta por dia
                        st.subheader("📈 Evolução do Tempo de Resposta")
                        if selected_client == "Todos":
                            cur.execute(
                                """
                                SELECT
                                    m.date as dia,
                                    ROUND(AVG(m.avg_response_time_ms)) as tempo_resposta_ms,
                                    ROUND(AVG(m.avg_resolution_time_ms)) as tempo_resolucao_ms,
                                    SUM(m.resolved_by_ai) as resolvidas_ia,
                                    SUM(m.human_takeovers) as takeovers
                                FROM metrics_daily m
                                WHERE m.date >= %s AND m.date < %s
                                GROUP BY m.date
                                ORDER BY m.date
                            """,
                                (start_date, end_date_exclusive),
                            )
                        else:
                            cur.execute(
                                """
                                SELECT
                                    m.date as dia,
                                    ROUND(AVG(m.avg_response_time_ms)) as tempo_resposta_ms,
                                    ROUND(AVG(m.avg_resolution_time_ms)) as tempo_resolucao_ms,
                                    SUM(m.resolved_by_ai) as resolvidas_ia,
                                    SUM(m.human_takeovers) as takeovers
                                FROM metrics_daily m
                                JOIN clients c ON m.client_id = c.id
                                WHERE m.date >= %s AND m.date < %s
                                AND c.name = %s
                                GROUP BY m.date
                                ORDER BY m.date
                            """,
                                (start_date, end_date_exclusive, selected_client),
                            )
                        daily_metrics = cur.fetchall()

                        if daily_metrics:
                            df_dm = _sanitize_df(pd.DataFrame(daily_metrics))
                            df_dm["dia"] = pd.to_datetime(df_dm["dia"])
                            df_dm = df_dm.set_index("dia")
                            st.line_chart(
                                df_dm[["tempo_resposta_ms", "tempo_resolucao_ms"]]
                            )
                    else:
                        st.info("Nenhuma métrica de tempo de resposta no período. Verifique se o metrics_worker está rodando.")
        except Exception as e:
            st.warning(f"⚠️ Erro ao buscar métricas de tempo: {e}")
            st.caption("Verifique se a tabela metrics_daily existe (migration 004).")

        st.divider()

        # ============================================================
        # SEÇÃO 7: FERRAMENTAS MAIS USADAS
        # ============================================================
        st.header("🔧 Ferramentas Mais Usadas")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if selected_client == "Todos":
                        cur.execute(
                            """
                            SELECT
                                event_data->>'tool' as ferramenta,
                                COUNT(*) as total_usos,
                                COUNT(DISTINCT chat_id) as conversas_distintas
                            FROM conversation_events
                            WHERE event_type = 'tool_used'
                            AND event_data ? 'tool'
                            AND created_at >= %s AND created_at < %s
                            GROUP BY ferramenta
                            ORDER BY total_usos DESC
                            LIMIT 20
                        """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                event_data->>'tool' as ferramenta,
                                COUNT(*) as total_usos,
                                COUNT(DISTINCT ce.chat_id) as conversas_distintas
                            FROM conversation_events ce
                            JOIN clients c ON ce.client_id = c.id
                            WHERE ce.event_type = 'tool_used'
                            AND ce.event_data ? 'tool'
                            AND ce.created_at >= %s AND ce.created_at < %s
                            AND c.name = %s
                            GROUP BY ferramenta
                            ORDER BY total_usos DESC
                            LIMIT 20
                        """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    tool_rows = cur.fetchall()

                    if tool_rows:
                        df_tools = _sanitize_df(pd.DataFrame(tool_rows))
                        st.dataframe(
                            df_tools,
                            column_config={
                                "ferramenta": "Ferramenta",
                                "total_usos": st.column_config.NumberColumn(
                                    "Total de Usos", format="%d"
                                ),
                                "conversas_distintas": st.column_config.NumberColumn(
                                    "Conversas Distintas", format="%d"
                                ),
                            },
                            hide_index=True,
                            width="stretch",
                        )
                        if len(df_tools) > 1:
                            st.bar_chart(df_tools.set_index("ferramenta")["total_usos"])
                    else:
                        st.info("Nenhum uso de ferramenta registrado no período.")
        except Exception as e:
            st.warning(f"⚠️ Erro ao buscar ferramentas: {e}")

        st.divider()

        # ============================================================
        # SEÇÃO 8: ATIVIDADE RECENTE (EVENTOS)
        # ============================================================
        st.header("📡 Atividade Recente de Eventos")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if selected_client == "Todos":
                        cur.execute(
                            """
                            SELECT
                                ce.event_type as tipo,
                                COUNT(*) as total
                            FROM conversation_events ce
                            WHERE ce.created_at >= %s AND ce.created_at < %s
                            GROUP BY ce.event_type
                            ORDER BY total DESC
                        """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                ce.event_type as tipo,
                                COUNT(*) as total
                            FROM conversation_events ce
                            JOIN clients c ON ce.client_id = c.id
                            WHERE ce.created_at >= %s AND ce.created_at < %s
                            AND c.name = %s
                            GROUP BY ce.event_type
                            ORDER BY total DESC
                        """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    event_rows = cur.fetchall()

                    if event_rows:
                        df_events = _sanitize_df(pd.DataFrame(event_rows))

                        # Mapear nomes legíveis
                        event_labels = {
                            "msg_received": "Mensagens Recebidas",
                            "ai_responded": "Respostas da IA",
                            "human_takeover": "Transferências p/ Humano",
                            "human_responded": "Respostas Humanas",
                            "resolved": "Conversas Resolvidas",
                            "tool_used": "Ferramentas Usadas",
                            "followup_sent": "Follow-ups Enviados",
                            "followup_converted": "Follow-ups Convertidos",
                        }
                        df_events["evento"] = df_events["tipo"].map(
                            lambda x: event_labels.get(x, x)
                        )

                        ev1, ev2 = st.columns([2, 1])
                        with ev1:
                            st.dataframe(
                                df_events[["evento", "total"]],
                                column_config={
                                    "evento": "Tipo de Evento",
                                    "total": st.column_config.NumberColumn(
                                        "Total", format="%d"
                                    ),
                                },
                                hide_index=True,
                                width="stretch",
                            )
                        with ev2:
                            st.bar_chart(df_events.set_index("evento")["total"])
                    else:
                        st.info("Nenhum evento registrado no período.")
        except Exception as e:
            st.warning(f"⚠️ Erro ao buscar eventos: {e}")

    with tab6:
        st.header("🚨 Centro de Alertas & Debug")
        st.caption("Visão 360° do sistema: erros, loops, conversas e custos.")

        try:
            from views.admin_debug_tab import render_admin_debug_tab

            render_admin_debug_tab()
        except Exception as e:
            import traceback

            st.error(f"Erro ao carregar painel de debug: {e}")
            st.code(traceback.format_exc(), language="python")
            st.info("Verifique se o arquivo `views/admin_debug_tab.py` existe.")
