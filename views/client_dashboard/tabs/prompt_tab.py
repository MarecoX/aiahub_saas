import streamlit as st
import os
import sys

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import get_connection


def render_prompt_tab(user_data):
    st.header("Personalidade do Robô")
    st.info("Defina como seu assistente deve se comportar.")

    # Carrega prompt atual do banco (reload fresco)
    current_prompt = user_data["system_prompt"]

    typed_prompt = st.text_area(
        "System Prompt", value=current_prompt, height=300, key="sys_prompt_area"
    )

    if st.button("💾 Salvar Personalidade"):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET system_prompt = %s WHERE id = %s",
                        (typed_prompt, user_data["id"]),
                    )
            st.success("Prompt atualizado com sucesso!")
            # Atualiza session state visualmente
            user_data["system_prompt"] = typed_prompt
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
