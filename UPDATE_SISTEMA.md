# 🚀 Atualização do Sistema - Kestra SaaS 2.0
Data: 23/05/2024
Autor: Kestra Assistant

Esta atualização focou em **Segurança**, **Controle de Comportamento** e **Observabilidade (Debug)**.

---

## 1. 📱 WhatsApp Avançado (Nova Seção no Dashboard)

As configurações do WhatsApp foram unificadas na aba **Ferramentas (`tools_tab.py`)** sob a seção **"WhatsApp Avançado"**.

### A. Modo Humanizado (Split Logic)
Controla como o robô envia mensagens longas.
- **✅ Ativado:** O robô "picota" o texto. Envia uma mensagem para cada parágrafo (separado por `\n\n`). Dá a sensação de alguém digitando várias frases.
- **ℹ️ Desativado (Padrão):** O robô agrupa o texto. Mantém listas e quebras de linha simples (`\n`) dentro do mesmo balão. Evita "spam" de notificações.

### B. Segurança e Controle (Listas)
Proteção para garantir que o robô só fale com quem deve.
- **✅ Whitelist (Permitidos):** Se você colocar números aqui (ex: `5511999999999`), o robô **ignorará todo o resto do mundo**. Só responde a estes. Útil para testes ou bots privados.
- **🚫 Blocklist (Bloqueados):** Números aqui são ignorados sumariamente. O robô nem gasta tokens de IA com eles.

### C. Reações e Interatividade
- Configuração para o robô reagir com emojis (👍, ❤️, 😂) às mensagens do cliente, com instruções personalizáveis.

---

## 2. 🐞 Sistema de Logs de Erro (Caixa Preta)

Foi implementado um sistema robusto de rastreamento de falhas para facilitar o debug, especialmente de problemas "misteriosos" como estouro de memória.

### Componentes:
1.  **Banco de Dados (`error_logs`):** Tabela criada automaticamente para persistir erros.
    - Colunas: `Timestamp`, `Source` (Origem), `Error Type`, `Traceback`, `Client ID`, `Chat ID`, `Memory Usage` (RAM).
2.  **Backend (O Espião):**
    - `rag_worker.py`: Instrumentado para capturar crashes durante a geração de IA.
    - `whatsapp_sender.py`: Instrumentado para capturar erros de envio ou parse de mensagens.
    - **Monitor de Memória:** Tenta registrar quanto de RAM o processo estava usando no momento do erro.
3.  **Frontend (O Vizualizador):**
    - Nova aba **"🐞 Logs de Erro"** em **Monitoramento (`monitoring_tab.py`)**.
    - Mostra os últimos 50 erros com detalhes expansíveis.

---

## 📁 Arquivos Modificados
- `views/client_dashboard/tabs/tools_tab.py`: UI Refatorada (WhatsApp Avançado).
- `views/client_dashboard/tabs/monitoring_tab.py`: Nova aba de Logs.
- `scripts/shared/saas_db.py`: Função `log_error` e `init_error_log_table`.
- `scripts/uazapi/rag_worker.py`: Catch + Log Error.
- `scripts/uazapi/whatsapp_sender.py`: Catch + Log Error (Wrapper Seguro).
