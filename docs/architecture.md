# Arquitetura do Sistema 🏛️

## Modular Monolith
O Kestra 2.0 segue o padrão **Modular Monolith**. Isso significa que todos os serviços rodam no mesmo repositório e processo, mas são logicamente separados.

## 🗺️ Mapa do Codebase

## 🗺️ Mapa Detalhado dos Módulos

### 1. `/api` (Backend)
Gateway de entrada. Feito em FastAPI.
*   `routers/meta.py`: Recebe os Webhooks da Meta (WhatsApp Oficial). Valida assinatura (`hub.verify_token`) e despacha para fila/processamento.
*   `routers/clients.py`: CRUD de usuários e configurações do SaaS.
*   `services/meta_service.py`: Camada de serviço que processa o payload bruto do WhatsApp antes de salvar.

### 2. `/scripts` (Core Logic)
O cérebro do sistema. Scripts executados pelos workers do Kestra.

#### 🟢 Módulo: `meta` (WhatsApp Oficial)
*   **`meta_manager.py`:** Orquestrador principal. Recebe mensagem -> Identifica Cliente -> Carrega Histórico -> Chama LangChain -> Envia Resposta.
*   **`meta_client.py`:** Wrapper HTTP oficial. Métodos para `send_text`, `send_image`, `upload_media`, `mark_read`.
*   **`meta_oauth.py`:** Gerencia o fluxo de "Embedded Signup" (Login com Facebook).

#### 🟡 Módulo: `shared` (Bibliotecas Comuns)
*   **`saas_db.py`:** **[CRÍTICO]** Gerencia o pool de conexões (psycopg_pool). Contém todas as queries SQL (buscas de cliente, salvamento de mensagem).
*   **`media_utils.py`:** Processamento Multimodal (Exclusivo Meta Oficial).
    *   **Nota:** Processa áudio (Whisper) e imagens (Gemini) vindos da API Cloud. Não é utilizado pelo Uazapi ou LancePilot.
    *   `transcribe_audio_bytes()`: Transcreve áudio.
    *   `analyze_image_bytes()`: Descreve imagens.
*   **`tools_library.py`:** Definição das Tools (Calendar, CRM) que a IA pode usar.

#### 🟣 Módulo: `lancepilot` (Legacy/Mass)
*   `ingest.py`: Recebe webhook e faz "Debounce" (espera usuário parar de digitar).
*   `rag_worker.py`: Pipeline RAG. Busca documentos no Google Gemini Vector Store e gera resposta.
*   `sender.py`: Dispara a resposta final via API do LancePilot.

---

## 🔄 Fluxos de Dados (Arquitetura Híbrida)

O sistema opera em dois modos distintos: **Tempo Real (API)** e **Orquestrado (Kestra)**.

### Fluxo A: API Oficial (Meta Cloud) ⚡
**Execução:** FastAPI (Background Tasks)
**Não passa pelo Kestra.** A Meta exige respostas em <3s, então processamos tudo na memória da API.

1.  **Webhook:** Meta chama `POST /meta/webhook`.
2.  **FastAPI:** Valida a assinatura de segurança.
3.  **Processamento (`meta_manager.py`):**
    *   Identifica o Tenant pelo `display_phone_number`.
    *   Salva a mensagem no Postgres (`chat_messages`).
    *   **IA Decision:** Se o bot estiver ativo, chama o `langchain` para gerar resposta.
4.  **Envio:** `meta_client.py` dispara a resposta HTTP de volta para a Meta.

### Fluxo B: LancePilot e Uazapi ⚙️
**Execução:** Kestra Workflow Engine
Processos assíncronos, em massa ou agendados.

#### 1. LancePilot (Disparo em Massa)
Definido em: `flows/lancepilot_native.yaml`
Este fluxo é um **Pipeline** linear:
*   **Trigger:** Webhook do LancePilot (Cliente respondeu campanha).
*   **Step 1 (Ingest):** `ingest.py` recebe o JSON, valida e salva num buffer Redis (evita processar cada letra digitada).
*   **Step 2 (RAG):** `rag_worker.py` lê o buffer, busca contexto na Base de Conhecimento (Google Gemini) e gera a resposta via GPT/Gemini.
*   **Step 3 (Sender):** `sender.py` envia a resposta final para a API do LancePilot.

#### 2. Uazapi (Follow-up)
Definido em: `flows/saas_followup_cron.yaml`
Este fluxo é um **Loop Agendado** (Cron):
*   **Trigger:** A cada 5 minutos.
*   **Step 1:** O Kestra sobe um container Docker rodando `scripts/uazapi/followup_worker.py`.
*   **Lógica:** O script varre o banco buscando conversas "mornas" (sem resposta há X horas).
*   **Ação:** Se a IA decidir que vale a pena, envia uma mensagem "E aí, vamos fechar?" usando a API Uazapi.

