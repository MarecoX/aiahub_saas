import json
import streamlit as st
import asyncio
import os
import sys
import base64
from datetime import datetime

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


def render_simulator_tab(user_data):
    st.header("Simulador de Chat")
    st.caption("Teste as respostas do seu bot usando a base de conhecimento acima.")

    # --- SIDEBAR UPLOADS (Simulation) ---
    with st.sidebar:
        st.divider()
        st.subheader("Simular Mídia")
        uploaded_image = st.file_uploader("Enviar Imagem", type=["png", "jpg", "jpeg"])
        uploaded_audio = st.file_uploader(
            "Enviar Áudio", type=["mp3", "wav", "ogg", "m4a"]
        )

    # --- CHAT HISTORY ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            # Se for mensagem de imagem do usuario (simulada)
            if msg.get("image_data"):
                st.image(msg["image_data"], caption="Imagem enviada", width=200)

    # --- INPUT ---
    prompt_text = st.chat_input("Pergunte algo ao seu bot...")

    # Lógica de Envio (Texto OU Mídia)
    should_send = prompt_text or uploaded_image or uploaded_audio

    if should_send:
        # 1. Processa Inputs
        image_b64 = None
        audio_bytes = None
        display_text = prompt_text or ""

        if uploaded_image:
            import io

            # Convert to Base64 for API
            img_bytes = uploaded_image.getvalue()
            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
            display_text += " [Imagem Enviada]"

        if uploaded_audio:
            # Bytes for Whisper
            audio_bytes = uploaded_audio.getvalue()
            display_text += " [Áudio Enviado]"

        # Só processa se não for uma repetição automática vazia do streamlit
        # (Streamlit rerun as vezes reenvia inputs, mas chat_input limpa sozinho. File uploader não)
        # Hack simples: se tem prompt_text ou media, processa.

        # User Msg
        user_msg_obj = {"role": "user", "content": display_text}

        # Save image for display history (not persistent, just session)
        if uploaded_image:
            user_msg_obj["image_data"] = uploaded_image.getvalue()

        st.session_state.messages.append(user_msg_obj)

        with st.chat_message("user"):
            st.markdown(display_text)
            if uploaded_image:
                st.image(uploaded_image, width=200)
            if uploaded_audio:
                st.audio(uploaded_audio)

        # Generate Answer
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                # Importa Ask SaaS
                try:
                    import importlib
                    import scripts.shared.chains_saas
                    import scripts.shared.tools_library

                    importlib.reload(scripts.shared.chains_saas)
                    importlib.reload(scripts.shared.tools_library)

                    from scripts.shared.chains_saas import ask_saas
                    from scripts.shared.tools_library import get_enabled_tools

                    # Mock Config Completo
                    tools_cfg = user_data.get("tools_config", {})
                    mock_config = {
                        "gemini_store_id": user_data.get("store_id"),
                        "id": user_data.get("id"),
                        "api_url": user_data.get("api_url", ""),
                        "token": user_data.get("token", ""),
                        "tools_config": tools_cfg,
                    }

                    # Gera Tools List para o Simulador
                    chat_sim_id = f"SIM_{user_data['id']}"
                    tools_list = get_enabled_tools(
                        tools_cfg, chat_id=chat_sim_id, client_config=mock_config
                    )

                    # Loop assincrono pra rodar ask_saas
                    # Agora suporta args multimodais E Tools
                    # Retorna response, usage e histórico de mensagens (debug)
                    response, usage, debug_msgs = asyncio.run(
                        ask_saas(
                            query=prompt_text
                            if prompt_text
                            else "",  # Backend lida com vazio se tiver audio
                            chat_id=chat_sim_id,
                            system_prompt=f"Data/Hora Atual: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n{user_data['system_prompt']}",
                            client_config=mock_config,
                            tools_list=tools_list,
                            image_base64=image_b64,
                            audio_bytes=audio_bytes,
                        )
                    )

                    # Exibe Logs de Pensamento (Tools)
                    if debug_msgs:
                        with st.expander("🧠 Processo de Pensamento (Debug Tools)"):
                            for m in debug_msgs:
                                # Se for Tool Call (AI Message com tool_calls)
                                if (
                                    m.type == "ai"
                                    and hasattr(m, "tool_calls")
                                    and m.tool_calls
                                ):
                                    for tc in m.tool_calls:
                                        st.markdown(
                                            f"🛠️ **Chamando Tool:** `{tc['name']}`"
                                        )
                                        st.json(tc["args"])

                                # Se for Tool Output (ToolMessage)
                                elif m.type == "tool":
                                    st.markdown(f"✅ **Resultado ({m.name}):**")
                                    # Tenta mostrar JSON bonito se der, senao texto
                                    try:
                                        st.json(json.loads(m.content))
                                    except:
                                        st.text(m.content)

                    # Exibe resposta
                    st.markdown(response)

                    # Debug Usage
                    if usage:
                        with st.expander("Metadados de Consumo"):
                            st.json(usage)

                    st.session_state.messages.append(
                        {"role": "assistant", "content": response}
                    )

                    # Limpa uploaders (hacky in streamlit, requires Key reset or similar, but for sim is fine)
                    # Para produção ideal, usariamos st.session_state keys + callbacks para limpar.
                    # Por enquanto, usuário deve remover o arquivo manualmente se não quiser reenviar.

                except Exception as e:
                    st.error(f"Erro no Simulador: {e}")
