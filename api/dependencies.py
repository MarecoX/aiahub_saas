from fastapi import Header, HTTPException
import os
import sys

# Ajusta Path para importar scripts/saas_db.py
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_shared_dir = os.path.join(current_dir, "..", "scripts", "shared")
sys.path.append(scripts_shared_dir)

from saas_db import get_connection  # noqa: E402


def get_db_connection():
    """Dependência para obter conexão com banco de dados."""
    try:
        conn = get_connection()
        return conn
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database Connection Error: {str(e)}"
        )


def verify_token(x_api_token: str = Header(...)):
    """
    Simples verificação de Token de Admin via Header 'x-api-token'.
    Definir ADMIN_SECRET no .env
    """
    admin_secret = os.getenv("ADMIN_API_SECRET", "123456")  # Default inseguro para dev
    if x_api_token != admin_secret:
        raise HTTPException(status_code=401, detail="Invalid Admin Token")
