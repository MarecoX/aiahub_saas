-- 1. Cria colunas de autenticação na tabela clients
ALTER TABLE clients ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;

-- 2. Cria o Super Admin (Senha default: 123456 -> hash SHA256)
-- O hash abaixo é de '123456'. Se quiser outra senha, gere o SHA256 dela.
INSERT INTO clients (name, username, password_hash, is_admin, token, system_prompt)
VALUES (
    'Super Admin', 
    'admin', 
    '8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92', 
    TRUE, 
    'admin_token', 
    'System Admin'
)
ON CONFLICT (username) DO NOTHING;
