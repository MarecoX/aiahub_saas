# Kestra 2.0 Docs 🚀

Bem-vindo à documentação técnica do **Kestra 2.0**, a plataforma SaaS de automação de WhatsApp e IA.

## Visão Geral
Este projeto é um **Modular Monolith** construído sobre:
*   [FastAPI](https://fastapi.tiangolo.com/): Backend e API REST.
*   [Streamlit](https://streamlit.io/): Frontend e Dashboard do Cliente.
*   PostgreSQL: Banco de Dados Relacional.
*   LangChain/LangGraph: Orquestração de IA.

## Guia Rápido

### Rodando Localmente
```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Rodar API
python -m uvicorn app:app --reload

# 3. Rodar Dashboard
streamlit run admin_dashboard.py
```

### Estrutura
*   `/api`: Endpoints REST e Lógica de Serviço.
*   `/scripts`: Workers de segundo plano (Follow-up, Meta, LancePilot).
*   `/views`: Frontend Streamlit.
*   `/shared`: Bibliotecas compartilhadas (DB, Utils).
