"""
llm_config_tab.py - Configuração do Modelo de IA por Cliente

Permite ao cliente escolher provider (OpenAI / OpenRouter), modelo, temperature,
e opcionalmente fornecer sua própria API key.
"""

import json
import streamlit as st

from scripts.shared.saas_db import get_connection
from scripts.shared.llm_provider import (
    MODEL_CATALOG,
    PROVIDER_OPTIONS,
)

# Defaults
_DEFAULT_PROVIDER = "openai"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_TEMPERATURE = 0.5


def render_llm_config_tab(user_data: dict):
    st.header("Modelo de IA")
    st.caption(
        "Configure qual modelo de linguagem a IA usa para responder seus clientes."
    )

    t_config = user_data.get("tools_config", {}) or {}
    llm_cfg = t_config.get("llm_config", {})
    if not isinstance(llm_cfg, dict):
        llm_cfg = {}

    # --- Status atual ---
    current_provider = llm_cfg.get("provider", _DEFAULT_PROVIDER)
    current_model = llm_cfg.get("model", _DEFAULT_MODEL)
    has_custom_key = bool(llm_cfg.get("api_key"))

    provider_label = PROVIDER_OPTIONS.get(current_provider, current_provider)
    st.info(
        f"Modelo atual: **{current_model}** via **{provider_label}**"
        + (" (chave própria)" if has_custom_key else "")
    )

    st.divider()

    # --- Provider ---
    provider_keys = list(PROVIDER_OPTIONS.keys())
    provider_labels = list(PROVIDER_OPTIONS.values())
    current_provider_idx = (
        provider_keys.index(current_provider)
        if current_provider in provider_keys
        else 0
    )

    selected_provider_label = st.selectbox(
        "Provider",
        options=provider_labels,
        index=current_provider_idx,
        help=(
            "**OpenAI (Direto)**: Conexão direta com a API da OpenAI. "
            "Menor latência, modelos GPT.\n\n"
            "**OpenRouter (Multi-provider)**: Gateway que dá acesso a "
            "GPT, Gemini, Claude, Llama, DeepSeek e outros com uma única API key."
        ),
        key="llm_provider",
    )
    selected_provider = provider_keys[provider_labels.index(selected_provider_label)]

    # --- Modelo ---
    models = MODEL_CATALOG.get(selected_provider, [])
    model_ids = [m["id"] for m in models]
    model_labels = [m["label"] for m in models]

    # Tenta manter o modelo atual selecionado
    if current_model in model_ids:
        current_model_idx = model_ids.index(current_model)
    else:
        # Pega o default do provider
        default_models = [m for m in models if m.get("default")]
        current_model_idx = model_ids.index(default_models[0]["id"]) if default_models else 0

    selected_model_label = st.selectbox(
        "Modelo",
        options=model_labels,
        index=current_model_idx,
        help="Cada modelo tem diferentes capacidades, velocidade e custo.",
        key="llm_model",
    )
    selected_model = model_ids[model_labels.index(selected_model_label)]

    # --- Temperature ---
    selected_temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=1.0,
        value=llm_cfg.get("temperature", _DEFAULT_TEMPERATURE),
        step=0.1,
        help=(
            "Controla a criatividade das respostas. "
            "**0.0** = Mais preciso e consistente. "
            "**1.0** = Mais criativo e variado. "
            "**Recomendado: 0.3-0.5** para atendimento ao cliente."
        ),
        key="llm_temperature",
    )

    st.divider()

    # --- API Key própria (opcional) ---
    st.subheader("Chave de API própria (opcional)")
    st.caption(
        "Se você possui sua própria chave de API, pode usá-la aqui. "
        "Isso permite controlar seus custos diretamente. "
        "Se deixar em branco, será usada a chave global da plataforma."
    )

    current_key = llm_cfg.get("api_key", "")
    # Mostra placeholder mascarado se já tem chave
    placeholder = "sk-...sua-chave-aqui" if not current_key else "Chave configurada (deixe vazio para manter)"
    new_api_key = st.text_input(
        f"API Key ({selected_provider_label})",
        value="",
        type="password",
        placeholder=placeholder,
        help=f"Sua chave de API do {selected_provider_label}. Será armazenada de forma segura.",
        key="llm_api_key",
    )

    # Checkbox para remover chave existente
    remove_key = False
    if current_key:
        remove_key = st.checkbox(
            "Remover minha chave e usar a chave da plataforma",
            key="llm_remove_key",
        )

    # --- Salvar ---
    st.divider()
    if st.button("Salvar Configuração do Modelo", type="primary"):
        # Resolve API key
        if remove_key:
            final_key = ""
        elif new_api_key:
            final_key = new_api_key
        else:
            final_key = current_key  # Mantém a existente

        new_llm_config = {
            "provider": selected_provider,
            "model": selected_model,
            "temperature": selected_temperature,
        }
        # Só salva api_key se tiver valor (não polui config com string vazia)
        if final_key:
            new_llm_config["api_key"] = final_key

        try:
            new_tools_config = t_config.copy()
            new_tools_config["llm_config"] = new_llm_config

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clients SET tools_config = %s WHERE id = %s",
                        (json.dumps(new_tools_config), user_data["id"]),
                    )

            user_data["tools_config"] = new_tools_config
            st.session_state["user_data"] = user_data
            st.success(
                f"Modelo atualizado para **{selected_model}** via **{selected_provider_label}**!"
            )
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")
