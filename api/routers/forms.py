"""
forms.py - Webhook para receber dados de formularios externos.

Endpoint publico (sem API key) que recebe qualquer JSON de formularios
(landing pages, Typeform, Respondi, Google Forms, etc.) e armazena o
contexto no Redis vinculado ao chat_id (telefone) do lead.

Suporta payloads flat (chave-valor) e payloads nested do Respondi/Typeform
com estrutura {form, respondent: {answers, raw_answers, respondent_utms}}.

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

# ── helpers de telefone ──────────────────────────────────────────────

PHONE_KEYS = [
    "phone", "telefone", "whatsapp", "celular", "mobile",
    "tel", "fone", "numero", "number", "phone_number",
]


def _coerce_phone_value(val) -> str | None:
    """Converte int/float/str para string de telefone, se possivel."""
    if isinstance(val, (int, float)):
        val = str(int(val))
    if isinstance(val, str) and len(val.strip()) >= 8:
        return val.strip()
    return None


def _normalize_phone(phone: str) -> str:
    """Remove caracteres nao-numericos e garante formato limpo."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) <= 11:
        digits = f"55{digits}"
    return digits


def _extract_phone(data: dict) -> str | None:
    """
    Tenta extrair o telefone do payload de forma inteligente.

    Procura em campos comuns (phone, telefone, whatsapp, celular, mobile)
    e normaliza para formato internacional (apenas digitos).
    Aceita valores string, int e float.
    """
    # Busca direta nas keys do payload
    for key in PHONE_KEYS:
        val = data.get(key)
        coerced = _coerce_phone_value(val)
        if coerced:
            return _normalize_phone(coerced)

    # Busca case-insensitive
    for k, v in data.items():
        if any(pk in k.lower() for pk in PHONE_KEYS):
            coerced = _coerce_phone_value(v)
            if coerced:
                return _normalize_phone(coerced)

    # Busca dentro de "respostas" / "answers" / "fields"
    for container_key in ("respostas", "answers", "fields", "data", "form_data"):
        container = data.get(container_key, {})
        if isinstance(container, dict):
            for k, v in container.items():
                if any(pk in k.lower() for pk in PHONE_KEYS):
                    coerced = _coerce_phone_value(v)
                    if coerced:
                        return _normalize_phone(coerced)

    return None


# ── parsing de payload Respondi / Typeform ───────────────────────────

def _unwrap_payload(data) -> dict | None:
    """
    Desembrulha payloads encapsulados em array ou formato n8n.

    Aceita:
      - [{...}]                         → {...}
      - {headers, body: {...}, ...}     → body
      - {...}                           → direto
    """
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        else:
            return None

    if not isinstance(data, dict):
        return None

    # n8n wrapper: tem "body" + ("webhookUrl" ou "headers")
    if "body" in data and ("webhookUrl" in data or "headers" in data):
        inner = data["body"]
        if isinstance(inner, dict):
            return inner

    return data


def _is_respondi_payload(data: dict) -> bool:
    """Detecta se o payload e do formato Respondi/Typeform."""
    return (
        isinstance(data.get("respondent"), dict)
        and isinstance(data.get("form"), dict)
    )


def _normalize_respondi_payload(data: dict) -> dict:
    """
    Converte payload Respondi/Typeform para formato normalizado.

    Input:
        {
            "form": {"form_name": "...", "form_id": "ag9uytVv"},
            "respondent": {
                "answers": {"Qual seu nome?": "Joao", ...},
                "raw_answers": [{"question": {...}, "answer": ...}, ...],
                "respondent_utms": {"utm_source": "ig", ...}
            }
        }

    Output:
        {
            "nome": "Joao",
            "telefone": "5511999999999",
            "email": "joao@email.com",
            "source": "Nome do Formulario",
            "respostas": {"Qual seu nome?": "Joao", ...},
            "utms": {"utm_source": "ig", ...}
        }
    """
    form_info = data.get("form", {})
    respondent = data.get("respondent", {})

    answers = respondent.get("answers", {})
    raw_answers = respondent.get("raw_answers", [])
    utms = respondent.get("respondent_utms", {})

    normalized: dict = {}

    # Form name como source
    form_name = form_info.get("form_name", "")
    if form_name:
        normalized["source"] = form_name

    # Extrair dados tipados de raw_answers (phone, name, email)
    for item in raw_answers:
        q = item.get("question", {})
        q_type = q.get("question_type", "")
        answer = item.get("answer")

        if q_type == "name" and answer:
            normalized["nome"] = str(answer)
        elif q_type == "email" and answer:
            normalized["email"] = str(answer)
        elif q_type == "phone" and answer:
            if isinstance(answer, dict):
                country = str(answer.get("country", "55"))
                phone_num = str(answer.get("phone", ""))
                normalized["telefone"] = f"{country}{phone_num}"
            else:
                normalized["telefone"] = str(answer)

    # Fallback: procurar telefone nos answers por keyword
    if "telefone" not in normalized and isinstance(answers, dict):
        for q_text, a_text in answers.items():
            if any(pk in q_text.lower() for pk in PHONE_KEYS):
                coerced = _coerce_phone_value(a_text)
                if coerced:
                    normalized["telefone"] = coerced
                    break

    # Fallback: procurar nome nos answers por keyword
    if "nome" not in normalized and isinstance(answers, dict):
        for q_text, a_text in answers.items():
            if any(nk in q_text.lower() for nk in ("nome", "name")):
                if isinstance(a_text, str) and a_text.strip():
                    normalized["nome"] = a_text.strip()
                    break

    # Respostas (dict pergunta→resposta)
    if answers:
        normalized["respostas"] = answers

    # UTMs — limpar valores vazios
    clean_utms = {k: v for k, v in utms.items() if v} if utms else {}
    if clean_utms:
        normalized["utms"] = clean_utms

    return normalized


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
        raw_body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")

    # Desembrulha payload (array, n8n wrapper)
    body = _unwrap_payload(raw_body)
    if not body:
        raise HTTPException(status_code=400, detail="Payload deve ser um objeto JSON nao-vazio")

    # Detecta e normaliza payload Respondi/Typeform
    if _is_respondi_payload(body):
        body = _normalize_respondi_payload(body)
        logger.info("📋 Payload Respondi/Typeform detectado e normalizado")

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
