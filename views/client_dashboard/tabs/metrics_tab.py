import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from scripts.shared.saas_db import (
    get_metrics_summary,
    get_tools_usage_breakdown,
    get_conversations_by_handler,
    get_response_time_stats,
    get_followup_stats,
    get_resolution_stats,
    get_metrics_daily_series,
    get_connection,
    update_tools_config_db,
)


def render_metrics_tab(user_data):
    """Dashboard de Metricas completo para o cliente."""
    st.header("📊 Metricas & Desempenho")

    client_id = str(user_data["id"])
    tools_config = user_data.get("tools_config", {}) or {}

    # --- Period Selector ---
    col_period, col_refresh = st.columns([3, 1])
    with col_period:
        period = st.selectbox(
            "Periodo",
            options=[7, 14, 30, 60, 90],
            format_func=lambda x: f"Ultimos {x} dias",
            index=2,
        )
    with col_refresh:
        st.write("")
        st.write("")
        if st.button("🔄 Atualizar"):
            st.rerun()

    # =============================================
    # 1. CARDS KPIs (Summary)
    # =============================================
    summary = get_metrics_summary(client_id)
    handler_data = get_conversations_by_handler(client_id, days=period)
    response_stats = get_response_time_stats(client_id, days=period)
    followup_data = get_followup_stats(client_id, days=period)
    resolution_data = get_resolution_stats(client_id, days=period)

    st.subheader("Visao Geral")

    # Row 1: Main KPIs
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Total de Conversas",
            handler_data.get("total_conversations", 0),
        )
    with c2:
        st.metric(
            "Atendidos por IA",
            handler_data.get("ai_served", 0),
        )
    with c3:
        st.metric(
            "Humano Entrou",
            handler_data.get("human_involved", 0),
        )
    with c4:
        st.metric(
            "Aguardando Humano",
            handler_data.get("waiting_human", 0),
        )

    # Row 2: Resolution + Response Time
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric(
            "Resolvido por IA",
            resolution_data.get("resolved_by_ai", 0),
        )
    with c6:
        st.metric(
            "Resolvido por Humano",
            resolution_data.get("resolved_by_human", 0),
        )
    with c7:
        avg_ms = response_stats.get("avg_ms", 0)
        if avg_ms > 0:
            display_time = f"{avg_ms / 1000:.1f}s" if avg_ms < 60000 else f"{avg_ms / 60000:.1f}min"
        else:
            display_time = "N/A"
        st.metric("Tempo Medio Resposta", display_time)
    with c8:
        st.metric(
            "Somente IA (sem humano)",
            handler_data.get("ai_only", 0),
        )

    st.divider()

    # =============================================
    # 2. TABS for detailed metrics
    # =============================================
    tab_tools, tab_followup, tab_response, tab_resolution, tab_chart = st.tabs(
        [
            "🔧 Tools Usadas",
            "📩 Follow-ups",
            "⏱️ Tempo de Resposta",
            "✅ Resolucao",
            "📈 Evolucao Diaria",
        ]
    )

    # --- TAB: Tools Usadas ---
    with tab_tools:
        st.subheader("Ferramentas Usadas por Clientes")
        st.caption("Quais ferramentas a IA acionou durante os atendimentos.")

        tools_data = get_tools_usage_breakdown(client_id, days=period)

        if tools_data:
            df_tools = pd.DataFrame(tools_data)
            df_tools.columns = ["Ferramenta", "Total Chamadas", "Conversas Unicas"]

            # Chart
            st.bar_chart(df_tools.set_index("Ferramenta")["Total Chamadas"])

            # Table
            st.dataframe(df_tools, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum uso de ferramenta registrado no periodo.")

    # --- TAB: Follow-ups ---
    with tab_followup:
        st.subheader("Follow-ups")
        st.caption("Quantidade de follow-ups enviados e quantos foram respondidos.")

        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            st.metric("Follow-ups Enviados", followup_data.get("sent", 0))
        with fc2:
            st.metric("Respondidos (Convertidos)", followup_data.get("converted", 0))
        with fc3:
            rate = followup_data.get("conversion_rate", 0)
            st.metric("Taxa de Resposta", f"{rate}%")

        if followup_data.get("sent", 0) > 0:
            st.progress(min(rate / 100, 1.0))

            fc4, fc5 = st.columns(2)
            with fc4:
                st.metric("Chats Unicos (Enviados)", followup_data.get("unique_chats_sent", 0))
            with fc5:
                st.metric("Chats Unicos (Convertidos)", followup_data.get("unique_chats_converted", 0))

    # --- TAB: Tempo de Resposta ---
    with tab_response:
        st.subheader("Tempo de Resposta (Webhook → Envio)")
        st.caption("Tempo medido desde a entrada do webhook ate o envio da resposta da IA.")

        if response_stats.get("sample_count", 0) > 0:
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1:
                avg = response_stats.get("avg_ms", 0)
                st.metric("Media", f"{avg / 1000:.1f}s")
            with rc2:
                med = response_stats.get("median_ms", 0)
                st.metric("Mediana (P50)", f"{med / 1000:.1f}s")
            with rc3:
                mn = response_stats.get("min_ms", 0)
                st.metric("Minimo", f"{mn / 1000:.1f}s")
            with rc4:
                mx = response_stats.get("max_ms", 0)
                st.metric("Maximo", f"{mx / 1000:.1f}s")

            st.caption(f"Baseado em {response_stats.get('sample_count', 0)} amostras.")
        else:
            st.info("Nenhum dado de tempo de resposta no periodo.")

    # --- TAB: Resolucao ---
    with tab_resolution:
        st.subheader("Resolucao de Atendimentos")

        # Summary
        rc1, rc2 = st.columns(2)
        with rc1:
            st.metric("Resolvido por IA", resolution_data.get("resolved_by_ai", 0))
        with rc2:
            st.metric("Resolvido por Humano", resolution_data.get("resolved_by_human", 0))

        total_resolved = (resolution_data.get("resolved_by_ai", 0)
                          + resolution_data.get("resolved_by_human", 0))
        if total_resolved > 0:
            ai_pct = resolution_data.get("resolved_by_ai", 0) / total_resolved * 100
            st.caption(f"Taxa IA: {ai_pct:.0f}% | Taxa Humano: {100 - ai_pct:.0f}%")
            st.progress(ai_pct / 100)

        st.divider()

        # --- RESOLUTION RULES CONFIG ---
        st.subheader("Regras de Resolucao")
        st.caption(
            "Configure quais acoes indicam que um atendimento foi resolvido. "
            "Isso permite gerar metricas precisas de 'Resolvido por IA' e 'Resolvido por Humano'."
        )

        resolution_cfg = tools_config.get("resolution_rules", {})

        # --- AI Resolution Rules ---
        st.markdown("**Resolvido por IA**")
        st.caption(
            "Se a IA acionar uma dessas ferramentas, o atendimento sera marcado como resolvido pela IA."
        )

        # Get available tools for this client
        available_tools = []
        for tool_name, tool_data in tools_config.items():
            if isinstance(tool_data, dict) and tool_data.get("active"):
                available_tools.append(tool_name)
            elif tool_data is True:
                available_tools.append(tool_name)

        ai_tools_resolve = resolution_cfg.get("ai_resolve_tools", [])
        new_ai_tools = st.multiselect(
            "Tools que indicam resolucao por IA",
            options=available_tools,
            default=[t for t in ai_tools_resolve if t in available_tools],
            help="Ex: Se a IA acionou 'enviar_relatorio', o atendimento SDR esta resolvido.",
            key="ai_resolve_tools",
        )

        ai_custom_event = resolution_cfg.get("ai_resolve_custom", "")
        new_ai_custom = st.text_area(
            "Eventos customizados (1 por linha)",
            value=ai_custom_event,
            height=80,
            help="Descreva cenarios adicionais. Ex: 'Se a IA enviou o relatorio do pedido'",
            key="ai_custom_events",
        )

        # --- Human Resolution Rules ---
        st.markdown("**Resolvido por Humano**")
        st.caption(
            "Se o humano enviar uma mensagem contendo uma dessas palavras/frases, "
            "o atendimento sera marcado como resolvido pelo humano."
        )

        human_keywords = resolution_cfg.get("human_resolve_keywords", "")
        if isinstance(human_keywords, list):
            human_keywords = "\n".join(human_keywords)

        new_human_keywords = st.text_area(
            "Palavras/frases de resolucao humana (1 por linha)",
            value=human_keywords,
            height=80,
            help="Ex: 'resolvido', 'finalizado', 'encerrado'. Se a mensagem do humano contem essas palavras, marca como resolvido.",
            key="human_resolve_keywords",
        )

        # Save button
        if st.button("💾 Salvar Regras de Resolucao", key="save_resolution_rules"):
            # Parse keywords into list
            kw_list = [k.strip() for k in new_human_keywords.strip().split("\n") if k.strip()]

            new_resolution_cfg = {
                "ai_resolve_tools": new_ai_tools,
                "ai_resolve_custom": new_ai_custom.strip(),
                "human_resolve_keywords": kw_list,
            }

            tools_config["resolution_rules"] = new_resolution_cfg
            if update_tools_config_db(user_data["id"], tools_config):
                st.success("Regras salvas com sucesso!")
                user_data["tools_config"] = tools_config
                st.session_state["user_data"] = user_data
            else:
                st.error("Erro ao salvar regras.")

    # --- TAB: Evolucao Diaria ---
    with tab_chart:
        st.subheader("Evolucao Diaria")

        daily_data = get_metrics_daily_series(client_id, days=period)

        if daily_data:
            df = pd.DataFrame(daily_data)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")

            # Conversations chart
            st.markdown("**Conversas por Dia**")
            chart_cols = ["total_conversations"]
            if "human_takeovers" in df.columns:
                chart_cols.append("human_takeovers")
            st.line_chart(df[chart_cols])

            # Resolution chart
            st.markdown("**Resolucao por Dia**")
            res_cols = []
            if "resolved_by_ai" in df.columns:
                res_cols.append("resolved_by_ai")
            if "resolved_by_human" in df.columns:
                res_cols.append("resolved_by_human")
            if res_cols:
                st.bar_chart(df[res_cols])

            # Response time chart
            if "avg_response_time_ms" in df.columns:
                st.markdown("**Tempo Medio de Resposta (ms)**")
                st.line_chart(df[["avg_response_time_ms"]])

            # Follow-up chart
            fup_cols = []
            if "followups_sent" in df.columns:
                fup_cols.append("followups_sent")
            if "followups_converted" in df.columns:
                fup_cols.append("followups_converted")
            if fup_cols:
                st.markdown("**Follow-ups**")
                st.bar_chart(df[fup_cols])

            # Raw data expander
            with st.expander("Ver dados brutos"):
                st.dataframe(df.reset_index(), use_container_width=True)
        else:
            st.info("Nenhum dado diario disponivel no periodo. Os dados sao agregados a cada 5 minutos.")
