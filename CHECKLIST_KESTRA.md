# Checklist de Migração para Kestra

## 1. Infraestrutura Kestra
- [ ] Configurar `docker-compose.yml` para rodar o Kestra (Webserver, Scheduler, Executor, Postgres).
- [ ] Configurar persistência de arquivos (Local storage ou MinIO) para o RAG.

## 2. Adaptação dos Scripts Python
Os scripts atuais (FastAPI) rodam continuamente. No Kestra, eles serão executados sob demanda (Tasks).
- [ ] **Desacoplar `message_handler.py`**: Transformar em função ou script que aceita argumentos (JSON da mensagem) e retorna JSON processado.
- [ ] **Desacoplar `chains.py`**: Garantir que o Agent possa ser instanciado e rodado em uma execução única (stateless), carregando o vectorstore do disco a cada execução (ou usar serviço de Vector DB externo para performance).
- [ ] **Adaptar `message_buffer.py`**:
    - O modelo de `asyncio.sleep` (debounce) não escala bem em Jobs batch.
    - **Nova Lógica**: O Kestra recebe o Webhook -> Salva no Redis (List).
    - Um segundo Flow (ou o mesmo com delay) verifica se há mais mensagens antes de processar.

## 3. Criação dos Flows (Fluxos)
### Flow A: `receive-whatsapp`
- **Trigger**: Webhook (URL pública exposta para o Uazapi).
- **Tasks**:
    1. Recebe JSON do Uazapi.
    2. Executa Script Python (`handler.py`) para baixar mídia e extrair texto.
    3. Armazena a mensagem limpa no Redis (com carimbo de tempo).
    4. Opcional: Aciona o Flow B se não houver um rodando.

### Flow B: `process-conversation`
- **Trigger**: Agendado (curto prazo) ou Acionado pelo Flow A.
- **Tasks**:
    1. **Wait/Debounce**: Script Python verifica Redis. Se a última mensagem for muito recente (< 5s), encerra (espera o próximo ciclo) ou aguarda.
    2. **Agrupamento**: Lê todas as msgs do Redis para aquele `chat_id`.
    3. **RAG/IA**: Executa Script Python (`agent.py`) que carrega o contexto e gera resposta.
    4. **Envio**: Executa Script Python (`sender.py`) que manda volta pro Uazapi (com splitting).

## 4. Deploy e Teste
- [ ] Subir Kestra.
- [ ] Configurar Tunnel (Ngrok) para o Webhook do Kestra (já que Uazapi precisa bater numa URL pública).
- [ ] Testar fluxo completo.
