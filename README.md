# 🏭 Kestra SaaS Application

Este é o Backoffice SaaS da Kestra AI, uma plataforma multi-tenant integrando Streamlit, Postgres e Google Gemini (RAG).

## 🚀 Funcionalidades

- **Multi-tenancy Total**: Login separado para Admin e Clientes.
- **RAG (Knowledge Base)**: Upload e gestão de arquivos para Gemini File Search.
- **Simulador de Chat**: Teste de prompts e respostas em tempo real.
- **Gestão de Clientes**: CRUD completo de configurações e tokens.

## 🛠️ Instalação Local

1. Clone o repositório.
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Crie um arquivo `.env` na raiz com as chaves:
   ```env
   DATABASE_CONNECTION_URI=postgresql://user:pass@host:port/db
   GEMINI_API_KEY=seu_api_key
   ```
4. Execute a aplicação:
   ```bash
   streamlit run app.py
   ```

## ☁️ Deploy no Streamlit Cloud

1. Suba este repositório no GitHub.
2. conecte no [share.streamlit.io](https://share.streamlit.io).
3. Selecione o repo e o arquivo `app.py`.
4. Em "Advanced Settings" -> "Secrets", adicione o conteúdo do seu `.env` (formato TOML):
   ```toml
   DATABASE_CONNECTION_URI = "sua_string_conexao"
   GEMINI_API_KEY = "sua_key"
   ```

---
Powered by Kestra AI
