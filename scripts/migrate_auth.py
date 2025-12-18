import os
import secrets
import hashlib
from saas_db import get_connection

def run_migration():
    print("🚀 Iniciando Migração de Autenticação...")
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Adicionar colunas se não existirem
            print("1. Adicionando colunas de Auth...")
            queries = [
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;",
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS password_hash TEXT;",
                "ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;"
            ]
            
            for q in queries:
                try:
                    cur.execute(q)
                except Exception as e:
                    print(f"⚠️ Erro ao executar query (pode já existir): {e}")
                    conn.rollback() # Rollback parcial se falhar
                else:
                    conn.commit()

            # 2. Criar Admin Default
            cur.execute("SELECT count(*) as total FROM clients WHERE is_admin = TRUE")
            res = cur.fetchone()
            # Como a conexão usa dict_row, acessamos por chave
            admin_count = res['total'] if res else 0
            
            if admin_count == 0:
                print("2. Criando Super Admin Padrão...")
                admin_user = "admin"
                default_pass = "123456"
                pass_hash = hashlib.sha256(default_pass.encode()).hexdigest()
                
                try:
                    # Tenta update primeiro se 'admin' já existir como nome
                    cur.execute("""
                        INSERT INTO clients (name, username, password_hash, is_admin, token, system_prompt)
                        VALUES ('Super Admin', %s, %s, TRUE, 'admin_token', 'System Admin')
                        ON CONFLICT (username) DO NOTHING
                    """, (admin_user, pass_hash))
                    conn.commit()
                    print(f"✅ Admin criado! User: {admin_user} | Pass: {default_pass}")
                except Exception as e:
                    print(f"Erro ao criar admin: {e}")
                    conn.rollback()
            else:
                print("ℹ️ Admin já existe.")

    print("✅ Migração Concluída!")

if __name__ == "__main__":
    run_migration()
