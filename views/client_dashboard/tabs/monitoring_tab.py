import streamlit as st
import pandas as pd
from datetime import datetime
from scripts.shared.saas_db import get_connection


def render_monitoring_tab(user_data):
    st.header("📊 Monitoramento em Tempo Real")
    st.caption("Acompanhe os lembretes agendados e os follow-ups em andamento.")

    tab1, tab2 = st.tabs(["📅 Lembretes Agendados", "💬 Follow-ups Ativos"])

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
