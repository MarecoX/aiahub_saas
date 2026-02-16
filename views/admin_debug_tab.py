"""
🚨 Centro de Alertas & Debug — Admin Dashboard
Painel completo com visão 360° do sistema.
"""

import streamlit as st
import pandas as pd

# Imports do projeto
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts", "shared"))

from shared.saas_db import get_connection

from shared.debug_queries import (
    get_system_health,
    get_error_logs_filtered,
    get_error_types,
    get_loop_suspects,
    get_conversation_history,
    cleanup_old_errors,
)

try:
    from shared.saas_db import clear_chat_history
except ImportError:

    def clear_chat_history(t_id):
        return False


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


def render_admin_debug_tab():
    """Renderiza o painel completo de Debug & Alertas."""

    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "📊 Saúde do Sistema",
            "🐞 Errors & Bugs",
            "🔄 Loop Detector",
            "💬 Conversation Inspector",
        ]
    )

    # =========================================================
    # TAB 1: SAÚDE DO SISTEMA
    # =========================================================
    with tab1:
        st.subheader("📊 Visão Geral do Sistema")

        if st.button("🔄 Atualizar", key="refresh_health"):
            st.rerun()

        health = get_system_health()

        # Métricas principais
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("👥 Clientes", health["total_clients"])
        col2.metric("💬 Conversas Ativas", health["active_conversations"])
        col3.metric("🐞 Erros (24h)", health["errors_24h"])
        col4.metric("💰 Custo (24h)", f"${health['cost_24h']:.4f}")

        st.markdown("---")

        # Gráfico de erros por hora
        if health["errors_by_hour"]:
            st.subheader("📈 Erros por Hora (Últimas 48h)")
            df_errors = _sanitize_df(pd.DataFrame(health["errors_by_hour"]))
            df_errors["hora"] = pd.to_datetime(df_errors["hora"])
            df_errors = df_errors.set_index("hora")
            st.bar_chart(df_errors["total"])
        else:
            st.success("🎉 Nenhum erro nas últimas 48 horas!")

        # Top clientes com erros
        if health["top_error_clients"]:
            st.subheader("🔥 Top Clientes com Erros (24h)")
            df_top = _sanitize_df(pd.DataFrame(health["top_error_clients"]))
            st.dataframe(
                df_top,
                column_config={
                    "client_name": "Cliente",
                    "error_count": st.column_config.NumberColumn("Erros", format="%d"),
                },
                hide_index=True,
                width="stretch",
            )

    # =========================================================
    # TAB 2: ERRORS & BUGS
    # =========================================================
    with tab2:
        st.subheader("🐞 Logs de Erro Detalhados")

        # Filtros
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            # Dropdown de clientes
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT id, name FROM clients ORDER BY name")
                        clients_list = cur.fetchall()
                client_options = {"Todos": None}
                for c in clients_list:
                    client_options[c["name"]] = str(c["id"])
                selected_client = st.selectbox(
                    "Filtrar por Cliente",
                    list(client_options.keys()),
                    key="err_client_filter",
                )
            except Exception:
                client_options = {"Todos": None}
                selected_client = "Todos"

        with col_f2:
            error_types = get_error_types()
            type_options = ["Todos"] + error_types
            selected_type = st.selectbox(
                "Tipo de Erro", type_options, key="err_type_filter"
            )

        with col_f3:
            days_filter = st.slider(
                "Período (dias)", min_value=1, max_value=90, value=7, key="err_days"
            )

        # Buscar erros
        errors = get_error_logs_filtered(
            client_id=client_options.get(selected_client),
            error_type=selected_type if selected_type != "Todos" else None,
            days=days_filter,
        )

        if errors:
            st.caption(f"Mostrando {len(errors)} erros encontrados.")

            for err in errors:
                ts = err["timestamp"].strftime("%d/%m %H:%M:%S")
                label = f"🚨 [{ts}] {err['source']} — {err['error_type']}"

                with st.expander(label):
                    st.error(f"**Mensagem:** {err['message']}")

                    c1, c2, c3 = st.columns(3)
                    c1.metric("Client ID", err["client_id"] or "N/A")
                    c2.metric("Chat ID", err["chat_id"] or "N/A")
                    c3.metric("Memória", err["memory_usage"] or "N/A")

                    if err["traceback"]:
                        st.code(err["traceback"], language="python")

                    if err["context_data"]:
                        st.json(err["context_data"])
        else:
            st.success("🎉 Nenhum erro encontrado neste período!")

        st.markdown("---")

        # Limpeza
        col_clean1, col_clean2 = st.columns([3, 1])
        with col_clean1:
            clean_days = st.number_input(
                "Limpar erros mais antigos que (dias):",
                min_value=7,
                value=30,
                key="clean_days",
            )
        with col_clean2:
            st.write("")  # Spacer
            st.write("")
            if st.button("🗑️ Limpar Logs Antigos", type="secondary"):
                deleted = cleanup_old_errors(days=clean_days)
                st.success(f"✅ {deleted} logs removidos!")

    # =========================================================
    # TAB 3: LOOP DETECTOR
    # =========================================================
    with tab3:
        st.subheader("🔄 Detector de Loops de Recursão")
        st.caption(
            "Identifica chats que fizeram muitas chamadas de IA em pouco tempo, "
            "indicando possíveis loops de ferramenta."
        )

        col_l1, col_l2 = st.columns(2)
        with col_l1:
            min_calls = st.number_input(
                "Mínimo de chamadas",
                min_value=3,
                value=5,
                key="loop_min_calls",
                help="Quantas chamadas para considerar suspeito",
            )
        with col_l2:
            window_min = st.number_input(
                "Janela de tempo (minutos)",
                min_value=1,
                value=2,
                key="loop_window",
                help="Período máximo entre primeira e última chamada",
            )

        if st.button("🔍 Detectar Loops", key="detect_loops"):
            suspects = get_loop_suspects(min_calls=min_calls, window_minutes=window_min)

            if suspects:
                st.warning(f"⚠️ {len(suspects)} suspeitos de loop encontrados!")

                for s in suspects:
                    duration = s.get("duration_seconds", 0)
                    duration_str = f"{duration:.0f}s" if duration else "N/A"

                    with st.expander(
                        f"🔄 {s['client_name'] or 'N/A'} — {s['chat_id']} "
                        f"({s['call_count']} chamadas em {duration_str})"
                    ):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Chamadas", s["call_count"])
                        c2.metric("Duração", duration_str)
                        c3.metric("Custo", f"${float(s.get('total_cost', 0)):.4f}")

                        st.text(f"Primeira: {s.get('first_call', 'N/A')}")
                        st.text(f"Última: {s.get('last_call', 'N/A')}")

                        # Botão de limpeza
                        clean_key = f"clean_loop_{s['chat_id']}_{s['client_id']}"
                        if st.button(
                            "🧹 Limpar Histórico deste Chat",
                            key=clean_key,
                        ):
                            client_id_str = (
                                str(s["client_id"]) if s["client_id"] else ""
                            )
                            thread_id = f"{client_id_str}:{s['chat_id']}"
                            if clear_chat_history(thread_id):
                                st.success("✅ Histórico limpo!")
                            else:
                                st.error("❌ Falha ao limpar.")
            else:
                st.success("🎉 Nenhum loop detectado nos últimos 7 dias!")

    # =========================================================
    # TAB 4: CONVERSATION INSPECTOR
    # =========================================================
    with tab4:
        st.subheader("💬 Inspetor de Conversas")
        st.caption("Inspecione o histórico completo de um chat para debug.")

        # Seletor de cliente
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name FROM clients ORDER BY name")
                    clients_data = cur.fetchall()

            if clients_data:
                client_dict = {row["name"]: str(row["id"]) for row in clients_data}
                selected_client_name = st.selectbox(
                    "Cliente:",
                    list(client_dict.keys()),
                    key="inspect_client",
                )
                selected_client_id = client_dict[selected_client_name]

                chat_id_input = st.text_input(
                    "Chat ID (telefone com código do país):",
                    placeholder="Ex: 5511999999999@s.whatsapp.net",
                    key="inspect_chat_id",
                )

                if st.button("🔍 Inspecionar", key="btn_inspect") and chat_id_input:
                    data = get_conversation_history(selected_client_id, chat_id_input)

                    # Estado da conversa
                    if data["state"]:
                        st.subheader("📋 Estado da Conversa")
                        state = data["state"]
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Status", state.get("status", "N/A"))
                        c2.metric("Estágio", state.get("followup_stage", "N/A"))
                        c3.metric("Último Role", state.get("last_role", "N/A"))
                        last_msg_at = state.get("last_message_at")
                        c4.metric(
                            "Última Msg",
                            last_msg_at.strftime("%d/%m %H:%M")
                            if last_msg_at
                            else "N/A",
                        )

                        if state.get("last_context"):
                            with st.expander("📝 Contexto Resumido"):
                                st.text(state["last_context"])

                    # Mensagens
                    if data["messages"]:
                        st.subheader(f"💬 Histórico ({len(data['messages'])} msgs)")

                        for msg in reversed(data["messages"]):
                            role = msg["role"]
                            content = msg["content"] or ""
                            ts = msg["created_at"].strftime("%d/%m %H:%M")

                            if role == "user":
                                st.chat_message("user").write(f"**[{ts}]** {content}")
                            else:
                                st.chat_message("assistant").write(
                                    f"**[{ts}]** {content}"
                                )

                            if msg.get("media_url"):
                                st.caption(f"📎 Mídia: {msg['media_url']}")
                    else:
                        st.info("Nenhuma mensagem encontrada para este chat.")

                    # Botão de limpeza
                    st.markdown("---")
                    if st.button(
                        "🧹 Limpar Memória (LangGraph Checkpointer)",
                        key="btn_clear_inspector",
                    ):
                        thread_id = f"{selected_client_id}:{chat_id_input}"
                        if clear_chat_history(thread_id):
                            st.success("✅ Memória de curto prazo limpa!")
                        else:
                            st.error("❌ Falha ao limpar.")
            else:
                st.info("Nenhum cliente cadastrado.")
        except Exception as e:
            st.error(f"Erro ao carregar dados: {e}")

