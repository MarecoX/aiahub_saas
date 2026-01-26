import streamlit as st
import asyncio
import os

from scripts.shared.saas_db import get_provider_config, upsert_provider_config


def render_connection_tab(user_data):
    st.header("Conexão WhatsApp (QR Code)")
    st.caption(
        "Conecte via QR Code (Z-API/Evolution) se preferir não usar a API Oficial."
    )

    # Lazy import to avoid circular dependency
    try:
        from scripts.uazapi.uazapi_saas import (
            get_instance_status,
            connect_instance,
            disconnect_instance,
        )
    except ImportError:
        import sys

        # Calculate root_dir for fallback import
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        sys.path.append(root_dir)

        from scripts.uazapi.uazapi_saas import (
            get_instance_status,
            connect_instance,
            disconnect_instance,
        )

    # Buscar de client_providers (novo) com fallback para colunas (legado)
    uazapi_cfg = get_provider_config(str(user_data["id"]), "uazapi") or {}
    if not uazapi_cfg:
        w_config = user_data.get("tools_config", {}).get("whatsapp", {})
        uazapi_cfg = {
            "url": user_data.get("api_url")
            or w_config.get("url")
            or os.getenv("UAZAPI_URL")
            or "",
            "token": user_data.get("token")
            or w_config.get("key")
            or os.getenv("UAZAPI_KEY")
            or "",
        }

    api_url = uazapi_cfg.get("url") or os.getenv("UAZAPI_URL")
    api_key = uazapi_cfg.get("token") or os.getenv("UAZAPI_KEY")

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
                    # Salvar em client_providers (novo)
                    upsert_provider_config(
                        client_id=str(user_data["id"]),
                        provider_type="uazapi",
                        config={"url": new_url, "token": new_key},
                        is_active=True,
                        is_default=(
                            user_data.get("whatsapp_provider")
                            in ["uazapi", "none", "", None]
                        ),
                    )

                    st.success("Configuração salva! Recarregando...")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")
    else:
        if st.button("🔄 Atualizar Status"):
            st.rerun()

        status_data = {}
        try:
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
        state = instance_data.get("state") or instance_data.get("status") or "unknown"

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
                    asyncio.run(disconnect_instance(api_key=api_key, base_url=api_url))
                    st.success("Comando de logout enviado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao desconectar: {e}")
