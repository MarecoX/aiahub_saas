"""
llm_provider.py - Factory para instanciar LLMs por cliente.

Suporta OpenAI (direto) e OpenRouter (via compatibilidade OpenAI).
Cada cliente pode configurar provider, modelo, temperature e até sua própria API key.

Uso:
    from llm_provider import get_llm, get_openai_client
    llm = get_llm(client_config)                   # LangChain ChatOpenAI
    client = get_openai_client(client_config)       # openai.OpenAI raw (reminders etc)
"""

import os
import logging

from langchain_openai import ChatOpenAI
try:
    from scripts.shared.crypto_utils import decrypt
except ImportError:
    from crypto_utils import decrypt

logger = logging.getLogger("LLMProvider")

# --- Env vars globais (fallback quando cliente não tem chave própria) ---
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# --- Catálogo de modelos por provider ---
# Facilmente extensível: basta adicionar entradas aqui.
MODEL_CATALOG = {
    "openai": [
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini (Rápido e barato)", "default": True},
        {"id": "gpt-4o", "label": "GPT-4o (Mais capaz)"},
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 Mini"},
        {"id": "gpt-4.1", "label": "GPT-4.1"},
    ],
    "openrouter": [
        {"id": "openai/gpt-4o-mini", "label": "GPT-4o Mini (OpenAI)", "default": True},
        {"id": "openai/gpt-4o", "label": "GPT-4o (OpenAI)"},
        {"id": "openai/gpt-4.1-mini", "label": "GPT-4.1 Mini (OpenAI)"},
        {"id": "openai/gpt-4.1", "label": "GPT-4.1 (OpenAI)"},
        {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash (Google)"},
        {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro (Google)"},
        {"id": "anthropic/claude-sonnet-4", "label": "Claude Sonnet 4 (Anthropic)"},
        {"id": "anthropic/claude-haiku-3.5", "label": "Claude Haiku 3.5 (Anthropic)"},
        {"id": "meta-llama/llama-4-maverick", "label": "Llama 4 Maverick (Meta)"},
        {"id": "deepseek/deepseek-chat-v3", "label": "DeepSeek V3 (DeepSeek)"},
    ],
}

# Providers disponíveis (label para UI)
PROVIDER_OPTIONS = {
    "openai": "OpenAI (Direto)",
    "openrouter": "OpenRouter (Multi-provider)",
}

# Defaults
_DEFAULT_PROVIDER = "openai"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_TEMPERATURE = 0.5


def _resolve_llm_config(client_config: dict) -> dict:
    """
    Extrai e resolve a configuração de LLM do client_config.
    Retorna dict com provider, model, temperature, api_key, base_url.
    """
    tools_config = client_config.get("tools_config", {}) or {}
    llm_cfg = tools_config.get("llm_config", {}) or {}

    provider = llm_cfg.get("provider", _DEFAULT_PROVIDER)
    model = llm_cfg.get("model", "")
    temperature = llm_cfg.get("temperature", _DEFAULT_TEMPERATURE)
    client_api_key = decrypt(llm_cfg.get("api_key", ""))  # descriptografa chave do cliente

    # Resolve API key: chave do cliente > env var global
    if provider == "openrouter":
        api_key = client_api_key or _OPENROUTER_API_KEY
        base_url = OPENROUTER_BASE_URL
        if not model:
            model = "openai/gpt-4o-mini"
    else:
        api_key = client_api_key or _OPENAI_API_KEY
        base_url = None  # usa default da OpenAI
        if not model:
            model = _DEFAULT_MODEL

    return {
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "api_key": api_key,
        "base_url": base_url,
    }


def get_llm(client_config: dict) -> ChatOpenAI:
    """
    Retorna instância de ChatOpenAI configurada para o cliente.
    Compatível com OpenAI direto e OpenRouter (mesma API).
    """
    cfg = _resolve_llm_config(client_config)

    if not cfg["api_key"]:
        logger.warning(
            f"API key não encontrada para provider={cfg['provider']}. "
            "Tentando fallback OpenAI..."
        )
        cfg["api_key"] = _OPENAI_API_KEY
        cfg["base_url"] = None
        cfg["model"] = _DEFAULT_MODEL

    kwargs = {
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "api_key": cfg["api_key"],
    }
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]

    logger.info(f"LLM: provider={cfg['provider']} model={cfg['model']}")
    return ChatOpenAI(**kwargs)


def get_openai_client(client_config: dict):
    """
    Retorna instância raw openai.OpenAI configurada para o cliente.
    Usado em contextos fora do LangChain (reminders, etc).
    """
    from openai import OpenAI

    cfg = _resolve_llm_config(client_config)

    if not cfg["api_key"]:
        cfg["api_key"] = _OPENAI_API_KEY
        cfg["base_url"] = None
        cfg["model"] = _DEFAULT_MODEL

    kwargs = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]

    return OpenAI(**kwargs), cfg["model"]


def get_model_label(provider: str, model_id: str) -> str:
    """Retorna label legível do modelo, ou o próprio ID se não encontrado."""
    for m in MODEL_CATALOG.get(provider, []):
        if m["id"] == model_id:
            return m["label"]
    return model_id
