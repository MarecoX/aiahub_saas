import streamlit as st
import os
import sys

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection


def render_followup_tab(user_data):
    st.header("⏰ Follow-up Automático")
    st.info(
        "Configure mensagens automáticas para enviar quando o cliente para de responder."
    )

    f_config = user_data.get("followup_config", {})
    if not f_config:
        f_config = {}

    state_key = f"followup_stages_{user_data['id']}"
    if state_key not in st.session_state:
        import copy

        st.session_state[state_key] = copy.deepcopy(f_config.get("stages", []))
        st.session_state[f"active_{user_data['id']}"] = f_config.get("active", False)

    active = st.toggle("Ativar Follow-up Automático", key=f"active_{user_data['id']}")
    current_stages = st.session_state[state_key]

    st.subheader(f"Etapas de Retomada ({len(current_stages)})")

    indices_to_remove = []
    for i, stage in enumerate(current_stages):
        with st.expander(f"Etapa {i + 1}", expanded=True):
            c1, c2 = st.columns([2, 1])
            stage["delay_minutes"] = c1.number_input(
                "Esperar (minutos)",
                min_value=1,
                value=int(stage.get("delay_minutes", 60)),
                key=f"d_{user_data['id']}_{i}",
            )
            stage["prompt"] = st.text_area(
                "Instrução para IA",
                value=stage.get("prompt", "Pergunte se precisa de ajuda."),
                key=f"p_{user_data['id']}_{i}",
            )
            if st.button("🗑️ Remover Etapa", key=f"rem_{user_data['id']}_{i}"):
                indices_to_remove.append(i)

    if indices_to_remove:
        for index in sorted(indices_to_remove, reverse=True):
            del st.session_state[state_key][index]
        st.rerun()

    if st.button("➕ Adicionar Nova Etapa"):
        st.session_state[state_key].append(
            {"delay_minutes": 60, "prompt": "Olá, ainda está por aqui?"}
        )
        st.rerun()

    st.divider()
    if st.button("💾 Salvar Configuração de Follow-up", type="primary"):
        final_config = {"active": active, "stages": st.session_state[state_key]}
        try:
            import json

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET followup_config = %s WHERE id = %s",
                        (json.dumps(final_config), user_data["id"]),
                    )
            user_data["followup_config"] = final_config
            st.success("✅ Configuração salva com sucesso!")
            st.balloons()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
