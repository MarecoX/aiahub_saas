# 🔧 Tools (Ferramentas da IA)

Documentação das ferramentas disponíveis para a IA utilizar durante as conversas.

## Compatibilidade por Provider

| Legenda | Significado |
|---------|-------------|
| 🟢 | Suporte completo |
| 🟡 | Suporte parcial (via Template ou com limitações) |
| 🔴 | Não disponível |

---

## Ferramentas Disponíveis

### 📋 Enviar Relatório
Envia dados coletados para um grupo de WhatsApp.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟡 Requer Template |
| Lancepilot | 🟡 Requer Template |

**Campos configuráveis:**
- `grupo_id`: ID do grupo destino
- `template`: Formato customizado da mensagem
- `instructions`: Quando a IA deve enviar

---

### 🧑‍💼 Atendimento Humano
Pausa a IA e transfere para atendimento humano.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟢 Completo |
| Lancepilot | 🟢 Completo |

**Campos configuráveis:**
- `timeout_minutes`: Duração do modo humano (5-1440 min)
- `instructions`: Quando ativar o atendimento humano

---

### 🛑 Desativar IA (Opt-out)
Desativa a IA permanentemente para o cliente.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo (com auto-detect de triggers) |
| Meta | 🟡 Parcial (sem auto-detect) |
| Lancepilot | 🟡 Parcial (sem auto-detect) |

**Campos configuráveis:**
- `instructions`: Gatilhos de parada (emojis, hashtags, frases)

**Auto-detect (Uazapi):** Detecta automaticamente #desativar, #parar, e emojis configurados sem depender da IA.

---

### 📅 Criar Lembrete
Agenda um lembrete para retornar contato com o cliente.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟡 Via Template (fora de 24h) |
| Lancepilot | 🟡 Via Template (fora de 24h) |

**Frases reconhecidas:**
- "amanhã", "depois de amanhã"
- "semana que vem", "próxima semana"
- "em 3 dias", "em 5 horas"
- "dia 15", "2026-02-10 10:00"

**Funcionamento:**
1. IA detecta intenção de follow-up
2. Salva lembrete no banco de dados
3. Job verifica lembretes a cada 5 minutos
4. Antes de enviar, IA analisa contexto para evitar mensagens desnecessárias

---

### 🌐 Consultar Viabilidade HubSoft
Verifica cobertura de internet em um endereço.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟢 Completo |
| Lancepilot | 🟢 Completo |

**Campos configuráveis:**
- `api_url`: URL da API HubSoft
- `client_id`, `client_secret`: Credenciais OAuth
- `username`, `password`: Login HubSoft
- `raio`: Raio de busca em metros (padrão: 250)

---

### 📍 Consultar CEP
Busca informações de um CEP brasileiro.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟢 Completo |
| Lancepilot | 🟢 Completo |

**Sem configuração necessária.**

---

### 🎙️ Enviar Áudio
Envia arquivo de áudio por URL.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🔴 Não disponível |
| Lancepilot | 🔴 Não disponível |

**Uso:** Inclua URL de áudio (.mp3, .ogg, .wav) no prompt ou resposta da IA.

### 📚 Base de Conhecimento (RAG)
Permite que a IA consulte documentos empresariais (PDFs, Manuais) antes de responder.

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟢 Completo |
| Lancepilot | 🟢 Completo |

**Configuração:**
- `rag_active` (bool): Ativa/Desativa a consulta aos documentos.
- `store_id`: ID do Vector Store (definido no cadastro do cliente).

**Funcionamento:**
- A tool `consultar_documentos_empresa` é injetada dinamicamente se `rag_active` for `True` e houver um `store_id`.
- A IA decide sozinha quando consultar os documentos (ex: dúvidas sobre regras, preços, manuais).

---

### 🌐 SGP (Provedores de Internet)
Integração completa com sistemas de gestão de provedores (SGP).

| Provider | Status |
|----------|--------|
| Uazapi | 🟢 Completo |
| Meta | 🟢 Completo |
| Lancepilot | 🟢 Completo |

**Funcionalidades:**
- **Viabilidade Técnica**: Consulta cobertura por CEP/Endereço.
- **Pré-Cadastro**: Cria cadastro de interessados automaticamente.
- **Planos**: Consulta planos disponíveis na região.

**Campos configuráveis:**
- `sgp_url`: URL do sistema SGP.
- `sgp_token`: Token de API.
- `sgp_app`: Nome do aplicativo de integração.

---

## Arquitetura de Tools

```
scripts/shared/tools_library.py
├── Definição das ferramentas (@tool)
├── AVAILABLE_TOOLS (registro central de funções)
├── get_enabled_tools()
│   ├── Carrega configs do JSON (client_config)
│   ├── Injeta dependências (URL, Token, IDs) via Wrappers
│   └── Injeta RAG dinamicamente (rag_active)
└── Helper Functions (validadores, formatadores)
```

## Adicionando Nova Tool

1. Crie a função em `tools_library.py` com decorator `@tool`
2. Adicione ao `AVAILABLE_TOOLS`
3. Crie wrapper de injeção em `get_enabled_tools()` se precisar de params dinâmicos
4. Adicione UI em `views/client_dashboard/tabs/tools_tab.py`
5. Adicione save na função `save_tools_config()`
