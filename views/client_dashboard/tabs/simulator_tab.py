import streamlit as st
import asyncio
import os
import sys

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


def render_simulator_tab(user_data):
    st.header("Simulador de Chat")
    st.caption("Teste as respostas do seu bot usando a base de conhecimento acima.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt_text := st.chat_input("Pergunte algo ao seu bot..."):
        # User Msg
        st.session_state.messages.append({"role": "user", "content": prompt_text})
        with st.chat_message("user"):
            st.markdown(prompt_text)

        # Generate Answer
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                # Importa Ask SaaS
                try:
                    from scripts.shared.chains_saas import ask_saas

                    # Mock Config
                    mock_config = {"gemini_store_id": user_data.get("store_id")}

                    # Loop assincrono pra rodar ask_saas
                    response = asyncio.run(
                        ask_saas(
                            query=prompt_text,
                            chat_id=f"SIM_{user_data['id']}",
                            system_prompt=user_data["system_prompt"],
                            client_config=mock_config,
                        )
                    )

                    st.markdown(response)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": response}
                    )

                except Exception as e:
                    st.error(f"Erro no Simulador: {e}")