---

## 🛠️ Como Cada Módulo Funciona (Deep Dive)

### Módulo `scripts/meta`
Focado em **Alta Performance**.
*   **`meta_client.py`:** É a "mão" do sistema. Sabe montar o JSON exato que a API do WhatsApp exige (Templates, Imagens, Botões).
*   **`meta_manager.py`:** É o "cérebro" rápido. Ele decide: "É mensagem de texto? É áudio? O cliente está pausado (Human Handover)?".

### Módulo `scripts/shared`
A "Cola" que une o sistema.
*   **`saas_db.py`:** Único ponto de contato com o banco. Se mudarmos a tabela `clients`, só alteramos aqui.
*   **`media_utils.py`:** Transforma "Binário" em "Texto". Recebe bytes de áudio OGG do WhatsApp, manda pra OpenAI (Whisper) e devolve string.

### Módulo `flows/` (YAMLs do Kestra)
São as "Receitas de Bolo" que o Kestra segue.
*   Eles definem a **Infraestrutura**: "Use a imagem Docker `marsllator/my-kestra-worker`".
*   Eles definem as **Variáveis**: "Passe a senha do Banco e a API Key da OpenAI para o script Python".

---

## 🏛️ Padrões de Design

PostgreSQL é a fonte da verdade.

*   `clients`: Tabela mestre. Cada linha é um SaaS Tenant.
*   `active_conversations`: Estado atual da conversa (State Machine).
*   `chat_messages`: Histórico de mensagens (Log).

> **Decisão de Design (ADR-001):** Configurações de ferramentas (ex: Calendar, CEP) são salvas em uma coluna `JSONB` chamada `tools_config` dentro da tabela `clients`. Isso permite flexibilidade sem migrations constantes.

> **Decisão de Design (ADR-002 - 2026-01):** Configurações de **provedores de comunicação** (Uazapi, LancePilot, Meta) foram movidas para a tabela `client_providers`. Isso permite múltiplas instâncias do mesmo provedor por cliente e separação clara de responsabilidades. Os workers usam sistema de fallback para retrocompatibilidade.

> **Decisão de Design (ADR-003 - 2026-02):** Métricas da IA usam arquitetura de **3 camadas**: Event Log (`conversation_events`) → Worker de Agregação (cron 5min) → Tabela Pré-calculada (`metrics_daily`). Isso garante leitura instantânea no dashboard (<50ms) independente do volume de dados, sem impactar a performance dos workers de ingest/RAG. Ver detalhes completos em `docs/database.md`.

## 🔄 Compatibilidade e Migração (Fallback Strategy)

Para garantir que clientes antigos continuem funcionando enquanto migramos para `client_providers`, o sistema implementa a seguinte lógica de prioridade na resolução de credenciais (ex: em `rag_worker.py`):

### Ordem de Resolução (Priority List):
1.  **Tabela `client_providers` (New):** O sistema busca primeiro por um registro ativo para o `provider_type` correspondente (uazapi, lancepilot, meta).
2.  **Configuração Legada (`clients` table):** Se não encontrar no provider, busca nas colunas antigas:
    *   **API URL:** `clients.api_url` ou `clients.tools_config['whatsapp']['url']`
    *   **Token/Key:** `clients.token` ou `clients.tools_config['whatsapp']['key']`

> **Nota:** O objetivo é depreciar as colunas `token`, `api_url` e `whatsapp_provider` da tabela `clients` após a migração completa de todos os tenants.

---

## 📊 Pipeline de Métricas (ADR-003)

O painel de métricas da IA opera com 3 camadas para performance em escala:

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Ingest / RAG  │────▶│  conversation_events  │────▶│  metrics_daily  │
│   Workers       │     │  (append-only log)    │     │  (pré-agregado) │
│                 │     │  ~0ms por INSERT      │     │                 │
└─────────────────┘     └──────────────────────┘     └────────┬────────┘
                               │                              │
                               │  metrics_worker (cron 5min)  │
                               └──────────────────────────────┘
                                                              │
                                                    ┌─────────▼─────────┐
                                                    │    Dashboard      │
                                                    │  (leitura <50ms)  │
                                                    └───────────────────┘
```

### Por que esta arquitetura?

| Alternativa | Escrita | Leitura Dashboard | Escala |
| :--- | :--- | :--- | :--- |
| Query ao vivo (full scan) | Nenhuma | Lenta | Ruim |
| Só event log | 1 INSERT | Média (agregação) | Boa |
| **Event log + agregação (escolhido)** | **1 INSERT** | **Instantânea** | **Excelente** |
| Time-series DB externo | Rápida | Rápida | Excelente (+ infra) |

A abordagem escolhida usa somente PostgreSQL (sem nova infra) e permite derivar qualquer métrica futura a partir do event log imutável.
