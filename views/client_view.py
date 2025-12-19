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
    tab_files, tab_prompt, tab_sim, tab_followup = st.tabs(["📂 Meus Arquivos (RAG)", "🧠 Personalidade (Prompt)", "💬 Testar Assistente", "⏰ Follow-up Autônomo"])

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
        
        typed_prompt = st.text_area("System Prompt", value=current_prompt, height=300)
        
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
                        # Mock Tools List (Vazio por enquanto, ou carregar do DB se quiser)
                        # No fluxo real o worker carrega as tools. Aqui vamos usar tools vazias 
                        # MAS o create_agent dentro do ask_saas INJETA o Knowledge Base se o store_id existir!
                        
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

    # --- TAB 4: FOLLOW-UP ---
    with tab_followup:
        st.header("⏰ Follow-up Automático")
        st.info("Configure mensagens automáticas para enviar quando o cliente para de responder.")
        
        # Load Config from User Data (Initial Load)
        f_config = user_data.get('followup_config', {})
        if not f_config: f_config = {}
        
        # --- STATE MANAGEMENT ---
        # Initialize session state for editing if not present or if user changed
        # We use a specific key to track which client's config is loaded
        state_key = f"followup_stages_{user_data['id']}"
        
        if state_key not in st.session_state:
            # Deep copy to avoid reference issues
            import copy
            initial_stages = copy.deepcopy(f_config.get('stages', []))
            st.session_state[state_key] = initial_stages
            st.session_state[f"active_{user_data['id']}"] = f_config.get('active', False)
            
        # Bind controls to session state
        active = st.toggle("Ativar Follow-up Automático", key=f"active_{user_data['id']}")
        
        current_stages = st.session_state[state_key]
        
        st.subheader(f"Etapas de Retomada ({len(current_stages)})")
        
        # Display Stages (Iterate over the SESSION STATE list)
        indices_to_remove = []
        
        for i, stage in enumerate(current_stages):
            with st.expander(f"Etapa {i+1}", expanded=True):
                c1, c2 = st.columns([2, 1])
                
                # Update values directly in the list
                stage['delay_minutes'] = c1.number_input(
                    f"Esperar (minutos)", 
                    min_value=1, 
                    value=int(stage.get('delay_minutes', 60)), 
                    key=f"d_{user_data['id']}_{i}"
                )
                
                stage['prompt'] = st.text_area(
                    f"Instrução para IA", 
                    value=stage.get('prompt', "Pergunte se precisa de ajuda."), 
                    key=f"p_{user_data['id']}_{i}",
                    help="Ex: 'Seja educado e pergunte se a dúvida foi sanada.'"
                )
                
                if st.button("🗑️ Remover Etapa", key=f"rem_{user_data['id']}_{i}"):
                    indices_to_remove.append(i)

        # Apply Removals
        if indices_to_remove:
            for index in sorted(indices_to_remove, reverse=True):
                del st.session_state[state_key][index]
            st.rerun()

        if st.button("➕ Adicionar Nova Etapa"):
            st.session_state[state_key].append({"delay_minutes": 60, "prompt": "Olá, ainda está por aqui?"})
            st.rerun()

        # Save Logic
        st.divider()
        if st.button("💾 Salvar Configuração de Follow-up", type="primary"):
            final_config = {
                "active": active,
                "stages": st.session_state[state_key]
            }
            try:
                import json
                with get_connection() as conn:
                    with conn.cursor() as cur:
                         cur.execute("UPDATE clients SET followup_config = %s WHERE id = %s", (json.dumps(final_config), user_data['id']))
                
                # Update local session IS CRITICAL so validade checks pass or other tabs see it
                user_data['followup_config'] = final_config
                
                # Force update of the session state key to match what we just saved (sync)
                st.success("✅ Configuração salva com sucesso!")
                st.balloons()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")
