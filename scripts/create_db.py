import psycopg2
import os
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# URL de Conexão (hardcoded por enquanto para garantir o setup, idealmente viria de .env)
# O usuário forneceu: postgresql://postgres:Mvmr2003!Postgres@178.156.143.131:5432/aiahub
DB_URL = "postgresql://postgres:Mvmr2003!Postgres@178.156.143.131:5432/aiahub"

DDL_COMMANDS = [
    # Habilitar extensão para UUID se não existir
    "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
    
    # Tabela de Clientes
    """
    CREATE TABLE IF NOT EXISTS clients (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL,
        token VARCHAR(255) UNIQUE NOT NULL,
        system_prompt TEXT DEFAULT 'Você é um assistente útil.',
        gemini_store_id VARCHAR(255),
        tools_config JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW()
    );
    """,
    
    # Tabela de Arquivos (Gatekeeper)
    """
    CREATE TABLE IF NOT EXISTS client_files (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
        filename VARCHAR(255) NOT NULL,
        file_hash VARCHAR(32) NOT NULL,
        google_file_uri VARCHAR(255),
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(client_id, file_hash)
    );
    """
]

def init_db():
    conn = None
    try:
        logger.info("🔌 Conectando ao Banco de Dados aiahub...")
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        for command in DDL_COMMANDS:
            logger.info(f"🔨 Executando SQL: {command.strip()[:50]}...")
            cur.execute(command)
            
        conn.commit()
        cur.close()
        logger.info("✅ Tabelas 'clients' e 'client_files' criadas com sucesso!")
        
    except Exception as e:
        logger.error(f"❌ Erro ao criar banco: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    init_db()
