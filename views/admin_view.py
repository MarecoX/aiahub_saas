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
        # --- FILTROS ---
        df_clients = list_clients()
        client_names = ["Todos"] + (
            df_clients["name"].tolist() if not df_clients.empty else []
        )

        fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
        with fcol1:
            selected_client = st.selectbox(
                "Filtrar por Cliente", client_names, key="consumo_filter"
            )
        with fcol2:
            start_date = st.date_input(
                "De", value=datetime.now() - timedelta(days=30), key="consumo_de"
            )
        with fcol3:
            end_date = st.date_input(
                "Ate", value=datetime.now(), key="consumo_ate"
            )

        end_date_exclusive = end_date + timedelta(days=1)

        # Helpers reutilizaveis para filtro de cliente
        _cli_where = "AND c.name = %s" if selected_client != "Todos" else ""
        _cli_params = (selected_client,) if selected_client != "Todos" else ()

        # ============================================================
        #  1) AGORA: O QUE ESTA ACONTECENDO NAS ULTIMAS 24H
        # ============================================================
        st.markdown("---")
        st.header("O que esta acontecendo agora (ultimas 24h)")
        st.caption(
            "Conversas ativas neste momento. "
            "Quem a IA ja respondeu, quem o humano respondeu, e quem esta esperando."
        )

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT
                            c.name as cliente,
                            COUNT(*) as total,
                            COUNT(CASE WHEN ac.last_role = 'ai' THEN 1 END) as ia_respondeu,
                            COUNT(CASE WHEN ac.last_role = 'human' THEN 1 END) as humano_respondeu,
                            COUNT(CASE WHEN ac.last_role = 'user'
                                       AND ac.last_message_at < NOW() - INTERVAL '5 minutes'
                                  THEN 1 END) as esperando_resposta
                        FROM active_conversations ac
                        JOIN clients c ON ac.client_id = c.id
                        WHERE ac.status = 'active'
                          AND ac.last_message_at > NOW() - INTERVAL '24 hours'
                        {_cli_where}
                        GROUP BY c.name
                        ORDER BY esperando_resposta DESC
                        """,
                        _cli_params,
                    )
                    rows = cur.fetchall()

                    if rows:
                        df_rt = _sanitize_df(pd.DataFrame(rows))
                        t_total = int(df_rt["total"].sum())
                        t_ia = int(df_rt["ia_respondeu"].sum())
                        t_hum = int(df_rt["humano_respondeu"].sum())
                        t_esp = int(df_rt["esperando_resposta"].sum())

                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Conversas Ativas", t_total)
                        c2.metric("IA Respondeu", t_ia)
                        c3.metric("Humano Respondeu", t_hum)
                        c4.metric("Esperando Resposta", t_esp)

                        if t_total > 0:
                            p1, p2, p3 = st.columns(3)
                            p1.metric("% pela IA", f"{t_ia / t_total * 100:.0f}%")
                            p2.metric("% pelo Humano", f"{t_hum / t_total * 100:.0f}%")
                            p3.metric("% Sem Resposta", f"{t_esp / t_total * 100:.0f}%")

                        st.dataframe(
                            df_rt,
                            column_config={
                                "cliente": "Cliente",
                                "total": st.column_config.NumberColumn("Total Conversas", format="%d"),
                                "ia_respondeu": st.column_config.NumberColumn("IA Respondeu", format="%d"),
                                "humano_respondeu": st.column_config.NumberColumn("Humano Respondeu", format="%d"),
                                "esperando_resposta": st.column_config.NumberColumn("Esperando Resposta", format="%d"),
                            },
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.info("Nenhuma conversa ativa nas ultimas 24h.")
        except Exception as e:
            st.warning(f"Erro ao buscar conversas ativas: {e}")

        # ============================================================
        #  2) FUNIL DE VENDAS: TODOS OS LEADS FORAM ATENDIDOS?
        # ============================================================
        st.markdown("---")
        st.header("Todos os leads foram atendidos? (periodo selecionado)")
        st.caption(
            "De todos os leads que chegaram, quantos a IA resolveu sozinha, "
            "em quantos o humano precisou entrar, e quantos ficaram sem resolucao (possivel perda de venda)."
        )

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT
                            c.name as cliente,
                            COALESCE(SUM(m.total_conversations), 0)::int as total_leads,
                            COALESCE(SUM(m.resolved_by_ai), 0)::int as ia_resolveu,
                            COALESCE(SUM(m.resolved_by_human), 0)::int as humano_resolveu,
                            COALESCE(SUM(m.human_takeovers), 0)::int as humano_entrou,
                            COALESCE(SUM(m.followups_sent), 0)::int as followups,
                            COALESCE(SUM(m.followups_converted), 0)::int as followups_ok,
                            COALESCE(SUM(m.total_messages_in), 0)::int as msgs_recebidas,
                            COALESCE(SUM(m.total_messages_out), 0)::int as msgs_enviadas,
                            ROUND(COALESCE(AVG(m.avg_response_time_ms), 0))::int as tempo_resposta_ms
                        FROM metrics_daily m
                        JOIN clients c ON m.client_id = c.id
                        WHERE m.date >= %s AND m.date < %s
                        {_cli_where}
                        GROUP BY c.name
                        ORDER BY total_leads DESC
                        """,
                        (start_date, end_date_exclusive) + _cli_params,
                    )
                    rows = cur.fetchall()

                    if rows:
                        df = _sanitize_df(pd.DataFrame(rows))

                        total_leads = int(df["total_leads"].sum())
                        total_ia = int(df["ia_resolveu"].sum())
                        total_hum_resolveu = int(df["humano_resolveu"].sum())
                        total_hum_entrou = int(df["humano_entrou"].sum())
                        total_resolvidos = total_ia + total_hum_resolveu
                        total_sem_resolucao = max(0, total_leads - total_resolvidos)
                        total_fup = int(df["followups"].sum())
                        total_fup_ok = int(df["followups_ok"].sum())

                        # --- RESUMO VISUAL ---
                        st.subheader("Resumo Geral")
                        k1, k2, k3, k4 = st.columns(4)
                        k1.metric("Total de Leads", total_leads,
                                  help="Quantidade de conversas unicas que chegaram no periodo")
                        k2.metric("IA Resolveu Sozinha", total_ia,
                                  help="Lead resolvido 100% pela IA, sem nenhum humano intervir")
                        k3.metric("Humano Precisou Entrar", total_hum_resolveu + total_hum_entrou,
                                  help="Um atendente humano precisou assumir a conversa")
                        k4.metric("Sem Resolucao (PERDA)", total_sem_resolucao,
                                  help="O lead falou com a IA mas ninguem resolveu — possivel perda de venda!")

                        # --- TAXAS ---
                        if total_leads > 0:
                            pct_ia = total_ia / total_leads * 100
                            pct_hum = (total_hum_resolveu + total_hum_entrou) / total_leads * 100
                            pct_perda = total_sem_resolucao / total_leads * 100

                            t1, t2, t3 = st.columns(3)
                            t1.metric("Taxa IA (sem humano)", f"{pct_ia:.1f}%",
                                      help="% dos leads que a IA resolveu sozinha")
                            t2.metric("Taxa Humano Necessario", f"{pct_hum:.1f}%",
                                      help="% dos leads onde o humano teve que intervir")
                            t3.metric("Taxa de Perda", f"{pct_perda:.1f}%",
                                      help="% dos leads sem resolucao — possivel erro de vendas!")

                            if pct_perda > 20:
                                st.error(
                                    f"ATENCAO: {pct_perda:.0f}% dos leads ficaram sem resolucao! "
                                    f"Isso significa que {total_sem_resolucao} pessoas podem ter desistido."
                                )
                            elif pct_perda > 10:
                                st.warning(
                                    f"Atencao: {pct_perda:.0f}% dos leads sem resolucao ({total_sem_resolucao} leads)."
                                )

                        # --- FOLLOW-UPS ---
                        if total_fup > 0:
                            fu1, fu2, fu3 = st.columns(3)
                            fu1.metric("Follow-ups Enviados", total_fup)
                            fu2.metric("Follow-ups que Deram Certo", total_fup_ok)
                            fu3.metric("Taxa de Conversao",
                                       f"{total_fup_ok / total_fup * 100:.1f}%")

                        # --- VOLUME ---
                        total_msgs_in = int(df["msgs_recebidas"].sum())
                        total_msgs_out = int(df["msgs_enviadas"].sum())
                        m1, m2 = st.columns(2)
                        m1.metric("Mensagens Recebidas (clientes)", f"{total_msgs_in:,}")
                        m2.metric("Mensagens Enviadas (IA + humano)", f"{total_msgs_out:,}")

                        # --- TABELA POR CLIENTE ---
                        st.subheader("Detalhamento por Cliente")
                        df["sem_resolucao"] = (df["total_leads"] - df["ia_resolveu"] - df["humano_resolveu"]).clip(lower=0)
                        df["taxa_ia"] = (df["ia_resolveu"] / df["total_leads"].replace(0, 1) * 100).round(1)
                        df["taxa_perda"] = (df["sem_resolucao"] / df["total_leads"].replace(0, 1) * 100).round(1)

                        st.dataframe(
                            df[["cliente", "total_leads", "ia_resolveu", "humano_resolveu",
                                "humano_entrou", "sem_resolucao", "taxa_ia", "taxa_perda",
                                "followups", "followups_ok"]],
                            column_config={
                                "cliente": "Cliente",
                                "total_leads": st.column_config.NumberColumn("Total Leads", format="%d"),
                                "ia_resolveu": st.column_config.NumberColumn("IA Resolveu", format="%d"),
                                "humano_resolveu": st.column_config.NumberColumn("Humano Resolveu", format="%d"),
                                "humano_entrou": st.column_config.NumberColumn("Humano Entrou", format="%d"),
                                "sem_resolucao": st.column_config.NumberColumn("Sem Resolucao", format="%d"),
                                "taxa_ia": st.column_config.NumberColumn("% IA", format="%.1f%%"),
                                "taxa_perda": st.column_config.NumberColumn("% Perda", format="%.1f%%"),
                                "followups": st.column_config.NumberColumn("Follow-ups", format="%d"),
                                "followups_ok": st.column_config.NumberColumn("Convertidos", format="%d"),
                            },
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.info("Nenhum dado no periodo. Verifique se o metrics_worker esta rodando.")
        except Exception as e:
            st.warning(f"Erro ao buscar funil de vendas: {e}")
            st.caption("Verifique se a tabela metrics_daily existe (migration 004).")

        # ============================================================
        #  3) FERRAMENTAS: QUAL E A MAIS USADA? POR CLIENTE?
        # ============================================================
        st.markdown("---")
        st.header("Qual ferramenta e a mais usada?")
        st.caption(
            "Ranking das ferramentas da IA (consultar CEP, viabilidade, CRM, etc). "
            "Quantas vezes cada uma foi chamada e qual cliente mais usa cada ferramenta."
        )

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # ---- RANKING GERAL ----
                    if selected_client == "Todos":
                        cur.execute(
                            """
                            SELECT
                                event_data->>'tool' as ferramenta,
                                COUNT(*) as vezes_usada,
                                COUNT(DISTINCT ce.chat_id) as em_quantas_conversas,
                                COUNT(DISTINCT ce.client_id) as quantos_clientes
                            FROM conversation_events ce
                            WHERE ce.event_type = 'tool_used'
                              AND ce.event_data ? 'tool'
                              AND ce.created_at >= %s AND ce.created_at < %s
                            GROUP BY ferramenta
                            ORDER BY vezes_usada DESC
                            LIMIT 20
                            """,
                            (start_date, end_date_exclusive),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                event_data->>'tool' as ferramenta,
                                COUNT(*) as vezes_usada,
                                COUNT(DISTINCT ce.chat_id) as em_quantas_conversas,
                                1 as quantos_clientes
                            FROM conversation_events ce
                            JOIN clients c ON ce.client_id = c.id
                            WHERE ce.event_type = 'tool_used'
                              AND ce.event_data ? 'tool'
                              AND ce.created_at >= %s AND ce.created_at < %s
                              AND c.name = %s
                            GROUP BY ferramenta
                            ORDER BY vezes_usada DESC
                            LIMIT 20
                            """,
                            (start_date, end_date_exclusive, selected_client),
                        )
                    tool_rows = cur.fetchall()

                    if tool_rows:
                        df_tools = _sanitize_df(pd.DataFrame(tool_rows))
                        top = df_tools.iloc[0]
                        st.success(
                            f"Ferramenta mais usada: **{top['ferramenta']}** "
                            f"— usada **{int(top['vezes_usada'])}** vezes "
                            f"em **{int(top['em_quantas_conversas'])}** conversas"
                        )

                        tc1, tc2 = st.columns([2, 1])
                        with tc1:
                            st.dataframe(
                                df_tools,
                                column_config={
                                    "ferramenta": "Ferramenta",
                                    "vezes_usada": st.column_config.NumberColumn("Vezes Usada", format="%d"),
                                    "em_quantas_conversas": st.column_config.NumberColumn("Em Quantas Conversas", format="%d"),
                                    "quantos_clientes": st.column_config.NumberColumn("Quantos Clientes Usam", format="%d"),
                                },
                                hide_index=True,
                                width="stretch",
                            )
                        with tc2:
                            if len(df_tools) > 1:
                                st.bar_chart(df_tools.set_index("ferramenta")["vezes_usada"])

                        # ---- QUAL CLIENTE USA QUAL FERRAMENTA ----
                        st.subheader("Qual cliente usa qual ferramenta?")
                        cur.execute(
                            f"""
                            SELECT
                                c.name as cliente,
                                event_data->>'tool' as ferramenta,
                                COUNT(*) as vezes,
                                COUNT(DISTINCT ce.chat_id) as conversas
                            FROM conversation_events ce
                            JOIN clients c ON ce.client_id = c.id
                            WHERE ce.event_type = 'tool_used'
                              AND ce.event_data ? 'tool'
                              AND ce.created_at >= %s AND ce.created_at < %s
                              {_cli_where}
                            GROUP BY c.name, ferramenta
                            ORDER BY c.name, vezes DESC
                            """,
                            (start_date, end_date_exclusive) + _cli_params,
                        )
                        tool_cli_rows = cur.fetchall()

                        if tool_cli_rows:
                            df_tc = _sanitize_df(pd.DataFrame(tool_cli_rows))
                            st.dataframe(
                                df_tc,
                                column_config={
                                    "cliente": "Cliente",
                                    "ferramenta": "Ferramenta",
                                    "vezes": st.column_config.NumberColumn("Vezes Usada", format="%d"),
                                    "conversas": st.column_config.NumberColumn("Em Quantas Conversas", format="%d"),
                                },
                                hide_index=True,
                                width="stretch",
                            )

                            # Resumo: top 1 por cliente
                            st.subheader("Ferramenta favorita de cada cliente")
                            top_per_cli = df_tc.loc[df_tc.groupby("cliente")["vezes"].idxmax()]
                            for _, r in top_per_cli.iterrows():
                                st.info(
                                    f"**{r['cliente']}** usa mais: "
                                    f"**{r['ferramenta']}** ({int(r['vezes'])} vezes)"
                                )
                    else:
                        st.info("Nenhuma ferramenta foi usada no periodo selecionado.")
        except Exception as e:
            st.warning(f"Erro ao buscar ferramentas: {e}")

        # ============================================================
        #  4) EVOLUCAO DIA A DIA (GRAFICO)
        # ============================================================
        st.markdown("---")
        st.header("Evolucao dia a dia")
        st.caption("Como os leads, resolucoes e perdas variaram por dia no periodo.")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT
                            m.date as dia,
                            COALESCE(SUM(m.total_conversations), 0)::int as leads,
                            COALESCE(SUM(m.resolved_by_ai), 0)::int as ia_resolveu,
                            COALESCE(SUM(m.resolved_by_human), 0)::int as humano_resolveu,
                            COALESCE(SUM(m.human_takeovers), 0)::int as humano_entrou,
                            ROUND(COALESCE(AVG(m.avg_response_time_ms), 0))::int as tempo_resposta_ms
                        FROM metrics_daily m
                        JOIN clients c ON m.client_id = c.id
                        WHERE m.date >= %s AND m.date < %s
                        {_cli_where}
                        GROUP BY m.date
                        ORDER BY m.date
                        """,
                        (start_date, end_date_exclusive) + _cli_params,
                    )
                    daily_rows = cur.fetchall()

                    if daily_rows:
                        df_d = _sanitize_df(pd.DataFrame(daily_rows))
                        df_d["dia"] = pd.to_datetime(df_d["dia"])
                        df_d["sem_resolucao"] = (df_d["leads"] - df_d["ia_resolveu"] - df_d["humano_resolveu"]).clip(lower=0)
                        df_dc = df_d.set_index("dia")

                        st.subheader("Leads vs Quem Resolveu")
                        st.line_chart(df_dc[["leads", "ia_resolveu", "humano_resolveu", "sem_resolucao"]])

                        st.subheader("Tempo de Resposta da IA (milissegundos)")
                        st.line_chart(df_dc[["tempo_resposta_ms"]])
                    else:
                        st.info("Sem dados diarios no periodo.")
        except Exception as e:
            st.warning(f"Erro ao gerar graficos: {e}")

        # ============================================================
        #  5) CUSTOS (QUANTO ESTA GASTANDO)
        # ============================================================
        st.markdown("---")
        st.header("Custos de IA (quanto esta gastando)")
        st.caption("Custos de OpenAI, Gemini e Whisper por cliente e por dia.")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    _cost_where = "AND c.name = %s" if selected_client != "Todos" else ""
                    _cost_join = "JOIN clients c ON u.client_id = c.id" if selected_client != "Todos" else ""
                    _cost_params = (start_date, end_date_exclusive) + _cli_params

                    # Grafico diario
                    cur.execute(
                        f"""
                        SELECT DATE(u.created_at) as dia,
                               ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                               ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                        FROM usage_tracking u
                        {_cost_join}
                        WHERE u.created_at >= %s AND u.created_at < %s
                        {_cost_where}
                        GROUP BY dia
                        ORDER BY dia
                        """,
                        _cost_params,
                    )
                    chart_rows = cur.fetchall()
                    if chart_rows:
                        df_ch = _sanitize_df(pd.DataFrame(chart_rows))
                        df_ch["dia"] = pd.to_datetime(df_ch["dia"])
                        st.line_chart(df_ch.set_index("dia")[["custo_usd", "custo_brl"]])

                    # Totais
                    cur.execute(
                        f"""
                        SELECT
                            COUNT(DISTINCT u.chat_id) as total_conversas,
                            ROUND(COALESCE(SUM(u.cost_usd), 0)::numeric, 4) as total_usd,
                            ROUND(COALESCE(SUM(u.cost_usd * 12), 0)::numeric, 2) as total_brl,
                            COALESCE(SUM(u.openai_input_tokens + u.openai_output_tokens), 0) as tokens_openai,
                            COALESCE(SUM(u.gemini_input_tokens + u.gemini_output_tokens), 0) as tokens_gemini,
                            COALESCE(SUM(u.whisper_seconds), 0) as segundos_audio,
                            COALESCE(SUM(u.images_count), 0) as imagens
                        FROM usage_tracking u
                        {_cost_join}
                        WHERE u.created_at >= %s AND u.created_at < %s
                        {_cost_where}
                        """,
                        _cost_params,
                    )
                    tot = cur.fetchone()

                    if tot and float(tot.get("total_usd") or 0) > 0:
                        st.subheader("Resumo do Periodo")
                        r1, r2, r3 = st.columns(3)
                        r1.metric("Custo Total",
                                  f"R$ {float(tot['total_brl']):.2f}",
                                  f"USD {float(tot['total_usd']):.4f}")
                        r2.metric("Conversas Atendidas", int(tot["total_conversas"]))
                        r3.metric("Imagens Processadas", int(tot["imagens"]))

                        r4, r5, r6 = st.columns(3)
                        r4.metric("Tokens OpenAI", f"{int(tot['tokens_openai']):,}")
                        r5.metric("Tokens Gemini", f"{int(tot['tokens_gemini']):,}")
                        r6.metric("Audio Transcrito (seg)", f"{int(tot['segundos_audio']):,}")

                    # Por provider e cliente
                    st.subheader("Custo por Cliente e Modelo de IA")
                    cur.execute(
                        f"""
                        SELECT
                            c.name as cliente,
                            u.provider as modelo_ia,
                            COUNT(DISTINCT u.chat_id) as conversas,
                            ROUND(SUM(u.cost_usd)::numeric, 4) as custo_usd,
                            ROUND(SUM(u.cost_usd * 12)::numeric, 2) as custo_brl
                        FROM usage_tracking u
                        JOIN clients c ON u.client_id = c.id
                        WHERE u.created_at >= %s AND u.created_at < %s
                        {_cli_where}
                        GROUP BY c.name, u.provider
                        ORDER BY custo_brl DESC
                        """,
                        (start_date, end_date_exclusive) + _cli_params,
                    )
                    prov_rows = cur.fetchall()
                    if prov_rows:
                        df_prov = _sanitize_df(pd.DataFrame(prov_rows))
                        st.dataframe(
                            df_prov,
                            column_config={
                                "cliente": "Cliente",
                                "modelo_ia": "Modelo de IA",
                                "conversas": st.column_config.NumberColumn("Conversas", format="%d"),
                                "custo_usd": st.column_config.NumberColumn("Custo (USD)", format="$%.4f"),
                                "custo_brl": st.column_config.NumberColumn("Custo (BRL)", format="R$%.2f"),
                            },
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.info("Nenhum dado de custo no periodo.")
        except Exception as e:
            st.warning(f"Erro ao buscar custos: {e}")

        # ============================================================
        #  6) REGISTRO TECNICO DE EVENTOS (ESCONDIDO POR PADRAO)
        # ============================================================
        st.markdown("---")
        with st.expander("Ver registro tecnico de eventos (avancado)", expanded=False):
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT ce.event_type as tipo, COUNT(*) as total
                            FROM conversation_events ce
                            {"JOIN clients c ON ce.client_id = c.id" if selected_client != "Todos" else ""}
                            WHERE ce.created_at >= %s AND ce.created_at < %s
                            {_cli_where}
                            GROUP BY ce.event_type
                            ORDER BY total DESC
                            """,
                            (start_date, end_date_exclusive) + _cli_params,
                        )
                        event_rows = cur.fetchall()
                        if event_rows:
                            df_ev = _sanitize_df(pd.DataFrame(event_rows))
                            labels = {
                                "msg_received": "Mensagens Recebidas",
                                "ai_responded": "Respostas da IA",
                                "human_takeover": "Humano Assumiu",
                                "human_responded": "Humano Respondeu",
                                "resolved": "Conversa Resolvida",
                                "tool_used": "Ferramenta Usada",
                                "followup_sent": "Follow-up Enviado",
                                "followup_converted": "Follow-up Convertido",
                            }
                            df_ev["evento"] = df_ev["tipo"].map(lambda x: labels.get(x, x))
                            ev1, ev2 = st.columns([2, 1])
                            with ev1:
                                st.dataframe(
                                    df_ev[["evento", "total"]],
                                    column_config={
                                        "evento": "Tipo de Evento",
                                        "total": st.column_config.NumberColumn("Total", format="%d"),
                                    },
                                    hide_index=True,
                                    width="stretch",
                                )
                            with ev2:
                                st.bar_chart(df_ev.set_index("evento")["total"])
                        else:
                            st.info("Nenhum evento no periodo.")
            except Exception as e:
                st.warning(f"Erro ao buscar eventos: {e}")

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
