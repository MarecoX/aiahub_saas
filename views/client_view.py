import streamlit as st
import os
import sys
import asyncio

# Adiciona diretório raiz ao path para imports funcionarem
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts import gemini_manager
from scripts.saas_db import get_connection

def render_client_view(user_data):
    # user_data = {'id', 'name', 'store_id', 'system_prompt', ...}
    
    st.title(f"🤖 Kestra AI | {user_data['name']}")
    
    col_info, col_logout = st.columns([4, 1])
    with col_info:
        st.caption(f"Knowledge Base ID: {user_data.get('store_id', 'Não configurado')}")
    with col_logout:
        if st.button("Sair"):
            st.session_state.clear()
            st.rerun()

    # --- TABS ---
    tab_files, tab_prompt, tab_sim, tab_tools, tab_whatsapp, tab_followup = st.tabs(["📂 Meus Arquivos (RAG)", "🧠 Personalidade (Prompt)", "💬 Testar Assistente", "🔗 Integrações e Ferramentas", "📱 Conexão WhatsApp", "⏰ Follow-up Autônomo"])

    # --- TAB 1: ARQUIVOS (RAG) ---
    with tab_files:
        st.header("Gerenciar Conhecimento")
        c_store_id = user_data.get('store_id')
        
        # Validar Store
        is_real_store = c_store_id and "fileSearchStores/" in c_store_id
        
        if not is_real_store:
            st.warning("⚠️ Seu espaço de arquivos ainda não foi inicializado. Entre em contato com o suporte.")
        else:
            # UPLOAD
            uploaded_files = st.file_uploader("Enviar PDFs, CSV, TXT", accept_multiple_files=True)
            if st.button("📤 Enviar para IA"):
                if uploaded_files:
                    bar = st.progress(0)
                    for i, file in enumerate(uploaded_files):
                        # Save temp
                        tpath = f"temp_{file.name}"
                        with open(tpath, "wb") as f: f.write(file.getbuffer())
                        
                        st.write(f"Enviando {file.name}...")
                        # Upload usando Manager
                        op, err = gemini_manager.upload_file_to_store(tpath, c_store_id, custom_display_name=file.name)
                        
                        if op: st.success(f"✅ {file.name} ok!")
                        else: st.error(f"Erro {file.name}: {err}")
                        
                        if os.path.exists(tpath): os.remove(tpath)
                        bar.progress((i+1)/len(uploaded_files))
            
            st.divider()
            
            # LISTAGEM
            st.subheader("Arquivos Ativos")
            files = gemini_manager.list_files_in_store(c_store_id)
            found = False
            for f in files:
                found = True
                c1, c2 = st.columns([4, 1])
                with c1:
                    dname = f.display_name if f.display_name else f.name
                    st.text(f"📄 {dname}")
                with c2:
                    if st.button("🗑️", key=f"del_{f.name}"):
                        gemini_manager.delete_file(f.name)
                        st.rerun()
            
            if not found:
                st.info("Nenhum arquivo na base.")

    # --- TAB 2: PROMPT ---
    with tab_prompt:
        st.header("Personalidade do Robô")
        st.info("Defina como seu assistente deve se comportar.")
        
        # Carrega prompt atual do banco (reload fresco)
        current_prompt = user_data['system_prompt']
        
        typed_prompt = st.text_area("System Prompt", value=current_prompt, height=300, key="sys_prompt_area")
        
        if st.button("💾 Salvar Personalidade"):
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                         cur.execute("UPDATE clients SET system_prompt = %s WHERE id = %s", (typed_prompt, user_data['id']))
                st.success("Prompt atualizado com sucesso!")
                # Atualiza session state visualmente
                user_data['system_prompt'] = typed_prompt
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

    # --- TAB 3: SIMULADOR ---
    with tab_sim:
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
                        from scripts.chains_saas import ask_saas
                        
                        # Mock Config
                        mock_config = {"gemini_store_id": user_data['store_id']}
                        
                        # Loop assincrono pra rodar ask_saas
                        response = asyncio.run(ask_saas(
                            query=prompt_text,
                            chat_id=f"SIM_{user_data['id']}",
                            system_prompt=user_data['system_prompt'],
                            client_config=mock_config
                        ))
                        
                        st.markdown(response)
                        st.session_state.messages.append({"role": "assistant", "content": response})
                        
                    except Exception as e:
                        st.error(f"Erro no Simulador: {e}")

    # --- TAB 4: INTEGRAÇÕES ---
    with tab_tools:
        st.header("Ferramentas e Integrações")
        st.info("Conecte seu assistente a sistemas externos.")
        
        # Load Config
        t_config = user_data.get('tools_config', {})
        if not t_config: t_config = {}
        
        # --- Kommo CRM ---
        st.subheader("Kommo CRM")
        kommo_cfg = t_config.get('qualificado_kommo_provedor', {})
        if isinstance(kommo_cfg, bool): kommo_cfg = {"active": kommo_cfg}
        
        c_kommo_active = st.toggle("Ativar Integração Kommo CRM", value=kommo_cfg.get('active', False))
        
        if c_kommo_active:
            k1, k2 = st.columns(2)
            k_url = k1.text_input("URL Base (ex: https://dominio.kommo.com)", value=kommo_cfg.get('url', ''))
            k_token = k2.text_input("Token de Autorização (Bearer ...)", value=kommo_cfg.get('token', ''), type="password")
            
            k3, k4 = st.columns(2)
            k_pipeline = k3.text_input("Pipeline ID (Opcional)", value=str(kommo_cfg.get('pipeline_id', '')))
            k_status = k4.text_input("Status ID (Lead Qualificado)", value=str(kommo_cfg.get('status_id', '')))
            
            st.caption("Ao preencher o Status ID, o assistente moverá o card automaticamente quando qualificado.")

        st.divider()
        if st.button("💾 Salvar Integrações"):
            new_tools_config = t_config.copy()
            new_tools_config['qualificado_kommo_provedor'] = {
                "active": c_kommo_active,
                "url": k_url if c_kommo_active else "",
                "token": k_token if c_kommo_active else "",
                "pipeline_id": k_pipeline if c_kommo_active else "",
                "status_id": k_status if c_kommo_active else ""
            }
            try:
                import json
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE clients SET tools_config = %s WHERE id = %s", (json.dumps(new_tools_config), user_data['id']))
                user_data['tools_config'] = new_tools_config
                st.success("Configurações salvas!")
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

    # --- TAB 5: CONEXÃO WHATSAPP ---
    with tab_whatsapp:
        st.header("Conexão WhatsApp")
        st.caption("Gerencie a conexão da sua instância com o WhatsApp.")
        
        from scripts.uazapi_saas import get_instance_status, connect_instance, disconnect_instance
        
        w_config = user_data.get('tools_config', {}).get('whatsapp', {})
        api_url = w_config.get('url', os.getenv("UAZAPI_URL"))
        api_key = w_config.get('key', os.getenv("UAZAPI_KEY"))
        
        if not api_url or not api_key:
            st.error("⚠️ URL ou Chave da API WhatsApp não configuradas. Verifique as variáveis de ambiente.")
        else:
            if st.button("🔄 Atualizar Status"):
                st.rerun()

            status_data = {}
            try:
                status_data = asyncio.run(get_instance_status(api_key=api_key, base_url=api_url))
            except Exception as e:
                st.error(f"Erro ao checar status: {e}")

            state = status_data.get("instance", {}).get("state", "unknown")
            st.metric("Status da Instância", state.upper(), delta="🟢 Online" if state=="open" else "🔴 Offline")

            if state != "open":
                st.divider()
                st.subheader("Nova Conexão")
                phone_num = st.text_input("Número (com DDD e DDI, ex: 5511999999999)", help="Deixe vazio para gerar QR Code, ou preencha para gerar Código de Pareamento.")
                
                if st.button("🔗 Conectar"):
                    with st.spinner("Solicitando conexão..."):
                        try:
                            resp = asyncio.run(connect_instance(phone=phone_num if phone_num else None, api_key=api_key, base_url=api_url))
                            if "base64" in resp:
                                st.image(resp["base64"], caption="Escaneie o QR Code", width=300)
                            elif "code" in resp:
                                st.success(f"Código de Pareamento: {resp['code']}")
                                st.title(resp['code'])
                                st.info("Digite este código no seu WhatsApp > Aparelhos Conectados > Conectar com número.")
                            else:
                                st.json(resp)
                        except Exception as e:
                            st.error(f"Erro ao conectar: {e}")
            
            if state == "open" or state == "connecting":
                st.divider()
                if st.button("🚪 Desconectar", type="primary"):
                    try:
                        asyncio.run(disconnect_instance(api_key=api_key, base_url=api_url))
                        st.success("Comando de logout enviado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao desconectar: {e}")

    # --- TAB 6: FOLLOW-UP ---
    with tab_followup:
        st.header("⏰ Follow-up Automático")
        st.info("Configure mensagens automáticas para enviar quando o cliente para de responder.")
        
        f_config = user_data.get('followup_config', {})
        if not f_config: f_config = {}
        
        state_key = f"followup_stages_{user_data['id']}"
        if state_key not in st.session_state:
            import copy
            st.session_state[state_key] = copy.deepcopy(f_config.get('stages', []))
            st.session_state[f"active_{user_data['id']}"] = f_config.get('active', False)
            
        active = st.toggle("Ativar Follow-up Automático", key=f"active_{user_data['id']}")
        current_stages = st.session_state[state_key]
        
        st.subheader(f"Etapas de Retomada ({len(current_stages)})")
        
        indices_to_remove = []
        for i, stage in enumerate(current_stages):
            with st.expander(f"Etapa {i+1}", expanded=True):
                c1, c2 = st.columns([2, 1])
                stage['delay_minutes'] = c1.number_input(f"Esperar (minutos)", min_value=1, value=int(stage.get('delay_minutes', 60)), key=f"d_{user_data['id']}_{i}")
                stage['prompt'] = st.text_area(f"Instrução para IA", value=stage.get('prompt', "Pergunte se precisa de ajuda."), key=f"p_{user_data['id']}_{i}")
                if st.button("🗑️ Remover Etapa", key=f"rem_{user_data['id']}_{i}"):
                    indices_to_remove.append(i)

        if indices_to_remove:
            for index in sorted(indices_to_remove, reverse=True):
                del st.session_state[state_key][index]
            st.rerun()

        if st.button("➕ Adicionar Nova Etapa"):
            st.session_state[state_key].append({"delay_minutes": 60, "prompt": "Olá, ainda está por aqui?"})
            st.rerun()

        st.divider()
        if st.button("💾 Salvar Configuração de Follow-up", type="primary"):
            final_config = {"active": active, "stages": st.session_state[state_key]}
            try:
                import json
                with get_connection() as conn:
                    with conn.cursor() as cur:
                         cur.execute("UPDATE clients SET followup_config = %s WHERE id = %s", (json.dumps(final_config), user_data['id']))
                user_data['followup_config'] = final_config
                st.success("✅ Configuração salva com sucesso!")
                st.balloons()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")
