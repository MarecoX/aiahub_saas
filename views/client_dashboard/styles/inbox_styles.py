def get_inbox_css():
    """
    Retorna o CSS customizado para transformar o Streamlit em um Inbox estilo WhatsApp Web.
    """
    return """
    <style>
    /* 1. RESET & LAYOUT BASE */
    /* Remove padding excessivo do Streamlit */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max_width: 100%;
    }
    
    /* 2. LISTA DE CONTATOS (COLUNA ESQUERDA) */
    /* Estiliza os botões do Streamlit para parecerem 'Cards' de contato */
    div[data-testid="stVerticalBlock"] > div > button {
        width: 100%;
        border: none !important;
        border-bottom: 1px solid #f0f2f5 !important;
        border-radius: 0px !important;
        background-color: transparent !important;
        text-align: left !important;
        padding: 15px 10px !important;
        color: #111b21 !important;
        transition: background-color 0.2s;
        box-shadow: none !important;
    }
    
    div[data-testid="stVerticalBlock"] > div > button:hover {
        background-color: #f5f6f6 !important;
        border-color: #f0f2f5 !important;
    }

    div[data-testid="stVerticalBlock"] > div > button:focus {
        background-color: #e9edef !important;
        outline: none !important;
    }
    
    /* Pequeno texto (hora) dentro do botão - Hack via CSS gerado dinamicamente no label */
    
    /* 3. ÁREA DE CHAT (COLUNA DIREITA) */
    /* Fundo padrão do WhatsApp */
    .stChatFloatingInputContainer {
        border-top: 1px solid #d1d7db;
        background-color: #f0f2f5;
        z-index: 99 !important;
    }

    /* Container de Rolagem (st.container com height) */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        /* Background do WhatsApp */
        background-color: #efeae2;
        background-image: url("https://user-images.githubusercontent.com/15075759/28719144-86dc0f70-73b1-11e7-911d-60d70fcded21.png");
        background-repeat: repeat;
    }
    
    /* 3.1 CHAT BUBBLES - REMOVIDO (Usa st.chat_message nativo) */

    
    /* Reset scrollbar for better look */
    ::-webkit-scrollbar {
        width: 6px !important;
        height: 6px !important;
    }
    
    </style>
    """
