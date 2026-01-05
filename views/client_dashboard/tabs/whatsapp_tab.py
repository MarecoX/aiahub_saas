import streamlit as st
import asyncio
import os
import sys

# Ensure root dir is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.shared.saas_db import (  # noqa: E402
    get_connection,
    get_inbox_conversations,
    get_messages,
    add_message,
)


def render_whatsapp_tab(user_data):
    st.header("WhatsApp Oficial (Meta API)")
    st.caption("Conecte sua conta WABA para estabilidade total.")

    t_config = user_data.get("tools_config", {})
    if not t_config:
        t_config = {}

    # Prioritize new 'whatsapp' key, fallback to legacy 'whatsapp_official'
    meta_cfg = t_config.get("whatsapp", {}) or t_config.get("whatsapp_official", {})

    # --- SUB-TABS ---
    mt_config, mt_templates, mt_profile, mt_inbox = st.tabs(
        ["⚙️ Configuração", "📝 Templates", "🏢 Perfil", "📥 Inbox"]
    )

    with mt_config:
        active_meta = st.toggle(
            "Ativar Integração Oficial", value=meta_cfg.get("active", False)
        )

        mc1, mc2 = st.columns(2)
        waba_id = mc1.text_input(
            "WABA ID (Conta Business)", value=meta_cfg.get("waba_id", "")
        )
        phone_id = mc2.text_input(
            "Phone ID (Identificação do Número)", value=meta_cfg.get("phone_id", "")
        )

        token = st.text_input(
            "Token Permanente (ATENÇÃO: Não cole o 'Code' aqui. Use System User Token)",
            value=meta_cfg.get("access_token") or meta_cfg.get("token", ""),
            type="password",
        )

        st.info("ℹ️ Para obter esses dados, acesse o Gerenciador de Negócios da Meta.")
        st.markdown("#### 🔗 Webhook para Meta App")
        st.info(
            "Configure esta URL no painel do seu App na Meta (Caso você seja o dono do App)."
        )

        # Force correct API domain ignoring DB config
        webhook_base = "https://api.aiahub.com.br"
        verify_token = "aiahub_meta_secret_2026"
        webhook_url = f"{webhook_base}/api/v1/meta/webhook/{verify_token}"

        # --- EMBEDDED SIGNUP FLOW ---
        st.info("💡 Use o botão abaixo para conectar seu WhatsApp Oficial.")

        # URL do Popup - Agora Dinâmica (ZDG Style)
        # Passa os parâmetros para o HTML ler e inicializar o SDK
        base_url = "https://api.aiahub.com.br/api/v1/meta/signup-static"
        signup_url = f"{base_url}?app_id=825239677170334&config_id=1240691471290119&version=v24.0&token={user_data['token']}"

        # Botão que abre o popup
        st.markdown(
            f"""
            <a href="{signup_url}" target="_blank">
                <button style="
                    background-color: #1877F2; 
                    color: white; 
                    border: none; 
                    padding: 10px 20px; 
                    border-radius: 5px; 
                    font-weight: bold; 
                    cursor: pointer;
                    display: flex;
                    align_items: center;
                    gap: 10px;">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="white" xmlns="http://www.w3.org/2000/svg">
                        <path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047v-2.66c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.29h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/>
                    </svg>
                    Entrar com Facebook
                </button>
            </a>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")

        # --- PHONE REGISTRATION & STATUS (Z-PRO STYLE) ---
        if token and phone_id:
            st.subheader("📡 Status da Conexão e Registro")
            col_status, col_actions = st.columns([1, 1])

            # Get Status Logic
            if col_status.button("🔄 Atualizar Status", use_container_width=True):
                # DEBUG: Direct request to see error details
                import requests

                url = f"https://graph.facebook.com/v23.0/{phone_id}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                try:
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        info = r.json()
                        status_val = info.get("code_verification_status", "UNKNOWN")
                        quality = info.get("quality_rating", "UNKNOWN")
                        display_phone = info.get("display_phone_number", "N/A")

                        st.session_state["waba_status"] = status_val
                        st.session_state["waba_quality"] = quality
                        st.session_state["waba_phone"] = display_phone
                        st.rerun()
                    else:
                        st.error(f"❌ Erro Meta ({r.status_code}): {r.text}")
                except Exception as e:
                    st.error(f"❌ Erro de Conexão: {e}")

            # Display Status
            curr_status = st.session_state.get("waba_status", "---")
            curr_quality = st.session_state.get("waba_quality", "---")
            curr_phone = st.session_state.get("waba_phone", "---")

            col_status.metric("Número", curr_phone)
            col_status.metric("Status Meta", curr_status)
            col_status.metric("Qualidade", curr_quality)

            # Registration Actions
            with col_actions:
                st.write("**Ações de Registro**")
                if curr_status != "VERIFIED":
                    reg_pin = st.text_input(
                        "PIN de 6 Dígitos (Sua Senha)", type="password", max_chars=6
                    )

                    if st.button("📩 Solicitar Código (SMS)"):
                        from scripts.meta.meta_client import MetaClient

                        mc = MetaClient(token, phone_id)
                        ok = asyncio.run(mc.request_verification_code())
                        if ok:
                            st.success("📩 SMS Enviado! Verifique seu celular.")
                        else:
                            st.error("❌ Falha ao enviar SMS. Tente novamente.")

                    ver_code = st.text_input("Código Recebido no SMS")
                    if st.button("✅ Validar Código"):
                        if not reg_pin or len(reg_pin) != 6:
                            st.warning("⚠️ Digite um PIN de 6 dígitos antes de validar.")
                        elif not ver_code:
                            st.warning("⚠️ Digite o código recebido no SMS.")
                        else:
                            from scripts.meta.meta_client import MetaClient

                            mc = MetaClient(token, phone_id)
                            ok = asyncio.run(mc.verify_and_register(ver_code, reg_pin))
                            if ok:
                                st.balloons()
                                st.success("✅ Telefone REGISTRADO com Sucesso!")
                                st.session_state["waba_status"] = "VERIFIED"
                                st.rerun()
                            else:
                                st.error("❌ Código inválido ou erro no registro.")
                else:
                    st.success("✅ Telefone Verificado e Pronto!")

                    # 2FA PIN Setting for Verified Accounts
                    with st.expander("🔐 Configurações de Segurança e Registro"):
                        st.info(
                            "Painel de controle para definição de senha e registro final na API."
                        )

                        col_pin, col_reg = st.columns(2)

                        # Coluna 1: PIN
                        with col_pin:
                            st.write("**Definir PIN (2FA)**")
                            new_pin = st.text_input(
                                "Novo PIN (6 Dígitos)",
                                type="password",
                                max_chars=6,
                                key="new_pin_2fa",
                            )
                            if st.button("Definir PIN via API"):
                                if len(new_pin) != 6:
                                    st.error("O PIN deve ter exatamente 6 dígitos.")
                                else:
                                    from scripts.meta.meta_client import MetaClient

                                    mc = MetaClient(token, phone_id)
                                    ok = asyncio.run(
                                        mc.set_two_step_verification(new_pin)
                                    )
                                    if ok:
                                        st.success(
                                            "✅ PIN de Segurança definido com sucesso!"
                                        )
                                    else:
                                        st.error(
                                            "❌ Falha ao definir PIN. A conta pode estar restringida ou não registrada."
                                        )

                        # Coluna 2: Registro Manual (Fix "Account does not exist")
                        with col_reg:
                            st.write("**Finalizar Registro (API)**")
                            st.caption(
                                "Use se o erro 'Account does not exist' persistir."
                            )
                            reg_pin_api = st.text_input(
                                "PIN para Registro",
                                type="password",
                                max_chars=6,
                                key="reg_pin_api",
                            )
                            if st.button("🚀 Registrar Conta na API"):
                                if len(reg_pin_api) != 6:
                                    st.error("Digite o PIN (6 dígitos) para registrar.")
                                else:
                                    from scripts.meta.meta_client import MetaClient

                                    mc = MetaClient(token, phone_id)
                                    ok = asyncio.run(mc.register_phone(reg_pin_api))
                                    if ok:
                                        st.success(
                                            "✅ Conta REGISTRADA na API com sucesso!"
                                        )
                                    else:
                                        st.error(
                                            "❌ Falha no registro. Verifique logs."
                                        )

                    st.warning(
                        """
                        ⚠️ **Atenção Importante:** 
                        Para enviar mensagens de Marketing e evitar bloqueios, você **precisa** cadastrar um Método de Pagamento na sua conta do WhatsApp (WABA) dentro do Gerenciador de Negócios da Meta.
                        
                        👉 **[Clique aqui para acessar o Gerenciador de Pagamentos](https://business.facebook.com/billing_hub/)**
                        
                        Sem isso, a Meta pode limitar o envio de mensagens.
                        """
                    )

        st.markdown("---")

        # --- MANUAL OVERRIDE (Legacy/Debug) ---
        with st.expander("⚙️ Configuração Manual (Avançado)"):
            c_url, c_copy = st.columns([4, 1])
            c_url.text_input(
                "URL de Callback",
                value=webhook_url,
                disabled=True,
                label_visibility="collapsed",
            )
            c_url.caption("Verify Token: aiahub_meta_secret_2026")

            col_save, col_verify = st.columns(2)

            if col_save.button("💾 Salvar e Subscrever", type="primary"):
                if not waba_id or not token:
                    st.error("Preencha WABA ID e Token.")
                else:
                    # 1. Salva no Banco
                    new_tools = t_config.copy()
                    existing_wa = t_config.get("whatsapp", {})
                    new_wa = existing_wa.copy()
                    new_wa.update(
                        {
                            "active": active_meta,
                            "waba_id": waba_id,
                            "phone_id": phone_id,
                            "access_token": token,  # Save as access_token for consistency
                            "mode": "official",
                        }
                    )
                    new_tools["whatsapp"] = new_wa

                    try:
                        import json

                        with get_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE clients SET tools_config = %s WHERE id = %s",
                                    (json.dumps(new_tools), user_data["id"]),
                                )
                        user_data["tools_config"] = new_tools

                        # 2. Executa Subscrição na Meta (Subscribe App to WABA)
                        st.subheader("Processando Integração...")
                        try:
                            from scripts.meta.meta_client import MetaClient

                            mc = MetaClient(token, phone_id)

                            with st.status(
                                "Conectando com Meta Cloud API...", expanded=True
                            ) as status:
                                st.write("🔄 Autenticando...")
                                # Valida Phone ID
                                info = asyncio.run(mc.get_phone_number_info())
                                if info:
                                    st.write(
                                        f"✅ Número Identificado: {info.get('display_phone_number')} ({info.get('quality_rating')})"
                                    )
                                else:
                                    st.error("❌ Token ou ID inválidos.")
                                    status.update(state="error")
                                    st.stop()

                                st.write("🔄 Inscrevendo App na WABA (Webhooks)...")
                                ok = asyncio.run(mc.subscribe_app_to_waba(waba_id))
                                if ok:
                                    st.write("✅ Webhooks Ativados com Sucesso!")
                                    status.update(
                                        label="Integração Concluída!", state="complete"
                                    )
                                    st.success("Configuração Salva e Conectada!")
                                    st.rerun()
                                else:
                                    st.error(
                                        "❌ Falha na subscrição (Verifique permissões do Token)."
                                    )
                                    status.update(state="error")
                        except Exception as e:
                            st.error(f"Erro na conexão: {e}")

                    except Exception as e:
                        st.error(f"Erro ao salvar banco: {e}")

        if col_verify.button("🔄 Verificar Status"):
            if not token:
                st.warning("Sem token configurado.")
            else:
                try:
                    from scripts.meta.meta_client import MetaClient

                    mc = MetaClient(token, phone_id)
                    info = asyncio.run(mc.get_phone_number_info())
                    if info:
                        st.success(f"ONLINE: {info.get('display_phone_number')}")
                        st.json(info)
                    else:
                        st.error("OFFLINE ou Token Inválido")
                except Exception as e:
                    st.error(str(e))

    with mt_templates:
        st.subheader("Gerenciar Templates")

        # --- SESSION STATE PARA O BODY (Para os botões de formatação funcionarem) ---
        if "t_body_content" not in st.session_state:
            st.session_state["t_body_content"] = ""

        # --- FORMULÁRIO DE CRIAÇÃO ---
        with st.expander("➕ Criar Novo Template", expanded=True):
            st.caption(
                "Crie templates seguindo o padrão da Meta. O nome será formatado automaticamente."
            )

            col_form, col_prev = st.columns([1.5, 1])

            with col_form:
                # Row 1: Name & Lang
                c_name, c_lang = st.columns(2)
                t_name = c_name.text_input(
                    "Nome do Template *", placeholder="ex: promo_verao_2025"
                )
                t_lang = c_lang.selectbox("Idioma *", ["pt_BR", "en_US", "es_ES"])

                # Row 2: Category
                st.markdown("##### Categoria do Template *")
                t_cat = st.radio(
                    "Categoria",
                    ["MARKETING", "UTILITY", "AUTHENTICATION"],
                    index=0,
                    captions=[
                        "Enviar promoções, ofertas e novidades.",
                        "Enviar atualizações de pedidos ou conta.",
                        "Enviar códigos de verificação (OTP).",
                    ],
                    horizontal=True,
                    label_visibility="collapsed",
                )

                st.divider()

                # Row 3: Header
                st.markdown("##### Cabeçalho (Opcional)")
                header_type = st.radio(
                    "Tipo de Cabeçalho",
                    ["Nenhum", "Texto", "Mídia (Imagem/Vídeo/Doc)"],
                    horizontal=True,
                    label_visibility="collapsed",
                )

                t_header_text = ""
                t_header_media = None

                if header_type == "Texto":
                    t_header_text = st.text_input(
                        "Texto do Cabeçalho", placeholder="Ex: 🎉 Oferta Relâmpago!"
                    )
                elif "Mídia" in header_type:
                    t_header_media = st.selectbox(
                        "Tipo de Mídia", ["IMAGE", "VIDEO", "DOCUMENT"]
                    )
                    st.info("ℹ️ A mídia real é enviada no momento do disparo via API.")

                # Row 4: Body
                st.markdown("##### Corpo da Mensagem *")

                # Toolbar (Fake)
                bt_col1, bt_col2, bt_col3, bt_col4 = st.columns([1, 1, 1, 4])
                if bt_col1.button("**B**", help="Negrito"):
                    st.session_state["t_body_content"] += "*texto*"
                if bt_col2.button("_I_", help="Itálico"):
                    st.session_state["t_body_content"] += "_texto_"
                if bt_col3.button("~S~", help="Tachado"):
                    st.session_state["t_body_content"] += "~texto~"
                if bt_col4.button("{ } Adicionar Variável"):
                    # Detectar próxima var? Simplificado:
                    st.session_state["t_body_content"] += "{{1}}"

                t_body = st.text_area(
                    "Texto da mensagem",
                    value=st.session_state["t_body_content"],
                    placeholder="Olá {{1}}, aproveite nossos descontos...",
                    height=200,
                    key="input_t_body",
                    label_visibility="collapsed",
                )
                # Sync back manual changes
                st.session_state["t_body_content"] = t_body

                # Row 5: Footer
                st.markdown("##### Rodapé (Opcional)")
                t_footer = st.text_input(
                    "Texto do Rodapé",
                    placeholder="Ex: Enviado por Tio Marcos Barbearia",
                )

                # Row 6: Buttons
                st.markdown("##### Botões")

                # Marketing Opt-out (Unsubscribe / Block)
                include_unsub = False
                include_block = False

                if t_cat == "MARKETING":
                    c_opt1, c_opt2 = st.columns(2)
                    include_unsub = c_opt1.checkbox(
                        "Incluir botão Unsubscribe", value=True
                    )
                    include_block = c_opt2.checkbox("Incluir botão Block", value=False)

                btn_options = [
                    "Nenhum",
                    "Quick Reply (Resposta Rápida)",
                    "Call to Action (Link/Telefone)",
                ]
                btn_type = st.selectbox("Adicionar Botão Interativo", btn_options)

                buttons_config = []

                if btn_type == "Quick Reply (Resposta Rápida)":
                    c_qr1, c_qr2 = st.columns(2)
                    qr1 = c_qr1.text_input("Botão 1 (Texto)", key="qr1")
                    qr2 = c_qr2.text_input("Botão 2 (Texto)", key="qr2")
                    if qr1:
                        buttons_config.append({"type": "QUICK_REPLY", "text": qr1})
                    if qr2:
                        buttons_config.append({"type": "QUICK_REPLY", "text": qr2})

                elif btn_type == "Call to Action (Link/Telefone)":
                    cta_type = st.selectbox(
                        "Tipo de Ação", ["Visit Website", "Call Phone Number"]
                    )
                    cta_text = st.text_input("Texto do Botão", key="cta_txt")
                    cta_val = st.text_input("URL ou Telefone (+55...)", key="cta_val")
                    if cta_type and cta_text and cta_val:
                        b_type_api = "URL" if "Website" in cta_type else "PHONE_NUMBER"
                        buttons_config.append(
                            {
                                "type": b_type_api,
                                "text": cta_text,
                                "url"
                                if b_type_api == "URL"
                                else "phone_number": cta_val,
                            }
                        )

                # Se Marketing, adiciona os botões especiais no final (Simulação via Quick Reply)
                if include_unsub:
                    buttons_config.append(
                        {"type": "QUICK_REPLY", "text": "Unsubscribe"}
                    )
                if include_block:
                    buttons_config.append(
                        {"type": "QUICK_REPLY", "text": "Stop / Block"}
                    )

                st.markdown("---")
                submit = st.button(
                    "📤 Criar e Enviar para Aprovação",
                    type="primary",
                    use_container_width=True,
                )

            with col_prev:
                st.markdown("##### 📱 Preview em Tempo Real")

                # Logic for Preview Rendition
                prev_header_html = ""
                if header_type == "Texto" and t_header_text:
                    prev_header_html = f'<div style="font-weight: bold; margin-bottom: 8px; color: #000; font-size: 15px;">{t_header_text}</div>'
                elif "Mídia" in header_type and t_header_media:
                    icon = (
                        "📷"
                        if t_header_media == "IMAGE"
                        else ("🎥" if t_header_media == "VIDEO" else "📄")
                    )
                    prev_header_html = f'<div style="background: #e0e0e0; height: 120px; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 10px; color: #555; font-size: 24px;">{icon} {t_header_media}</div>'
                else:
                    prev_header_html = ""  # Garante vazio se "Nenhum"

                prev_body_html = (t_body or "Digite o texto da mensagem...").replace(
                    "\n", "<br>"
                )
                # Simple markdown parse for preview
                prev_body_html = (
                    prev_body_html.replace("*", "<b>")
                    .replace("_", "<i>")
                    .replace("~", "<strike>")
                )

                prev_footer_html = (
                    f'<div style="font-size: 11px; color: #888; margin-top: 8px; padding-top: 5px; border-top: 1px solid rgba(0,0,0,0.05);">{t_footer}</div>'
                    if t_footer
                    else ""
                )

                # Buttons HTML
                btns_html = ""
                # Interactive
                for b in buttons_config:
                    icon = (
                        "↩️"
                        if b["type"] == "QUICK_REPLY"
                        else ("📞" if b["type"] == "PHONE_NUMBER" else "🔗")
                    )
                    btns_html += f'<div style="margin-top: 5px; background: white; color: #00a5f4; text-align: center; padding: 10px; border-radius: 5px; cursor: pointer; box-shadow: 0 1px 0.5px rgba(0,0,0,0.1); font-weight: 500;">{icon} {b["text"]}</div>'

                # Flatten HTML to avoid markdown indentation issues
                preview_card = (
                    f"<div style=\"background-color: #F0F2F5; border-radius: 20px; padding: 20px; font-family: Helvetica, Arial, sans-serif; border: 1px solid #ddd; min-height: 400px; background-image: url('https://user-images.githubusercontent.com/15075759/28719144-86dc0f70-73b1-11e7-911d-60d70fcded21.png');\">"
                    f'<div style="background-color: #FFFFFF; border-radius: 0px 10px 10px 10px; padding: 12px; box-shadow: 0 1px 1px rgba(0,0,0,0.1); max-width: 95%; font-size: 14px; line-height: 1.4; position: relative;">'
                    f"{prev_header_html}"
                    f'<div style="color: #111;">{prev_body_html}</div>'
                    f"{prev_footer_html}"
                    f'<div style="position: absolute; bottom: 5px; right: 10px; font-size: 10px; color: #999;">12:00 PM</div>'
                    f"</div>"
                    f"{btns_html}"
                    f"</div>"
                )
                st.markdown(preview_card, unsafe_allow_html=True)

            if submit:
                if not t_name or not t_body:
                    st.error("Campos obrigatórios: Nome e Corpo.")
                else:
                    # Construct Components
                    final_components = []

                    # Header
                    if header_type == "Texto" and t_header_text:
                        final_components.append(
                            {
                                "type": "HEADER",
                                "format": "TEXT",
                                "text": t_header_text,
                            }
                        )
                    elif "Mídia" in header_type and t_header_media:
                        final_components.append(
                            {"type": "HEADER", "format": t_header_media}
                        )

                    # Body
                    final_components.append({"type": "BODY", "text": t_body})

                    # Footer
                    if t_footer:
                        final_components.append({"type": "FOOTER", "text": t_footer})

                    # Buttons
                    if buttons_config:
                        final_components.append(
                            {"type": "BUTTONS", "buttons": buttons_config}
                        )

                    # Send
                    with st.spinner("Enviando para Meta..."):
                        try:
                            from scripts.meta.meta_client import MetaClient

                            mc = MetaClient(
                                meta_cfg.get("access_token") or meta_cfg.get("token"),
                                meta_cfg["phone_id"],
                            )
                            resp = asyncio.run(
                                mc.create_template_waba(
                                    waba_id=meta_cfg["waba_id"],
                                    name=t_name.lower().strip().replace(" ", "_"),
                                    category=t_cat,
                                    language=t_lang,
                                    components=final_components,
                                )
                            )
                            if "id" in resp:
                                st.success(
                                    f"✅ Template Environment Criado! ID: {resp['id']}"
                                )
                                st.info("Status: PENDING - Aguarde aprovação.")
                            elif "error" in resp:
                                st.error(f"Erro Meta: {resp['error']}")
                        except Exception as e:
                            st.error(f"Falha: {e}")

        st.markdown("---")
        st.subheader("Biblioteca de Templates")
        if st.button("🔄 Atualizar Lista"):
            with st.spinner("Buscando..."):
                try:
                    from scripts.meta.meta_client import MetaClient

                    mc = MetaClient(
                        meta_cfg.get("access_token") or meta_cfg.get("token"),
                        meta_cfg["phone_id"],
                    )

                    lst = asyncio.run(mc.get_templates(meta_cfg["waba_id"]))
                    st.session_state[f"meta_templates_{user_data['id']}"] = lst
                except Exception as e:
                    st.error(str(e))

        # Interactive List with Send Option
        t_list = st.session_state.get(f"meta_templates_{user_data['id']}", [])
        if t_list:
            for t in t_list:
                # Use expander to clean UI but allow actions
                status_icon = "✅" if t["status"] == "APPROVED" else "⏳"
                with st.expander(f"{status_icon} {t['name']} ({t['language']})"):
                    st.caption(f"ID: {t['id']} | Categoria: {t['category']}")

                    st.markdown("#### Testar Disparo")
                    t_dest = st.text_input(
                        "Número de Destino (55...)", key=f"dest_{t['id']}"
                    )

                    if st.button(f"🚀 Enviar {t['name']}", key=f"btn_send_{t['id']}"):
                        if not t_dest:
                            st.error("Digite o número.")
                        else:
                            with st.spinner("Enviando..."):
                                try:
                                    from scripts.meta.meta_client import MetaClient

                                    mc = MetaClient(
                                        meta_cfg.get("access_token")
                                        or meta_cfg.get("token"),
                                        meta_cfg["phone_id"],
                                    )
                                    # Sending without components (variables) for now as quick test
                                    # If needed, we can parse body to allow inputting vars
                                    resp = asyncio.run(
                                        mc.send_message_template(
                                            to=t_dest,
                                            template_name=t["name"],
                                            language_code=t["language"],
                                        )
                                    )

                                    if resp:
                                        st.success("Enviado com sucesso!")
                                    else:
                                        st.error("Falha ao enviar.")
                                except Exception as e:
                                    st.error(f"Erro: {e}")

    with mt_profile:
        st.subheader("Perfil da Empresa (WhatsApp Business)")
        if not meta_cfg.get("active") or not (
            meta_cfg.get("token") or meta_cfg.get("access_token")
        ):
            st.warning("Ative a integração e configure o Token primeiro.")
        else:
            if st.button("🔄 Carregar Perfil Atual"):
                with st.spinner("Buscando dados na Meta..."):
                    try:
                        from scripts.meta.meta_client import MetaClient

                        mc = MetaClient(
                            meta_cfg.get("access_token") or meta_cfg.get("token"),
                            meta_cfg["phone_id"],
                        )
                        profile_data = asyncio.run(mc.get_business_profile())
                        if profile_data:
                            st.session_state["waba_profile"] = profile_data
                            st.success("Dados carregados!")
                        else:
                            st.warning("Não foi possível carregar o perfil.")
                    except Exception as e:
                        st.error(f"Erro ao carregar: {e}")

            # Form
            profile_data = st.session_state.get("waba_profile", {})

            with st.form("form_profile_update"):
                p_desc = st.text_area(
                    "Descrição do Negócio",
                    value=profile_data.get("description", ""),
                )

                c_vert, c_email = st.columns(2)

                verticals = [
                    "UNDEFINED",
                    "OTHER",
                    "AUTO_DEALERSHIP",
                    "BEAUTY_SALON_AND_BARBER",
                    "CLOTHING",
                    "EDUCATION",
                    "ENTERTAINMENT",
                    "EVENT_PLANNING_AND_SERVICE",
                    "FINANCE",
                    "FOOD_AND_GROCERY",
                    "HOTEL_AND_LODGING",
                    "MEDICAL_AND_HEALTH",
                    "NON_PROFIT_ORGANIZATION",
                    "PROFESSIONAL_SERVICES",
                    "REAL_ESTATE",
                    "RESTAURANT",
                    "SHOPPING_AND_RETAIL",
                    "TRAVEL_AND_TRANSPORTATION",
                ]
                current_vert = profile_data.get("vertical", "UNDEFINED")
                if current_vert not in verticals:
                    verticals.insert(0, current_vert)

                p_vert = c_vert.selectbox(
                    "Categoria (Vertical)",
                    verticals,
                    index=verticals.index(current_vert)
                    if current_vert in verticals
                    else 0,
                )
                p_email = c_email.text_input(
                    "Email de Contato", value=profile_data.get("email", "")
                )

                p_addr = st.text_input(
                    "Endereço", value=profile_data.get("address", "")
                )

                c_web1, c_web2 = st.columns(2)
                websites = profile_data.get("websites", [])
                w1 = websites[0] if len(websites) > 0 else ""
                w2 = websites[1] if len(websites) > 1 else ""

                p_web1 = c_web1.text_input("Website 1", value=w1)
                p_web2 = c_web2.text_input("Website 2", value=w2)

                p_about = st.text_input(
                    "Sobre (Status)", value=profile_data.get("about", "")
                )

                if st.form_submit_button("💾 Salvar Perfil"):
                    new_data = {
                        "description": p_desc,
                        "vertical": p_vert,
                        "email": p_email,
                        "address": p_addr,
                        "websites": [w for w in [p_web1, p_web2] if w],
                        "about": p_about,
                    }

                    with st.spinner("Atualizando na Meta..."):
                        try:
                            from scripts.meta.meta_client import MetaClient

                            mc = MetaClient(
                                meta_cfg.get("access_token") or meta_cfg.get("token"),
                                meta_cfg["phone_id"],
                            )
                            ok = asyncio.run(mc.update_business_profile(new_data))
                            if ok:
                                st.success("Perfil atualizado com sucesso!")
                                st.session_state["waba_profile"].update(new_data)
                            else:
                                st.error("Falha ao atualizar perfil.")
                        except Exception as e:
                            st.error(f"Erro: {e}")

    with mt_inbox:
        st.header("📬 Inbox WhatsApp")
        st.caption("Visualize e responda conversas em tempo real.")

        # Prioritize new 'whatsapp' key
        meta_cfg_inbox = user_data.get("tools_config", {}).get(
            "whatsapp", {}
        ) or user_data.get("tools_config", {}).get("whatsapp_official", {})
        if not meta_cfg_inbox.get("active"):
            st.warning(
                "⚠️ Ative o WhatsApp Oficial na aba 'Configuração' para usar o Inbox."
            )
        else:
            c_list, c_chat = st.columns([1, 2.5])

            # --- COLUNA 1: LISTA DE CONTATOS ---
            with c_list:
                st.subheader("Conversas")
                if st.button("🔄 Atualizar", key="refresh_inbox"):
                    st.rerun()

                conversations = get_inbox_conversations(user_data["id"])

                if not conversations:
                    st.info("Nenhuma conversa recente.")

                for conv in conversations:
                    chat_id = conv["chat_id"]
                    # Tenta formatar bonito (Data ou Status)
                    label = f"📱 {chat_id}"
                    if conv.get("last_role") == "user":
                        label += " 🔴"  # Cliente falou por ultimo
                    else:
                        label += " 🟢"

                    if st.button(
                        label, key=f"chat_btn_{chat_id}", use_container_width=True
                    ):
                        st.session_state["active_chat_id"] = chat_id
                        st.rerun()

            # --- COLUNA 2: ÁREA DE CHAT ---
            with c_chat:
                active_id = st.session_state.get("active_chat_id")

                if not active_id:
                    st.info("👈 Selecione uma conversa na esquerda.")
                else:
                    st.markdown(f"**Conversando com:** `{active_id}`")
                    st.divider()

                    # Container para rolagem (Streamlit nativo ja rola)
                    chat_container = st.container()

                    with chat_container:
                        history = get_messages(user_data["id"], active_id, limit=50)

                        if not history:
                            st.caption("Nenhum histórico encontrado.")

                        for msg in history:
                            role = msg["role"]
                            content = msg["content"]

                            with st.chat_message(role):
                                st.markdown(content)
                                st.caption(
                                    f"{msg['created_at'].strftime('%H:%M')} - {role}"
                                )

                    # INPUT AREA
                    if prompt := st.chat_input("Digite sua resposta..."):
                        # 1. Enviar via Meta API
                        with st.spinner("Enviando..."):
                            try:
                                from scripts.meta.meta_client import MetaClient

                                mc = MetaClient(
                                    meta_cfg_inbox.get("access_token")
                                    or meta_cfg_inbox.get("token"),
                                    meta_cfg_inbox["phone_id"],
                                )
                                # Envia texto
                                asyncio.run(mc.send_message_text(active_id, prompt))

                                # 2. Salvar no Banco (Assistant)
                                add_message(
                                    client_id=user_data["id"],
                                    chat_id=active_id,
                                    role="assistant",
                                    content=prompt,
                                )
                                st.rerun()  # Atualiza UI
                            except Exception as e:
                                st.error(f"Erro ao enviar: {e}")
