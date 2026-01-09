# usado apenas no meta_manager.py

import os
import io
import logging
from openai import OpenAI
from google import genai
from google.genai import types

logger = logging.getLogger("MediaUtils")

# Load Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    try:
        import streamlit as st

        OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    try:
        import streamlit as st

        GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass


def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """
    Transcreve áudio usando OpenAI Whisper.
    Recebe bytes diretos, salva temp em memória virtual (io.BytesIO) com nome fictício.
    """
    if not OPENAI_API_KEY:
        logger.error("❌ OPENAI_API_KEY faltante para transcrição.")
        return "[Erro: Transcrição indisponível]"

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        # Whisper exige um objeto "arquivo" com nome.
        # BytesIO resolve, mas precisa do atributo name.
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        logger.info(f"🎙️ Transcrevendo áudio ({len(audio_bytes)} bytes)...")
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="pt",  # Force PT for better accuracy in Brazil context
        )

        text = transcript.text
        logger.info(f"✅ Transcrição: {text[:50]}...")

        # Salva usage para tracking (estima segundos pelo tamanho do áudio)
        # Aproximação: 16kB/s para OGG Opus
        try:
            from usage_tracker import save_usage

            estimated_seconds = len(audio_bytes) / 16000
            save_usage(
                client_id="unknown",  # Será passado pelo caller quando disponível
                chat_id="unknown",
                source="media",
                provider="uazapi",
                whisper_seconds=int(estimated_seconds),
            )
        except Exception:
            pass

        return text

    except Exception as e:
        logger.error(f"❌ Erro na transcrição Whisper: {e}")
        return f"[Erro na transcrição: {e}]"


def analyze_image_bytes(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Analisa imagem usando Gemini Vision (1.5 Flash ou superior).
    """
    if not GEMINI_API_KEY:
        logger.error("❌ GEMINI_API_KEY faltante para visão computacional.")
        return "[Erro: Visão Computacional indisponível]"

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        logger.info(f"👁️ Analisando imagem ({len(image_bytes)} bytes)...")

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                "Descreva esta imagem detalhadamente para que eu possa responder ao usuário sobre ela. Se houver texto, transcreva-o integralmente.",
            ],
        )

        text = response.text.strip()
        logger.info(f"✅ Visão: {text[:50]}...")

        # Salva usage para tracking
        try:
            from usage_tracker import save_usage

            gemini_usage = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                gemini_usage = {
                    "input_tokens": getattr(
                        response.usage_metadata, "prompt_token_count", 0
                    ),
                    "output_tokens": getattr(
                        response.usage_metadata, "candidates_token_count", 0
                    ),
                }
            save_usage(
                client_id="unknown",
                chat_id="unknown",
                source="media",
                provider="uazapi",
                gemini_usage=gemini_usage,
                images_count=1,
            )
        except Exception:
            pass

        return text

    except Exception as e:
        logger.error(f"❌ Erro na análise Gemini Vision: {e}")
        return f"[Erro na análise de imagem: {e}]"
