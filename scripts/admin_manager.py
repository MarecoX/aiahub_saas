import os
import uuid
import psycopg
import google.generativeai as genai
from dotenv import load_dotenv

# Carrega variáveis de ambiente (.env na raiz)
load_dotenv(dotenv_path="../.env")

# Configuração
DB_URL = os.getenv("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("❌ Erro: GEMINI_API_KEY não encontrada no .env")

# genai.configure(api_key=GEMINI_API_KEY) # Opcional se não for criar Store real agora

def create_client(name, token, system_prompt, timeout=60):
    """
    1. Cria um Vector Store (Corpus) no Google Gemini (Simulado por enquanto).
    2. Salva o Cliente no Postgres com o ID do Store e Timeout.
    """
    if not DB_URL:
        print("❌ DB_URL não definida.")
        return

    try:
        print(f"🚀 Iniciando Onboarding: {name}...")
        
        # 1. Simular Store ID (Placeholder)
        store_id = f"store_{uuid.uuid4().hex[:8]}" 
        print(f"✅ Store ID Virtual Gerado: {store_id}")

        # 2. Salvar no Postgres (Psycopg 3)
        print("💾 Salvando no Banco de Dados...")
        
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                sql = """
                    INSERT INTO clients (name, token, system_prompt, gemini_store_id, human_attendant_timeout)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                """
                cur.execute(sql, (name, token, system_prompt, store_id, timeout))
                client_id = cur.fetchone()[0]
                
        print(f"🎉 Cliente Criado com Sucesso!")
        print(f"🆔 ID: {client_id}")
        print(f"🔑 Token: {token}")
        print(f"⏳ Timeout Humano: {timeout} min")
        
    except Exception as e:
        print(f"❌ Erro ao criar cliente: {e}")

if __name__ == "__main__":
    print("--- 🏭 Kestra 2.0 Client Onboarding 🏭 ---")
    c_name = input("Nome do Cliente (ex: Pizzaria): ")
    c_token = input("Token/Instance ID (ex: 55119999999): ")
    c_prompt = input("System Prompt (ex: Você é um robô...): ")
    c_timeout = input("Timeout de Pausa (minutos) [60]: ")
    
    timeout_val = int(c_timeout) if c_timeout.isdigit() else 60
    
    if c_name and c_token:
        create_client(c_name, c_token, c_prompt, timeout_val)
    else:
        print("Cancelado.")
