import sys
import os
import asyncio
import logging
import random
import re
from kestra import Kestra

# Adiciona shared folder e uazapi folder ao path
shared_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
uazapi_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(shared_dir)
sys.path.append(uazapi_dir)

from uazapi_saas import send_whatsapp_message, send_whatsapp_audio, send_whatsapp_media  # noqa: E402
from message_buffer import _split_natural_messages, convert_md_to_whatsapp  # noqa: E402


# Regex que identifica linhas que sao itens de lista (numerados, bullets, emojis)
_LIST_ITEM_RE = re.compile(
    r"^\s*"  # espaco opcional
    r"(?:"
    r"\d{1,3}[.)\-]"  # 1. ou 1) ou 1-
    r"|\d{1,3}\s*[\U0001F300-\U0001FAFF]"  # 1 👉 (numero + emoji)
    r"|[-*•]"  # - ou * ou •
    r"|[\U0001F300-\U0001FAFF]"  # emoji no inicio
    r")"
    r"\s",  # seguido de espaco
    re.UNICODE,
)


def _merge_list_items(parts: list[str]) -> list[str]:
    """
    Reagrupa fragmentos que sao itens de lista numa unica mensagem.
    Evita que listas numeradas sejam enviadas como mensagens separadas.

    Ex: ["Opcoes:", "1 Comprar", "2 Vender", "3 SAC", "Escolha uma opcao"]
    ->  ["Opcoes:\n\n1 Comprar\n\n2 Vender\n\n3 SAC", "Escolha uma opcao"]
    """
    if len(parts) <= 1:
        return parts

    merged = []
    buffer = []

    for part in parts:
        is_list_item = bool(_LIST_ITEM_RE.match(part))

        if is_list_item:
            buffer.append(part)
        else:
            # Nao e item de lista: flush buffer se tiver
            if buffer:
                merged.append("\n".join(buffer))
                buffer = []
            merged.append(part)

    # Flush final
    if buffer:
        merged.append("\n".join(buffer))

    return merged


# --- BOOTSTRAP AMBIENTE KESTRA (Igual ao rag_worker.py) ---
def ensure_env(key, default):
    if not os.getenv(key):
        print(
            f"⚠️ [BOOTSTRAP-Sender] Variável {key} não encontrada. Usando default: {default}"
        )
        os.environ[key] = default


ensure_env("VECTOR_STORE_PATH", "vectorstore")
ensure_env("RAG_FILES_DIR", "rag_files")
ensure_env("BUFFER_KEY_SUFIX", "_buffer")
ensure_env("BUFFER_TTL", "300")
# Corrige incompatibilidade de nomes (Kestra usa DATABASE_URL, App usa DATABASE_CONNECTION_URI)
if os.getenv("DATABASE_URL") and not os.getenv("DATABASE_CONNECTION_URI"):
    os.environ["DATABASE_CONNECTION_URI"] = os.getenv("DATABASE_URL")

# Configura logs para sair no STDOUT (evita ficar vermelho/ERROR no Kestra)
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("KestraSend")


