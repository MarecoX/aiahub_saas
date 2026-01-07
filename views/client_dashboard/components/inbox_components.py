import streamlit as st
import datetime


def format_contact_label(chat_id, last_message_at, last_role, last_context=""):
    """
    Cria um label rico para o botão do contato.
    Como o Streamlit não permite HTML complexo dentro de botões nativos,
    usamos formatação de texto inteligente e emojis.
    """
    # 1. Formata Hora
    time_str = ""
    if last_message_at:
        try:
            # Se for hoje, mostra hora. Se não, mostra data
            now = datetime.datetime.now()
            diff = now - last_message_at
            if diff.days == 0:
                time_str = last_message_at.strftime("%H:%M")
            else:
                time_str = last_message_at.strftime("%d/%m")
        except Exception:
            pass

    # 2. Ícone de Status
    status_icon = "🟢"  # Respondido
    if last_role == "user":
        status_icon = "🔴"  # Pendente (Cliente falou por último)

    # 3. Preview da Mensagem (Truncado)
    # Tenta pegar do last_context (que é longo) ou usa placeholder
    preview = "Nova mensagem..."
    if last_context:
        # Pega as ultimas 30 chars
        preview = (
            (last_context[:35] + "...") if len(last_context) > 35 else last_context
        )

    # Monta o Label (Visual Hack)
    # [🔴 14:30] +5511999...
    # Preview...

    # Streamlit Buttons não suportam newlines reais visualmente bem em todos os temas,
    # mas podemos tentar um hack ou manter simples.
    # Vamos adicionar o preview se houver espaço.
    return f"{status_icon} {chat_id} | {time_str}\n{preview}"


def render_message_bubble(role: str, content: str, created_at=None, avatar_url=None):
    """
    Gera o HTML puro para uma bolha de chat com suporte a Avatar.
    """
    # Formata hora
    time_str = created_at.strftime("%H:%M") if created_at else ""

    # Avatar Element
    avatar_html = ""
    if avatar_url:
        avatar_html = f'<div class="chat-avatar" style="background-image: url(\'{avatar_url}\');"></div>'

    if role == "user":
        # USER (CLIENTE): [Avatar] [Bubble] (Esquerda)
        html = f"""
        <div class="chat-row row-user">
            {avatar_html}
            <div class="chat-bubble bubble-user">
                {content}
                <span class="bubble-time">{time_str}</span>
            </div>
        </div>
        """
    else:
        # ASSISTANT (MINHA EMPRESA): [Bubble] [Avatar] (Direita)
        html = f"""
        <div class="chat-row row-assistant">
            <div class="chat-bubble bubble-assistant">
                {content}
                <span class="bubble-time">{time_str}</span>
            </div>
            {avatar_html}
        </div>
        """
    return html


def render_chat_header(active_chat_id):
    """
    Renderiza o cabeçalho da área de chat.
    """
    col_avatar, col_info = st.columns([1, 8])
    with col_avatar:
        # Placeholder de Avatar (Pode ser substituido pela foto do perfil do WhatsApp se tivermos)
        st.markdown("👤", unsafe_allow_html=True)
    with col_info:
        st.markdown(f"**{active_chat_id}**")
        st.caption("Online via WhatsApp Oficial")
    st.divider()
