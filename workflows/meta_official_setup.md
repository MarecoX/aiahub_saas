---
description: Guia Definitivo de Integração e Aprovação Meta WhatsApp API
---
# Workflow de Integração Meta (Official WhatsApp API)

Este documento define o processo padrão (SOP) para conectar, verificar e aprovar o uso da API Oficial no AIAHUB CONECT.

## Fases do Ciclo de Vida

### 1. Preparação (Ambiente de Negócios)
Antes de qualquer código, o cliente precisa ter os ativos comerciais prontos.
- [ ] **BM (Business Manager)**: Criado e Verificado (Recomendado).
- [ ] **WABA (WhatsApp Business Account)**: Criada dentro da BM.
- [ ] **App Meta**: Tipo "Empresa" (Business), com produto "WhatsApp" adicionado.

### 2. Configuração Técnica (O "Tech Provider")
Configuração necessária para o AIAHUB (Você) atuar como provedor.
1.  **System User (Admin)**:
    - Criar "Usuário do Sistema" no BM do AIAHUB.
    - Função: `Admin`.
    - Gerar Token Permanente.
    - **Permissões Críticas**:
        - `whatsapp_business_management`
        - `whatsapp_business_messaging`
        - `business_management`

2.  **Configuração do App**:
    - **Webhook**: Url do AIAHUB (`https://api.aiahub.com.br/api/v1/meta/webhook`).
    - **Verify Token**: Um segredo fixo (ex: `aiahub_meta_secret_2026`).
    - **Campos Webhook**:
        - `messages` (Mandar/Receber zaps).
        - `message_template_status_update` (Aprovação de templates).

### 3. Integração no Sistema (Nosso Código)
A implementação segue o padrão modular do projeto (`scripts/meta`).

#### Módulo `scripts/meta/client.py`
Responsável pela comunicação com a Graph API.
- `send_message(waba_id, phone, token, content)`
- `get_templates(waba_id, token)`
- `create_template(...)`

#### Módulo `api/routers/meta.py`
Interface HTTP para receber eventos.
- `GET /webhook`: Valida o `hub.challenge` com o nosso `Verify Token`.
- `POST /webhook`: Recebe a mensagem, decodifica JSON e chama o Agente IA.

### 4. Processo de Aprovação (App Review)
Para sair do "Sandbox" e poder conectar números de terceiros (Clientes), o App precisa passar na revisão da Meta.

**Itens para Enviar:**
1.  **Permissão `whatsapp_business_messaging`**:
    - *Justificativa*: "O app permite que empresas respondam clientes de forma automatizada e centralizada."
    - *Evidência*: Screencast mostrando o recebimento de mensagem no Painel AIAHUB.
2.  **Permissão `whatsapp_business_management`**:
    - *Justificativa*: "Para sincronizar e listar templates de mensagens aprovados."
    - *Evidência*: Screencast da aba "Templates" mostrando a lista.

### 5. Go-Live (Produção)
Após aprovação:
1.  Cliente insere **BM ID**, **WABA ID** e **Token** no AIAHUB.
2.  Cliente cadastra **Forma de Pagamento** na BM dele (WhatsApp cobra por conversa).
3.  Número sai do status "Pendente" para "Conectado".

## Validação de Segurança
- [ ] O Token do Usuário do Sistema NUNCA deve ser exposto no Frontend.
- [ ] O Webhook deve validar a assinatura `X-Hub-Signature-256`.