async def _run_sender_unsafe():
    import re

    chat_id = os.getenv("KESTRA_CHAT_ID")
    raw_response = os.getenv("KESTRA_RESPONSE_TEXT")

    if not chat_id or not raw_response:
        logger.info("Nada para enviar.")
        return

    # Dynamic Routing (Instance Selection)
    dynamic_url = os.getenv("KESTRA_API_URL")
    dynamic_key = os.getenv("KESTRA_API_KEY")

    # --- CLIENT CONFIG CHECK ---
    # Verifica se o cliente prefere quebra por parágrafos (Estilo SID/Humanizado)
    use_paragraph_split = False
    try:
        from saas_db import get_client_config

        # dynamic_key é o token do cliente/provider
        client_cfg = get_client_config(dynamic_key)
        if client_cfg:
            tools_cfg = client_cfg.get("tools_config", {})
            # Pode estar na raiz do tools_config ou dentro de 'whatsapp'
            if tools_cfg.get("whatsapp", {}).get("split_by_paragraph"):
                use_paragraph_split = True
            elif tools_cfg.get("split_by_paragraph"):  # Backwards/Direct support
                use_paragraph_split = True

            if use_paragraph_split:
                logger.info("🔪 Modo 'Split by Paragraph' ATIVADO para este cliente.")
    except Exception as e:
        logger.warning(f"⚠️ Erro ao buscar config do cliente para split logic: {e}")

    # --- MARKDOWN → WHATSAPP CONVERSION ---
    # Aplica conversao ANTES de qualquer split (ambos os modos recebem texto limpo)
    raw_response = convert_md_to_whatsapp(raw_response)

    # --- SEO/SEQUENTIAL SENDING LOGIC ---
    # O objetivo é respeitar a ordem: Texto -> Imagem -> Texto -> Video...

    media_extensions = r"\.(?:mp3|wav|ogg|m4a|opus|mp4|avi|mov|jpg|jpeg|png|gif|webp|pdf|doc|docx|xls|xlsx|txt|csv)"

    # Combina Regex para pegar Markdown OU Raw Link
    # Group 1: Caption (Markdown)
    # Group 2: URL (Markdown)
    # Group 3: URL (Raw)
    pattern = re.compile(
        r"\[([^\]]*)\]\((https?://[^\)]+" + media_extensions + r")\)|"  # Markdown
        r"((?<!\()https?://[^\s]+" + media_extensions + r")",  # Raw
        re.IGNORECASE,
    )

    last_pos = 0
    total_sent = 0
    medias_count = 0

    for match in pattern.finditer(raw_response):
        # 1. Envia o TEXTO antes da mídia (se houver)
        pre_text = raw_response[last_pos : match.start()].strip()
        if pre_text:
            if use_paragraph_split:
                # Lógica SID: Quebra por parágrafo (\n\n) + reagrupa listas
                parts = [p.strip() for p in re.split(r"\n\s*\n", pre_text) if p.strip()]
                parts = _merge_list_items(parts)
            else:
                # Lógica Kestra Default: Quebra natural inteligente
                parts = _split_natural_messages(pre_text)
                parts = _merge_list_items(parts)

            for part in parts:
                try:
                    await send_whatsapp_message(
                        chat_id, part, api_key=dynamic_key, base_url=dynamic_url
                    )
                    logger.info(f"📝 Texto enviado: {part[:30]}...")
                    # Delay um pouco maior se for paragraph split para dar tempo de ler
                    delay = (
                        random.uniform(1.5, 3.0)
                        if use_paragraph_split
                        else random.uniform(1.0, 2.5)
                    )
                    await asyncio.sleep(delay)
                    total_sent += 1
                except Exception as e:
                    logger.error(f"Erro ao enviar texto: {e}")

        # 2. Prepara a MÍDIA
        caption = match.group(1) or ""
        url = match.group(2) or match.group(3)

        # Limpa legenda se for igual a URL ou vazia
        if caption.strip() == url.strip() or caption.startswith("http"):
            caption = ""

        # Determina tipo
        media_type = "document"
        ext = url.split(".")[-1].lower()
        if ext in ["mp3", "wav", "ogg", "m4a", "opus"]:
            media_type = "audio"
        elif ext in ["mp4", "avi", "mov"]:
            media_type = "video"
        elif ext in ["jpg", "jpeg", "png", "gif", "webp"]:
            media_type = "image"

        # 3. Envia a MÍDIA
        try:
            if media_type == "audio":
                await send_whatsapp_audio(
                    chat_id, url, api_key=dynamic_key, base_url=dynamic_url
                )
            else:
                await send_whatsapp_media(
                    chat_id,
                    url,
                    media_type=media_type,
                    caption=caption,  # Envia legenda junto com a mídia (se houver)
                    api_key=dynamic_key,
                    base_url=dynamic_url,
                )
            logger.info(f"📎 Mídia enviada ({media_type}): {url[:30]}...")
            medias_count += 1
            total_sent += 1
            await asyncio.sleep(1.5)  # Tempo para processar mídia
        except Exception as e:
            logger.error(f"Erro ao enviar mídia {url}: {e}")

        last_pos = match.end()

    # 4. Envia o RESTANTE do texto (pós-última mídia)
    remaining_text = raw_response[last_pos:].strip()
    if remaining_text:
        if use_paragraph_split:
            # Lógica SID: Quebra por parágrafo + reagrupa listas
            parts = [
                p.strip() for p in re.split(r"\n\s*\n", remaining_text) if p.strip()
            ]
            parts = _merge_list_items(parts)
        else:
            # Lógica Kestra Default
            parts = _split_natural_messages(remaining_text)
            parts = _merge_list_items(parts)

        for part in parts:
            try:
                await send_whatsapp_message(
                    chat_id, part, api_key=dynamic_key, base_url=dynamic_url
                )
                logger.info(f"📝 Texto final enviado: {part[:30]}...")
                delay = (
                    random.uniform(1.5, 3.0)
                    if use_paragraph_split
                    else random.uniform(1.0, 2.0)
                )
                await asyncio.sleep(delay)
                total_sent += 1
            except Exception as e:
                logger.error(f"Erro ao enviar texto final: {e}")

    Kestra.outputs({"status": "sent", "count": total_sent, "medias": medias_count})


async def run_sender():
    try:
        await _run_sender_unsafe()
    except Exception as e:
        logger.error(f"❌ Erro Crítico no Sender: {e}", exc_info=True)
        try:
            # Try to recover context for logging
            chat_id = os.getenv("KESTRA_CHAT_ID")
            from saas_db import log_error, get_client_config

            dynamic_key = os.getenv("KESTRA_API_KEY")

            client_cfg = None
            if dynamic_key:
                try:
                    client_cfg = get_client_config(dynamic_key)
                except Exception:
                    pass

            cid = client_cfg.get("id") if client_cfg else None
            log_error(
                "whatsapp_sender.py",
                e,
                {"context": "wrapper_catch"},
                client_id=cid,
                chat_id=chat_id,
            )
        except Exception as logger_err:
            logger.error(f"Failed to log error: {logger_err}")
        raise e


if __name__ == "__main__":
    asyncio.run(run_sender())
