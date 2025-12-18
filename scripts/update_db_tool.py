import os
import psycopg2
from psycopg2.extras import Json

# Configuração de Conexão
DB_URL = os.getenv("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")
CLIENT_TOKEN = "03ec6549-9d88-44bd-8946-0b118d2d1794" # O Token do seu print/JSON

def enable_tool():
    if not DB_URL:
        print("❌ DATABASE_URL não definida.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # 1. Pega o config atual
        cur.execute("SELECT tools_config FROM clients WHERE token = %s", (CLIENT_TOKEN,))
        row = cur.fetchone()
        
        if not row:
            print("❌ Cliente não encontrado para este token!")
            return

        current_config = row[0] or {}
        print(f"Config Atual: {current_config}")

        # 2. Adiciona a tool
        current_config['consultar_cep'] = True
        
        # 3. Atualiza no banco
        cur.execute(
            "UPDATE clients SET tools_config = %s WHERE token = %s",
            (Json(current_config), CLIENT_TOKEN)
        )
        conn.commit()
        print(f"✅ Sucesso! Nova Config: {current_config}")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    enable_tool()
