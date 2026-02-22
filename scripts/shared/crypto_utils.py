"""
crypto_utils.py - Criptografia de segredos (API keys etc.)

Usa Fernet (AES-128-CBC + HMAC-SHA256) via biblioteca `cryptography`.
A master key vem da env var ENCRYPTION_KEY (base64 url-safe de 32 bytes).

Gerar uma chave nova (rode uma vez):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Adicione no .env:
    ENCRYPTION_KEY=<valor gerado>
"""

import os
import logging

logger = logging.getLogger("CryptoUtils")

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False
    Fernet = None
    InvalidToken = Exception
    logger.warning("Pacote 'cryptography' não instalado — criptografia desativada, API keys tratadas como plaintext.")

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

# Prefixo para identificar valores já criptografados
_ENC_PREFIX = "enc:"


def _get_fernet():
    if not _HAS_CRYPTO:
        return None
    if not _ENCRYPTION_KEY:
        logger.warning("ENCRYPTION_KEY não definida — criptografia desativada.")
        return None
    try:
        return Fernet(_ENCRYPTION_KEY.encode())
    except Exception as e:
        logger.error(f"ENCRYPTION_KEY inválida: {e}")
        return None


def encrypt(plaintext: str) -> str:
    """Criptografa uma string. Retorna com prefixo 'enc:'.
    Se não houver ENCRYPTION_KEY, retorna o valor original (graceful degradation)."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_ENC_PREFIX):
        return plaintext  # já criptografado
    f = _get_fernet()
    if not f:
        return plaintext
    token = f.encrypt(plaintext.encode()).decode()
    return f"{_ENC_PREFIX}{token}"


def decrypt(value: str) -> str:
    """Descriptografa uma string com prefixo 'enc:'.
    Se não tiver prefixo, assume plaintext legado e retorna como está."""
    if not value:
        return value
    if not value.startswith(_ENC_PREFIX):
        return value  # plaintext legado — compatível com dados antigos
    f = _get_fernet()
    if not f:
        logger.error("Impossível descriptografar sem ENCRYPTION_KEY.")
        return ""
    try:
        encrypted = value[len(_ENC_PREFIX):]
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        logger.error("Falha ao descriptografar — token inválido ou key errada.")
        return ""
