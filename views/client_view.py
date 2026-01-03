import streamlit as st
import os
import sys
import asyncio
import uuid

# Adiciona diretório raiz ao path para imports funcionarem
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from api.services.gemini_service import GeminiService  # noqa: E402


from scripts.shared.saas_db import (
    get_connection,
    get_inbox_conversations,
    get_messages,
    add_message,
)  # noqa: E402
from scripts.meta.meta_client import MetaClient


def render_client_view(user_data):
    # Inicializa GeminiService com tratamento de erro
    try:
        from api.services.gemini_service import GeminiService

        gemini_manager = GeminiService()
    except Exception as e:
        st.error(f"Erro ao inicializar IA: {e}")
        gemini_manager = None
    # user_data = {'id', 'name', 'store_id', 'system_prompt', ...}

    st.title(f"🤖 AIAHUB CONECT | {user_data['name']}")

    col_info, col_logout = st.columns([4, 1])
    with col_info:
        st.caption(f"Knowledge Base ID: {user_data.get('store_id', 'Não configurado')}")
    with col_logout:
        if st.button("Sair"):
            st.session_state.clear()
            st.rerun()

    # --- TABS ---
    (
        tab_files,
        tab_prompt,
        tab_sim,
        tab_tools,
        tab_whatsapp,
        tab_meta_official,
        tab_followup,
        tab_inbox,
    ) = st.tabs(
        [
            "📂 Meus Arquivos (RAG)",
            "🧠 Personalidade (Prompt)",
            "💬 Testar Assistente",
            "🔗 Integrações e Ferramentas",
            "📱 Conexão WhatsApp",
            "🟢 WhatsApp Oficial",
            "⏰ Follow-up Autônomo",
            "📬 Inbox",
        ]
    )

    # --- TAB 1: ARQUIVOS (RAG) ---
    with tab_files:
        st.header("Gerenciar Conhecimento")
        c_store_id = user_data.get("store_id")

        # Validar se é store real (Enterprise) ou dummy
        is_dummy = (
            c_store_id
            and "store_" in c_store_id
            and "fileSearchStores" not in c_store_id
        )

        if not c_store_id or is_dummy:
            st.warning(
                "⚠️ Seu espaço de arquivos ainda não foi inicializado corretamente no Gemini."
            )
            if st.button("🚀 Inicializar Espaço agora"):
                with st.spinner("Criando Vector Store no Google..."):
                    vs, err = gemini_manager.get_or_create_vector_store(
                        user_data["name"]
                    )
                    if vs:
                        try:
                            with get_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute(
                                        "UPDATE clients SET gemini_store_id = %s WHERE id = %s",
                                        (vs.name, user_data["id"]),
                                    )
                            user_data["store_id"] = vs.name
                            st.success(f"Espaço criado! ID: {vs.name}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao salvar BD: {e}")
                    else:
                        st.error(f"Erro ao criar no Gemini: {err}")

        # Só mostra upload se tiver algo (após validação acima)
        if c_store_id:
            # UPLOAD
            uploaded_files = st.file_uploader(
                "Enviar PDFs, CSV, TXT", accept_multiple_files=True
            )
            if st.button("📤 Enviar para IA"):
                if uploaded_files:
                    bar = st.progress(0)
                    for i, file in enumerate(uploaded_files):
                        # Save temp with SAFE ASCII NAME using UUID
                        ext = os.path.splitext(file.name)[1]
                        tpath = f"temp_{uuid.uuid4().hex}{ext}"

                        with open(tpath, "wb") as f:
                            f.write(file.getbuffer())

                        st.write(f"Enviando {file.name}...")
                        # Upload usando Manager
                        op, err = gemini_manager.upload_file_to_store(
                            tpath, c_store_id, custom_display_name=file.name
                        )

                        if op:
                            st.success(f"✅ {file.name} ok!")
                        else:
                            st.error(f"Erro {file.name}: {err}")

                        if os.path.exists(tpath):
                            os.remove(tpath)
                        bar.progress((i + 1) / len(uploaded_files))

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
                        from scripts.shared.chains_saas import ask_saas

                        # Mock Config
                        mock_config = {"gemini_store_id": user_data["store_id"]}

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

    # --- TAB 4: INTEGRAÇÕES ---
    with tab_tools:
        st.header("Ferramentas e Integrações")
        st.info("Conecte seu assistente a sistemas externos.")

        # Load Config
        t_config = user_data.get("tools_config", {})
        if not t_config:
            t_config = {}

        # --- Kommo CRM ---
        st.subheader("Kommo CRM")
        kommo_cfg = t_config.get("qualificado_kommo_provedor", {})
        if isinstance(kommo_cfg, bool):
            kommo_cfg = {"active": kommo_cfg}

        c_kommo_active = st.toggle(
            "Ativar Integração Kommo CRM", value=kommo_cfg.get("active", False)
        )

        if c_kommo_active:
            k1, k2 = st.columns(2)
            k_url = k1.text_input(
                "URL Base (ex: https://dominio.kommo.com)",
                value=kommo_cfg.get("url", ""),
            )
            k_token = k2.text_input(
                "Token de Autorização (Bearer ...)",
                value=kommo_cfg.get("token", ""),
                type="password",
            )

            k3, k4 = st.columns(2)
            k_pipeline = k3.text_input(
                "Pipeline ID (Opcional)", value=str(kommo_cfg.get("pipeline_id", ""))
            )
            k_status = k4.text_input(
                "Status ID (Lead Qualificado)",
                value=str(kommo_cfg.get("status_id", "")),
            )

            st.caption(
                "Ao preencher o Status ID, o assistente moverá o card automaticamente quando qualificado."
            )

        st.divider()

        # --- LancePilot ---
        st.subheader("LancePilot (WhatsApp Oficial)")
        # Now reads from columns instead of JSON
        c_lp_active = st.toggle(
            "Ativar Integração LancePilot",
            value=user_data.get("lancepilot_active", False),
        )

        lp_token = user_data.get("lancepilot_token", "") or ""
        lp_workspace_id = user_data.get("lancepilot_workspace_id", "") or ""
        lp_number = user_data.get("lancepilot_number", "") or ""

        if c_lp_active:
            lp_token = st.text_input(
                "Token LancePilot (API v3)", value=lp_token, type="password"
            )

            lp_number = st.text_input(
                "Número Conectado (Ex: 5561999999999)",
                value=lp_number,
                help="Este número será usado para identificar a origem das mensagens se o Webhook não tiver token.",
            )

            # Privacy: Search Term Required
            lp_search = st.text_input(
                "Nome do Workspace (Filtro Obrigatório)",
                help="Digite o nome exato para buscar seu workspace.",
            )

            # Fetch Workspaces Button
            if lp_token:
                if st.button("🔄 Carregar Workspaces"):
                    if not lp_search:
                        st.warning("⚠️ Digite o nome do Workspace para buscar.")
                    else:
                        try:
                            # Lazy import to avoid circular dependency
                            try:
                                from scripts.lancepilot.client import LancePilotClient
                            except ImportError:
                                import sys

                                sys.path.append(
                                    os.path.abspath(
                                        os.path.join(os.path.dirname(__file__), "..")
                                    )
                                )
                                from scripts.lancepilot.client import LancePilotClient

                            client = LancePilotClient(token=lp_token)
                            # Pass search term!
                            data = client.get_workspaces(search_query=lp_search)
                            st.session_state[f"lp_workspaces_{user_data['id']}"] = data
                            if data:
                                st.success(f"Encontrado: {len(data)} workspace(s).")
                            else:
                                st.warning("Nenhum workspace encontrado com este nome.")
                        except Exception as e:
                            st.error(f"Erro ao buscar workspaces: {e}")

            # Dropdown for Workspace
            saved_ws_list = st.session_state.get(f"lp_workspaces_{user_data['id']}", [])

            if saved_ws_list:
                ws_options = {
                    w["id"]: f"{w['attributes']['name']} ({w['id']})"
                    for w in saved_ws_list
                }

                # Default index
                def_idx = 0
                keys = list(ws_options.keys())
                if lp_workspace_id in keys:
                    def_idx = keys.index(lp_workspace_id)

                selected_ws = st.selectbox(
                    "Selecione o Workspace",
                    options=keys,
                    format_func=lambda x: ws_options[x],
                    index=def_idx,
                )
                lp_workspace_id = selected_ws
            else:
                lp_workspace_id = st.text_input(
                    "ID do Workspace",
                    value=lp_workspace_id,
                    help="Use a busca acima para preencher.",
                )

            if c_lp_active:
                st.markdown("#### 🔗 Webhook de Integração")
                st.info(
                    "Copie a URL abaixo e configure no LancePilot (Settings > Webhook):"
                )

                # Tenta adivinhar a URL base (ou usa placeholder)
                base_kestra = user_data.get("api_url") or "https://SEU-KESTRA-URL.com"
                if "/api" in base_kestra:
                    base_kestra = base_kestra.split("/api")[0]

                # URL do Webhook do Flow 'lancepilot_native'
                webhook_url = f"{base_kestra}/api/v1/executions/webhook/company.team/lancepilot_native/lp_webhook"

                st.code(webhook_url, language="text")
                st.caption(
                    f"Token do Cliente: {user_data.get('token')} | Identificação via Número: {lp_number}"
                )

        st.divider()

        # --- Betel ERP ---
        st.subheader("Betel ERP (Consulta de Produtos)")
        betel_cfg = t_config.get("consultar_produtos_betel", {})
        if isinstance(betel_cfg, bool):
            betel_cfg = {"active": betel_cfg}

        c_betel_active = st.toggle(
            "Ativar Integração Betel ERP", value=betel_cfg.get("active", False)
        )

        b_loja = betel_cfg.get("loja_id", "")
        b_access = betel_cfg.get("access_token", "")
        b_secret = betel_cfg.get("secret_token", "")

        if c_betel_active:
            b_loja = st.text_input("ID da Loja", value=b_loja)
            b1, b2 = st.columns(2)
            b_access = b1.text_input("Access Token", value=b_access, type="password")
            b_secret = b2.text_input("Secret Token", value=b_secret, type="password")

        st.divider()

        # --- Enviar Relatório ---
        st.subheader("📤 Enviar Relatório para Grupo")
        relatorio_cfg = t_config.get("enviar_relatorio", {})
        if isinstance(relatorio_cfg, bool):
            relatorio_cfg = {"active": relatorio_cfg}

        c_relatorio_active = st.toggle(
            "Habilitar Envio de Relatórios", value=relatorio_cfg.get("active", False)
        )

        r_grupo = relatorio_cfg.get("grupo_id", "")
        r_instructions = relatorio_cfg.get("instructions", "")
        r_template = relatorio_cfg.get("template", "")

        if c_relatorio_active:
            r_grupo = st.text_input(
                "ID do Grupo WhatsApp",
                value=r_grupo,
                help="Ex: 5511999999999-1234567890@g.us (obtenha via Uazapi)",
            )
            r_instructions = st.text_area(
                "Quando enviar relatório?",
                value=r_instructions,
                height=100,
                placeholder="Ex: Envie relatório quando o cliente confirmar pedido, reservar produto, ou fechar negócio...",
            )
            r_template = st.text_area(
                "Template da Mensagem (Opcional)",
                value=r_template,
                height=80,
                placeholder="Ex: *Novo Pedido* \\n Cliente: {{nome}} \\n Produto: {{produto}}",
                help="Use {{campo}} para inserir dados. Se vazio, usa formato padrão.",
            )

        st.divider()

        # --- Atendimento Humano ---
        st.subheader("🧑‍💼 Atendimento Humano")
        handoff_cfg = t_config.get("atendimento_humano", {})
        if isinstance(handoff_cfg, bool):
            handoff_cfg = {"active": handoff_cfg}

        c_handoff_active = st.toggle(
            "Habilitar Atendimento Humano", value=handoff_cfg.get("active", False)
        )

        h_timeout = handoff_cfg.get("timeout_minutes", 60)
        h_instructions = handoff_cfg.get("instructions", "")

        if c_handoff_active:
            h_timeout = st.number_input(
                "Duração do Modo Humano (minutos)",
                min_value=5,
                max_value=1440,
                value=int(h_timeout),
                help="Tempo que a IA ficará pausada após transferir para humano.",
            )
            h_instructions = st.text_area(
                "Quando ativar o Atendimento Humano?",
                value=h_instructions,
                height=120,
                placeholder="Ex: Transfira para humano quando o cliente pedir entrega, solicitar desconto, ou perguntar sobre garantia...",
                help="Essas instruções serão adicionadas ao prompt da IA.",
            )

        st.divider()
        if st.button("💾 Salvar Integrações"):
            new_tools_config = t_config.copy()
            # Save Kommo
            new_tools_config["qualificado_kommo_provedor"] = {
                "active": c_kommo_active,
                "url": k_url if c_kommo_active else "",
                "token": k_token if c_kommo_active else "",
                "pipeline_id": k_pipeline if c_kommo_active else "",
                "status_id": k_status if c_kommo_active else "",
            }
            # LancePilot is now saved to columns (not in tools_config)
            # Save Betel
            new_tools_config["consultar_produtos_betel"] = {
                "active": c_betel_active,
                "loja_id": b_loja if c_betel_active else "",
                "access_token": b_access if c_betel_active else "",
                "secret_token": b_secret if c_betel_active else "",
            }
            # Save Enviar Relatório
            new_tools_config["enviar_relatorio"] = {
                "active": c_relatorio_active,
                "grupo_id": r_grupo if c_relatorio_active else "",
                "instructions": r_instructions if c_relatorio_active else "",
                "template": r_template if c_relatorio_active else "",
            }
            # Save Atendimento Humano
            new_tools_config["atendimento_humano"] = {
                "active": c_handoff_active,
                "timeout_minutes": h_timeout if c_handoff_active else 60,
                "instructions": h_instructions if c_handoff_active else "",
            }

            try:
                import json

                with get_connection() as conn:
                    with conn.cursor() as cur:
                        # Save tools_config JSON (without channels)
                        cur.execute(
                            "UPDATE clients SET tools_config = %s WHERE id = %s",
                            (json.dumps(new_tools_config), user_data["id"]),
                        )
                        # Save channel columns separately
                        cur.execute(
                            """
                            UPDATE clients SET
                                lancepilot_active = %s,
                                lancepilot_token = %s,
                                lancepilot_workspace_id = %s,
                                lancepilot_number = %s
                            WHERE id = %s
                            """,
                            (
                                c_lp_active,
                                lp_token if c_lp_active else "",
                                lp_workspace_id if c_lp_active else "",
                                lp_number if c_lp_active else "",
                                user_data["id"],
                            ),
                        )
                user_data["tools_config"] = new_tools_config
                user_data["lancepilot_active"] = c_lp_active
                user_data["lancepilot_token"] = lp_token
                user_data["lancepilot_workspace_id"] = lp_workspace_id
                user_data["lancepilot_number"] = lp_number
                st.success("Configurações salvas!")
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

    # --- TAB 5: CONEXÃO WHATSAPP ---
    with tab_whatsapp:
        st.header("Conexão WhatsApp")
        st.caption("Gerencie a conexão da sua instância com o WhatsApp.")

        from scripts.uazapi.uazapi_saas import (
            get_instance_status,
            connect_instance,
            disconnect_instance,
        )

        w_config = user_data.get("tools_config", {}).get("whatsapp", {})

        # Ordem de prioridade (Client DB > Tools Config > Env Var)
        api_url = (
            user_data.get("api_url") or w_config.get("url") or os.getenv("UAZAPI_URL")
        )
        api_key = (
            user_data.get("token") or w_config.get("key") or os.getenv("UAZAPI_KEY")
        )

        # Se não tiver URL/Key, permite configurar na hora
        if not api_url or not api_key:
            st.warning("⚠️ Configuração do WhatsApp não detectada.")
            st.info("Preencha os dados da sua instância Uazapi/Evolution abaixo:")

            with st.form("config_whatsapp_form"):
                new_url = st.text_input(
                    "URL da API (ex: https://api.z-api.io...)", value=api_url or ""
                )
                new_key = st.text_input(
                    "Global API Key / Token", value=api_key or "", type="password"
                )

                if st.form_submit_button("💾 Salvar Configuração"):
                    try:
                        # Atualiza tools_config no banco
                        current_tools = user_data.get("tools_config", {}) or {}
                        # Garante que é dict
                        if isinstance(current_tools, str):
                            import json

                            current_tools = json.loads(current_tools)

                        current_tools["whatsapp"] = {"url": new_url, "key": new_key}

                        import json

                        with get_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE clients SET tools_config = %s WHERE id = %s",
                                    (json.dumps(current_tools), user_data["id"]),
                                )

                        # Atualiza memória e recarrega
                        user_data["tools_config"] = current_tools
                        st.success("Configuração salva! Recarregando...")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
        else:
            if st.button("🔄 Atualizar Status"):
                st.rerun()

            status_data = {}
            try:
                # Debug Info: Mostra URL mascarada
                # st.write(f"Connecting to: {api_url}")
                status_data = asyncio.run(
                    get_instance_status(api_key=api_key, base_url=api_url)
                )
            except Exception as e:
                st.error(f"Erro ao conectar na API Uazapi: {e}")
                st.caption(f"URL: {api_url}")
                st.info(
                    "Dica: Verifique se o container Uazapi está rodando e se as variáveis de ambiente (UAZAPI_URL) estão corretas."
                )

            if "error" in status_data:
                st.error(f"Erro na API: {status_data['error']}")
                st.caption(f"Tentando conectar em: {api_url}")

            instance_data = status_data.get("instance", {})
            # API pode retornar 'state' ou 'status' dependendo da versão
            state = (
                instance_data.get("state") or instance_data.get("status") or "unknown"
            )

            st.metric(
                "Status da Instância",
                state.upper(),
                delta="🟢 Online" if state == "open" else "🔴 Offline",
            )

            if state != "open":
                st.divider()
                st.subheader("Nova Conexão")
                phone_num = st.text_input(
                    "Número (Opcional - Apenas para Código de Pareamento)",
                    help="Deixe vazio para gerar QR Code.",
                )

                st.caption(
                    "ℹ️ Para ver o **QR Code**, clique no botão abaixo sem preencher o número."
                )

                if st.button("🔗 Gerar QR Code / Conectar"):
                    with st.spinner("Solicitando conexão..."):
                        try:
                            resp = asyncio.run(
                                connect_instance(
                                    phone=phone_num if phone_num else None,
                                    api_key=api_key,
                                    base_url=api_url,
                                )
                            )

                            # DEBUG: Mostra o JSON cru para entendermos o que está voltando
                            st.write("Resposta da API (Debug):")
                            st.json(resp)

                            # Tenta extrair QR Code de vários locais possíveis

                            # Tenta extrair QR Code de vários locais possíveis
                            qr_code_data = (
                                resp.get("base64")
                                or resp.get("qrcode")
                                or resp.get("instance", {}).get("qrcode")
                            )

                            if qr_code_data:
                                # Se vier com prefixo data URI, o st.image renderiza
                                st.image(
                                    qr_code_data,
                                    caption="Escaneie o QR Code",
                                    width=300,
                                )
                            elif "code" in resp:
                                st.success(f"Código de Pareamento: {resp['code']}")
                                st.title(resp["code"])
                                st.info(
                                    "Digite este código no seu WhatsApp > Aparelhos Conectados > Conectar com número."
                                )
                            else:
                                st.json(resp)
                        except Exception as e:
                            st.error(f"Erro ao conectar: {e}")

            if state == "open" or state == "connecting":
                st.divider()
                if st.button("🚪 Desconectar", type="primary"):
                    try:
                        asyncio.run(
                            disconnect_instance(api_key=api_key, base_url=api_url)
                        )
                        st.success("Comando de logout enviado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao desconectar: {e}")

    # --- TAB 6: FOLLOW-UP ---
    with tab_followup:
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
            st.session_state[f"active_{user_data['id']}"] = f_config.get(
                "active", False
            )

        active = st.toggle(
            "Ativar Follow-up Automático", key=f"active_{user_data['id']}"
        )
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

    # --- TAB 7: META OFFICIAL (NOVA) ---
    with tab_meta_official:
        st.header("WhatsApp Oficial (Meta API)")
        st.caption("Conecte sua conta WABA para estabilidade total.")

        meta_cfg = t_config.get("whatsapp_official", {})

        # --- SUB-TABS ---
        mt_config, mt_templates = st.tabs(["⚙️ Configuração", "📝 Templates"])

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
                "Token Permanente (System User)",
                value=meta_cfg.get("token", ""),
                type="password",
            )

            st.info(
                "ℹ️ Para obter esses dados, acesse o Gerenciador de Negócios da Meta."
            )
            st.markdown("#### 🔗 Webhook para Meta App")
            st.info(
                "Configure esta URL no painel do seu App na Meta (Caso você seja o dono do App)."
            )

            # Force correct API domain ignoring DB config
            webhook_base = "https://api.aiahub.com.br"
            verify_token = "aiahub_meta_secret_2026"  # The real secret
            webhook_url = f"{webhook_base}/api/v1/meta/webhook/{verify_token}"

            c_url, c_copy = st.columns([4, 1])
            c_url.text_input(
                "URL de Callback",
                value=webhook_url,
                disabled=True,
                label_visibility="collapsed",
            )
            c_url.caption(f"Verify Token: aiahub_meta_secret_2026")

            col_save, col_verify = st.columns(2)

            if col_save.button("💾 Salvar e Subscrever", type="primary"):
                if not waba_id or not token:
                    st.error("Preencha WABA ID e Token.")
                else:
                    # 1. Salva no Banco
                    new_tools = t_config.copy()
                    new_tools["whatsapp_official"] = {
                        "active": active_meta,
                        "waba_id": waba_id,
                        "phone_id": phone_id,
                        "token": token,
                    }

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

            # --- FORMULÁRIO DE CRIAÇÃO ---
            with st.expander("➕ Criar Novo Template", expanded=True):
                st.caption(
                    "Crie templates para aprovação da Meta. O nome deve ser minúsculo e sem espaços."
                )

                col_form, col_prev = st.columns([1.5, 1])

                with col_form:
                    c_name, c_cat, c_lang = st.columns(3)
                    t_name = c_name.text_input("Nome (ex: promo_verao)")
                    t_cat = c_cat.selectbox(
                        "Categoria", ["MARKETING", "UTILITY", "AUTHENTICATION"]
                    )
                    t_lang = c_lang.selectbox("Idioma", ["pt_BR", "en_US"])

                    st.markdown("**Componentes**")
                    t_header = st.text_input(
                        "Cabeçalho (Opcional)",
                        placeholder="Ex: Oferta Especial!",
                        key="th",
                    )
                    t_body = st.text_area(
                        "Corpo (Obrigatório)",
                        placeholder="Olá {{1}}, confira nossas ofertas!",
                        height=150,
                        key="tb",
                    )
                    t_footer = st.text_input(
                        "Rodapé (Opcional)",
                        placeholder="Ex: Enviado por Kestra",
                        key="tf",
                    )

                    st.markdown("**Botões (Quick Reply)**")
                    c_btn1, c_btn2 = st.columns(2)
                    btn1_text = c_btn1.text_input("Botão 1", key="b1")
                    btn2_text = c_btn2.text_input("Botão 2", key="b2")

                    submit = st.button(
                        "📤 Criar e Enviar para Aprovação",
                        type="primary",
                        use_container_width=True,
                    )

                with col_prev:
                    st.markdown("##### 📱 Preview")
                    # Simulation Styling
                    preview_html = f"""
                    <div style="
                        background-color: #E5DDD5; 
                        border-radius: 15px; 
                        padding: 20px; 
                        font-family: Helvetica, Arial, sans-serif; 
                        border: 1px solid #ccc;
                        min-height: 300px;
                    ">
                        <div style="
                            background-color: #DCF8C6; 
                            border-radius: 7.5px; 
                            padding: 10px; 
                            box-shadow: 0 1px 0.5px rgba(0,0,0,0.13);
                            max-width: 90%;
                        ">
                            {f'<div style="font-weight: bold; margin-bottom: 5px; color: #000;">{t_header}</div>' if t_header else ""}
                            <div style="white-space: pre-wrap; color: #000;">{t_body or "Digitar corpo..."}</div>
                            {f'<div style="font-size: 11px; color: #999; margin-top: 5px;">{t_footer}</div>' if t_footer else ""}
                        </div>
                        {f'<div style="margin-top: 5px; background: white; color: #00a5f4; text-align: center; padding: 10px; border-radius: 7px; cursor: pointer; box-shadow: 0 1px 0.5px rgba(0,0,0,0.13);">{btn1_text}</div>' if btn1_text else ""}
                        {f'<div style="margin-top: 5px; background: white; color: #00a5f4; text-align: center; padding: 10px; border-radius: 7px; cursor: pointer; box-shadow: 0 1px 0.5px rgba(0,0,0,0.13);">{btn2_text}</div>' if btn2_text else ""}
                    </div>
                    """
                    st.markdown(preview_html, unsafe_allow_html=True)

                if submit:
                    if not t_name or not t_body:
                        st.error("Nome e Corpo são obrigatórios.")
                    elif not meta_cfg.get("waba_id"):
                        st.error("WABA ID não encontrado na configuração.")
                    else:
                        # Monta Payload
                        components = []
                        if t_header:
                            components.append(
                                {"type": "HEADER", "format": "TEXT", "text": t_header}
                            )  # Header
                        components.append({"type": "BODY", "text": t_body})  # Body
                        if t_footer:
                            components.append(
                                {"type": "FOOTER", "text": t_footer}
                            )  # Footer

                        buttons_list = []  # Buttons
                        if btn1_text:
                            buttons_list.append(
                                {"type": "QUICK_REPLY", "text": btn1_text}
                            )
                        if btn2_text:
                            buttons_list.append(
                                {"type": "QUICK_REPLY", "text": btn2_text}
                            )
                        if buttons_list:
                            components.append(
                                {"type": "BUTTONS", "buttons": buttons_list}
                            )

                        # Envia
                        with st.spinner("Enviando solicitação para Meta..."):
                            try:
                                from scripts.meta.meta_client import MetaClient

                                mc = MetaClient(meta_cfg["token"], meta_cfg["phone_id"])
                                resp = asyncio.run(
                                    mc.create_template_waba(
                                        waba_id=meta_cfg["waba_id"],
                                        name=t_name.lower().strip(),
                                        category=t_cat,
                                        language=t_lang,
                                        components=components,
                                    )
                                )
                                if "id" in resp:
                                    st.success(
                                        f"✅ Template Criado! ID: {resp['id']} (Status: PENDING)"
                                    )
                                    st.info("Aguarde a aprovação da Meta.")
                                elif "error" in resp:
                                    st.error(f"Erro Meta: {resp['error']}")
                                else:
                                    st.error(f"Erro desconhecido: {resp}")
                            except Exception as e:
                                st.error(f"Falha ao criar: {e}")

            st.markdown("---")
            st.subheader("Templates Aprovados")
            if not meta_cfg.get("active") or not meta_cfg.get("token"):
                st.warning("Ative a integração e configure o Token primeiro.")
            else:
                if st.button("🔄 Sincronizar Templates da Meta"):
                    with st.spinner("Buscando na Graph API..."):
                        try:
                            from scripts.meta.meta_client import MetaClient

                            mc = MetaClient(meta_cfg["token"], meta_cfg["phone_id"])
                            templates = asyncio.run(
                                mc.get_templates(meta_cfg["waba_id"])
                            )
                            st.session_state[f"meta_templates_{user_data['id']}"] = (
                                templates
                            )
                            st.success(f"{len(templates)} templates encontrados!")
                        except Exception as e:
                            st.error(f"Erro ao buscar: {e}")

                templates_list = st.session_state.get(
                    f"meta_templates_{user_data['id']}", []
                )

                if templates_list:
                    for t in templates_list:
                        with st.expander(f"{t['name']} ({t['status']})"):
                            st.json(t)
                            # Test Send Input
                            c_dest, c_btn = st.columns([3, 1])
                            dest_test = c_dest.text_input(
                                "Destino (Ex: 5511999999999)", key=f"dest_{t['name']}"
                            )
                            if c_btn.button("🚀 Enviar", key=f"btn_{t['name']}"):
                                if not dest_test:
                                    st.warning("Digite o número de destino.")
                                else:
                                    with st.spinner("Enviando..."):
                                        try:
                                            from scripts.meta.meta_client import (
                                                MetaClient,
                                            )

                                            mc = MetaClient(
                                                meta_cfg["token"], meta_cfg["phone_id"]
                                            )

                                            # Envia template sem variáveis (teste simples)
                                            # Para templates complexos, precisaria de Inputs dinâmicos,
                                            # mas para o vídeo de aprovação, um template Hello World basta.
                                            resp = asyncio.run(
                                                mc.send_message_template(
                                                    to=dest_test,
                                                    template_name=t["name"],
                                                    language_code=t.get("language")
                                                    or "pt_BR",
                                                )
                                            )

                                            if resp and "messages" in resp:
                                                st.success(
                                                    f"Enviado! ID: {resp['messages'][0]['id']}"
                                                )
                                                st.json(resp)
                                            else:
                                                st.error("Erro no envio.")
                                                st.json(resp)
                                        except Exception as e:
                                            st.error(f"Falha: {e}")
                else:
                    st.info("Nenhum template carregado. Clique em Sincronizar.")

    # --- TAB 8: INBOX (NOVA) ---
    with tab_inbox:
        st.header("📬 Inbox WhatsApp")
        st.caption("Visualize e responda conversas em tempo real.")

        meta_cfg = user_data.get("tools_config", {}).get("whatsapp_official", {})
        if not meta_cfg.get("active"):
            st.warning("⚠️ Ative o WhatsApp Oficial na aba anterior para usar o Inbox.")
        else:
            c_list, c_chat = st.columns([1, 2.5])

            # --- COLUNA 1: LISTA DE CONTATOS ---
            with c_list:
                st.subheader("Conversas")
                if st.button("🔄 Atualizar"):
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

                            # Mapeia role 'user' -> 'user' (Direita), 'assistant' -> 'assistant' (Esquerda)
                            # Mas no st.chat_message, 'user' é icone de pessoa, 'assistant' é robo.
                            # Se role for 'user' (Cliente) -> st.chat_message("user")
                            # Se role for 'assistant' (Nós) -> st.chat_message("assistant")

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
                                mc = MetaClient(meta_cfg["token"], meta_cfg["phone_id"])
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
