import streamlit as st
import pandas as pd
from datetime import datetime
from scripts.shared.saas_db import get_connection


def render_monitoring_tab(user_data):
    st.header("📊 Monitoramento em Tempo Real")
    st.caption("Acompanhe os lembretes agendados e os follow-ups em andamento.")

    tab1, tab2, tab3 = st.tabs(["📅 Lembretes", "💬 Follow-ups", "🐞 Logs de Erro"])

    # --- TAB 1: LEMBRETES ---
    with tab1:
        st.subheader("Lembretes Pendentes")

        # Action: Cancel Reminder
        if "cancel_reminder" in st.session_state:
            r_id = st.session_state.pop("cancel_reminder")
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE reminders SET status = 'cancelled' WHERE id = %s AND client_id = %s",
                            (r_id, user_data["id"]),
                        )
                st.success(f"Lembrete {r_id} cancelado!")
            except Exception as e:
                st.error(f"Erro ao cancelar: {e}")

        # Query Reminders
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, chat_id, scheduled_at, message, status 
                        FROM reminders 
                        WHERE client_id = %s AND status = 'pending'
                        ORDER BY scheduled_at ASC
                    """,
                        (user_data["id"],),
                    )
                    rows = cur.fetchall()

            if rows:
                df = pd.DataFrame(rows)
                # Format Date
                df["scheduled_at"] = pd.to_datetime(df["scheduled_at"]).dt.strftime(
                    "%d/%m/%Y %H:%M"
                )

                # Display as detailed cards or table
                for index, row in df.iterrows():
                    with st.expander(f"📅 {row['scheduled_at']} - {row['chat_id']}"):
                        st.write(f"**Mensagem:** {row['message']}")
                        st.write(f"**Status:** {row['status']}")
                        if st.button(
                            "❌ Cancelar Lembrete", key=f"btn_cancel_{row['id']}"
                        ):
                            st.session_state["cancel_reminder"] = row["id"]
                            st.rerun()
            else:
                st.info("Nenhum lembrete pendente.")

        except Exception as e:
            st.warning(f"Erro ao buscar lembretes (Tabela existe?): {e}")

    # --- TAB 2: ACTIVE FOLLOW-UPS ---
    with tab2:
        st.subheader("Conversas em Acompanhamento")

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT chat_id, status, followup_stage, last_message_at, last_role
                        FROM active_conversations
                        WHERE client_id = %s AND status = 'active'
                        ORDER BY last_message_at DESC
                    """,
                        (user_data["id"],),
                    )
                    rows = cur.fetchall()

            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(
                    df,
                    column_config={
                        "last_message_at": st.column_config.DatetimeColumn(
                            "Última Msg", format="DD/MM/YYYY HH:mm"
                        ),
                        "followup_stage": "Estágio",
                    },
                    width="stretch",
                )
            else:
                st.info("Nenhuma conversa ativa no momento.")

        except Exception as e:
            st.error(f"Erro ao buscar conversas: {e}")

    # --- TAB 3: ERROR LOGS (NEW) ---
    with tab3:
        st.subheader("🐞 Logs de Erro (Sistema)")
        st.caption(
            "Visualize erros recentes para debug. Mostrando últimos 50 registros."
        )

        if st.button("🔄 Atualizar Logs"):
            st.rerun()

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Tenta criar se não existir (garantia visual)
                    # Mas o backend já cria.
                    cur.execute(
                        """
                        SELECT id, timestamp, source, error_type, message, traceback, client_id, chat_id, memory_usage, context_data
                        FROM error_logs
                        ORDER BY timestamp DESC
                        LIMIT 50
                        """
                    )
                    error_rows = cur.fetchall()

            if error_rows:
                for err in error_rows:
                    ts = err["timestamp"].strftime("%d/%m %H:%M:%S")
                    label = f"🚨 [{ts}] {err['source']} - {err['error_type']}"

                    with st.expander(label):
                        st.error(f"**Mensagem:** {err['message']}")

                        c1, c2, c3 = st.columns(3)
                        c1.metric("Client ID", err["client_id"] or "N/A")
                        c2.metric("Chat ID", err["chat_id"] or "N/A")
                        c3.metric("Memória", err["memory_usage"] or "N/A")

                        st.text_area("Traceback", err["traceback"], height=200)

                        if err["context_data"]:
                            st.json(err["context_data"])
            else:
                st.success("🎉 Nenhum erro registrado recentemente!")

        except Exception as e:
            if 'relation "error_logs" does not exist' in str(e):
                st.warning(
                    "⚠️ Tabela de logs ainda não criada (será criada no primeiro erro)."
                )
            else:
                st.error(f"Erro ao buscar logs: {e}")
