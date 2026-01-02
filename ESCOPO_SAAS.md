# PROJETO KESTRA 2.0 - SaaS Architecture (Gemini Edition) 💎

## 1. Objetivo
Plataforma SaaS Multi-Tenant simplificada, delegando a infraestrutura de vetores para o **Google Gemini File Search** e gerenciando configurações no **Postgres (`aiahub`)**.

## 2. Nova Arquitetura

### 🏭 Camada de Orquestração (Kestra)
- **Papel:** "Router" Simples.
- **Responsabilidade:** Recebe webhook -> Passa `client_token` para o Python.
- **Zero Config:** O Kestra NÃO sabe nada sobre prompts ou arquivos.

### 🧠 Camada de Inteligência (Python Workers)
- **Papel:** Controlador de Lógica.
- **Fluxo:**
    1. Recebe `client_token`.
    2. Conecta no `aiahub` (Postgres).
    3. `SELECT config, gemini_store_id FROM clients WHERE token = ...`
    4. Instancia cliente Gemini apontando para o `store_id` específico.
    5. `Gemini.generate_content(prompt, tools=..., context=store_id)`
    6. Retorna resposta.

### 💾 Camada de Dados (`aiahub`)

#### Tabela `clients`
Armazena a "Identidade" de cada cliente.
```sql
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL, -- Chave de API / Webhook
    system_prompt TEXT DEFAULT 'Você é um assistente útil.',
    gemini_store_id VARCHAR(255),       -- ID do "Corpus" no Google
    tools_config JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Tabela `client_files`
Gatekeeper de arquivos para evitar duplicatas (Hash Check).
```sql
CREATE TABLE client_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    file_hash VARCHAR(32) NOT NULL,     -- MD5 do conteúdo
    google_file_uri VARCHAR(255),       -- URI do arquivo na nuvem do Google
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, file_hash)        -- Impede upload repetido
);
```

## 3. Vantagens da Mudança
1.  **Zero Infra Vetorial:** Adeus Chroma/Docker/Volumes. O Google gerencia os vetores.
2.  **Contexto Infinito:** O Gemini busca no documento com janelas enormes (1M/2M tokens).
3.  **Simplicidade:** O código Python fica minúsculo, quase um proxy inteligente.

## 4. Plano de Migração
1.  [ ] Modelar Tabela `clients` no Postgres.
2.  [ ] Criar script `admin_create_client.py` (Para criar Stores no Google e salvar no DB).
3.  [ ] Atualizar `rag_worker.py` para usar a nova lógica.
