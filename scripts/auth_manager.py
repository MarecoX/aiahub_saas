import hashlib
import logging
from .saas_db import get_connection

logger = logging.getLogger("AuthManager")

def hash_password(password: str) -> str:
    """Retorna o hash SHA256 da senha."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_login(username, password):
    """
    Verifica credenciais no banco.
    Retorna dict com dados do usuário ou None se falhar.
    """
    pwd_hash = hash_password(password)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, is_admin, gemini_store_id, system_prompt, followup_config, tools_config 
                FROM clients 
                WHERE username = %s AND password_hash = %s
            """, (username, pwd_hash))
            
            row = cur.fetchone()
            
            if row:
                return {
                    "id": str(row['id']),
                    "name": row['name'],
                    "is_admin": row['is_admin'],
                    "store_id": row['gemini_store_id'],
                    "system_prompt": row['system_prompt'],
                    "followup_config": row.get('followup_config', {}),
                    "tools_config": row.get('tools_config', {})
                }
            return None

def update_password(client_id, new_password):
    """Atualiza a senha de um cliente."""
    pwd_hash = hash_password(new_password)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE clients SET password_hash = %s WHERE id = %s", (pwd_hash, client_id))
            conn.commit()
    return True
