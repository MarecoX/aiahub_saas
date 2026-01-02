"""
Utilitários de Autenticação - Bcrypt para Senhas
"""

import bcrypt


def hash_password(password: str) -> str:
    """
    Gera hash bcrypt com salt automático.
    Cost factor padrão: 12 (2^12 = 4096 iterações)

    Args:
        password: Senha em texto plano

    Returns:
        Hash bcrypt no formato $2b$12$...
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """
    Verifica se a senha corresponde ao hash bcrypt.

    Args:
        password: Senha em texto plano para verificar
        hashed: Hash bcrypt armazenado

    Returns:
        True se a senha estiver correta
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def is_bcrypt_hash(hashed: str) -> bool:
    """
    Verifica se o hash é no formato bcrypt (começa com $2b$ ou $2a$).
    Útil para migração gradual de SHA-256 para bcrypt.
    """
    return hashed.startswith("$2b$") or hashed.startswith("$2a$")
