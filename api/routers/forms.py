"""
forms.py - Webhook para receber dados de formularios externos.

Endpoint publico (sem API key) que recebe qualquer JSON de formularios
(landing pages, Typeform, Respondi, Google Forms, etc.) e armazena o
contexto no Redis vinculado ao chat_id (telefone) do lead.

Suporta payloads flat (chave-valor) e payloads nested do Respondi/Typeform
com estrutura {form, respondent: {answers, raw_answers, respondent_utms}}.

O rag_worker.py le esse contexto e injeta no system_prompt antes
de chamar a IA, para que ela saiba o que a pessoa ja preencheu.

Opcionalmente, envia uma saudacao proativa ao lead via WhatsApp
(quando send_greeting esta ativo no form_context).

URL: POST /api/v1/forms/{client_id}/submit
"""

import asyncio
import logging
import os
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from google import genai

from saas_db import get_client_config_by_id, get_default_provider, get_provider_config

logger = logging.getLogger("API_Forms")

router = APIRouter(tags=["Forms"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_gemini_client = None
if GEMINI_API_KEY:
    try:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        logger.warning("⚠️ Gemini client nao inicializado (greeting desabilitado)")


# ── envio proativo de saudacao ───────────────────────────────────────

async def _send_form_greeting(
    client_id: str,
    client_config: dict,
    phone: str,
    context_data: dict,
    form_cfg: dict,
):
    """
    Gera uma saudacao com IA e envia ao lead via WhatsApp (background task).
    """
    try:
        # 1. Gerar texto da saudacao via Gemini
        if not _gemini_client:
            logger.error("❌ Gemini client indisponivel — saudacao nao enviada")
            return

        from scripts.shared.lead_context import format_context_for_prompt

        context_text = format_context_for_prompt(context_data)
        form_instructions = form_cfg.get("instructions", "")
        system_prompt = client_config.get("system_prompt", "")

        prompt = (
            f"Voce e um assistente virtual profissional.\n"
            f"Perfil do assistente:\n{system_prompt[:1500]}\n\n"
            f"O lead acabou de preencher um formulario e seus dados sao:\n{context_text}\n\n"
        )
        if form_instructions:
            prompt += f"Instrucoes especificas do cliente:\n{form_instructions}\n\n"
        prompt += (
            "Sua tarefa: Gere uma UNICA mensagem de saudacao para enviar ao lead via WhatsApp.\n"
            "Regras:\n"
            "1. Seja breve, cordial e direto.\n"
            "2. Use o nome do lead se disponivel.\n"
            "3. Faca referencia ao interesse/dados do formulario.\n"
            "4. NAO use placeholders como [Nome]. NAO use markdown.\n"
            "5. Gere APENAS o texto da mensagem, sem explicacoes.\n"
        )

        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"temperature": 0.3},
        )
        greeting_text = response.text.strip()

        if not greeting_text or len(greeting_text) < 5:
            logger.warning("⚠️ Saudacao gerada vazia ou muito curta — abortando envio")
            return

        # 2. Descobrir provider e enviar
        provider_type, provider_cfg = get_default_provider(str(client_id))

        # Fallback: campo legado whatsapp_provider
        if not provider_type:
            provider_type = client_config.get("whatsapp_provider") or "none"
            provider_cfg = get_provider_config(str(client_id), provider_type) or {}

        if provider_type in (None, "", "none"):
            logger.warning(f"⚠️ Nenhum provider configurado para {client_config['name']} — saudacao nao enviada")
            return

        logger.info(f"📤 Enviando saudacao via {provider_type} para {phone}")

        if provider_type == "uazapi":
            from scripts.uazapi.uazapi_saas import send_whatsapp_message

            base_url = provider_cfg.get("url") or client_config.get("api_url") or ""
            api_key = provider_cfg.get("token") or provider_cfg.get("api_key") or client_config.get("token") or ""
            await send_whatsapp_message(phone, greeting_text, api_key=api_key, base_url=base_url)

        elif provider_type == "meta":
            from scripts.meta.meta_client import MetaClient

            token = provider_cfg.get("token", "")
            phone_id = provider_cfg.get("phone_id", "")
            if token and phone_id:
                meta = MetaClient(token=token, phone_id=phone_id)
                await meta.send_message_text(to=phone, text=greeting_text)
            else:
                logger.error("❌ Meta provider sem token ou phone_id — saudacao nao enviada")
                return

        elif provider_type == "lancepilot":
            from scripts.lancepilot.client import LancePilotClient

            lp_token = provider_cfg.get("token") or client_config.get("lancepilot_token") or ""
            workspace_id = provider_cfg.get("workspace_id") or client_config.get("lancepilot_workspace_id") or ""
            if lp_token and workspace_id:
                lp = LancePilotClient(token=lp_token)
                await asyncio.to_thread(lp.send_text_message_via_number, workspace_id, phone, greeting_text)
            else:
                logger.error("❌ LancePilot provider sem token ou workspace — saudacao nao enviada")
                return

        else:
            logger.warning(f"⚠️ Provider '{provider_type}' nao suportado para saudacao")
            return

        logger.info(f"✅ Saudacao enviada para {phone} (client={client_config['name']}, provider={provider_type})")

    except Exception as e:
        logger.error(f"❌ Erro ao enviar saudacao para {phone}: {e}")


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
async def submit_form(client_id: str, request: Request, background_tasks: BackgroundTasks):
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

        # --- Envio de saudacao proativa (background) ---
        if form_cfg.get("send_greeting"):
            background_tasks.add_task(
                _send_form_greeting,
                client_id=client_id,
                client_config=client_config,
                phone=phone,
                context_data=body,
                form_cfg=form_cfg,
            )
            logger.info(f"📤 Saudacao agendada para {phone}")

        return {"status": "ok", "chat_id": phone, "fields_received": len(body)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro ao processar formulario: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar formulario")
