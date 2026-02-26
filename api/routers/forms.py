"""
forms.py - Webhook para receber dados de formularios externos.

Endpoint publico (sem API key) que recebe qualquer JSON de formularios
(landing pages, Typeform, Google Forms, etc.) e armazena o contexto
no Redis vinculado ao chat_id (telefone) do lead.

O rag_worker.py le esse contexto e injeta no system_prompt antes
de chamar a IA, para que ela saiba o que a pessoa ja preencheu.

URL: POST /api/v1/forms/{client_id}/submit
"""

import logging
import os
import re

from fastapi import APIRouter, HTTPException, Request

from saas_db import get_client_config_by_id

logger = logging.getLogger("API_Forms")

router = APIRouter(tags=["Forms"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def _coerce_phone_value(val) -> str | None:
    """Converte int/float/str para string de telefone, se possivel."""
    if isinstance(val, (int, float)):
        val = str(int(val))
    if isinstance(val, str) and len(val.strip()) >= 8:
        return val.strip()
    return None


def _extract_phone(data: dict) -> str | None:
    """
    Tenta extrair o telefone do payload de forma inteligente.

    Procura em campos comuns (phone, telefone, whatsapp, celular, mobile)
    e normaliza para formato internacional (apenas digitos).
    Aceita valores string, int e float.
    """
    phone_keys = [
        "phone", "telefone", "whatsapp", "celular", "mobile",
        "tel", "fone", "numero", "number", "phone_number",
    ]

    # Busca direta nas keys do payload
    for key in phone_keys:
        val = data.get(key)
        coerced = _coerce_phone_value(val)
        if coerced:
            return _normalize_phone(coerced)

    # Busca case-insensitive
    for k, v in data.items():
        if any(pk in k.lower() for pk in phone_keys):
            coerced = _coerce_phone_value(v)
            if coerced:
                return _normalize_phone(coerced)

    # Busca dentro de "respostas" / "answers" / "fields"
    for container_key in ("respostas", "answers", "fields", "data", "form_data"):
        container = data.get(container_key, {})
        if isinstance(container, dict):
            for k, v in container.items():
                if any(pk in k.lower() for pk in phone_keys):
                    coerced = _coerce_phone_value(v)
                    if coerced:
                        return _normalize_phone(coerced)

    return None


def _normalize_phone(phone: str) -> str:
    """Remove caracteres nao-numericos e garante formato limpo."""
    digits = re.sub(r"\D", "", phone)
    # Se comeca com 0, remove (formato local BR)
    if digits.startswith("0"):
        digits = digits[1:]
    # Se nao tem codigo de pais, assume Brasil (55)
    if len(digits) <= 11:
        digits = f"55{digits}"
    return digits


@router.get("/{client_id}/submit")
async def submit_form_get(client_id: str):
    """Responde a GET requests (health-check de provedores de formulario)."""
    return {
        "status": "ok",
        "method": "POST",
        "detail": "Use POST to submit form data.",
    }


@router.post("/{client_id}/submit")
async def submit_form(client_id: str, request: Request):
    """
    Recebe dados de um formulario externo e salva o contexto no Redis.

    O payload pode ser qualquer JSON. O unico requisito e que contenha
    um campo de telefone (phone, telefone, whatsapp, celular, etc.)
    para vincular ao chat_id do WhatsApp.

    Exemplo de payload:
    ```json
    {
        "nome": "Joao Silva",
        "telefone": "11999999999",
        "interesse": "Plano Premium",
        "orcamento": "R$ 5.000"
    }
    ```

    Returns:
        {"status": "ok", "chat_id": "5511999999999"}
    """
    # Valida cliente pelo ID (UUID)
    client_config = get_client_config_by_id(client_id)
    if not client_config:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")

    # Verifica se form_context esta ativo
    tools_config = client_config.get("tools_config") or {}
    form_cfg = tools_config.get("form_context", {})
    if isinstance(form_cfg, bool):
        form_cfg = {"active": form_cfg}
    if not form_cfg.get("active"):
        raise HTTPException(
            status_code=403,
            detail="Contexto de formulario nao esta ativo para este cliente",
        )

    # Parse body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")

    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="Payload deve ser um objeto JSON nao-vazio")

    # Extrai telefone
    phone = _extract_phone(body)
    if not phone:
        raise HTTPException(
            status_code=422,
            detail=(
                "Nenhum campo de telefone encontrado no payload. "
                "Inclua um campo como 'phone', 'telefone', 'whatsapp' ou 'celular'."
            ),
        )

    # Salva no Redis
    try:
        from scripts.shared.lead_context import save_lead_context

        success = save_lead_context(
            redis_url=REDIS_URL,
            client_id=client_id,
            chat_id=phone,
            context_data=body,
        )

        if not success:
            raise HTTPException(status_code=500, detail="Erro ao salvar contexto no Redis")

        logger.info(
            f"📋 Form context salvo: client={client_config['name']}, "
            f"phone={phone}, fields={len(body)}"
        )

        return {"status": "ok", "chat_id": phone, "fields_received": len(body)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro ao processar formulario: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar formulario")
