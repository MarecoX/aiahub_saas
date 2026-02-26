from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import os
import logging

from api.routers import clients
from api.routers import forms
from api.routers import meta
from api.routers import providers

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API_Manager")

app = FastAPI(
    title="AIAHUB CONECT API",
    description="API para gerenciamento de clientes, tools (LancePilot/Uazapi) e arquivos RAG.",
    version="1.0.1",
)

# CORS (Permitir acesso de qualquer lugar por enquanto - Ajuste se tiver domínio específico)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Verifica se a API está online."""
    return {"status": "ok", "service": "AIAHUB Client Manager"}


@app.get("/politica-de-privacidade", response_class=HTMLResponse)
async def privacy_policy():
    """Retorna a página de Política de Privacidade para conformidade com o Facebook."""
    possible_paths = ["views/privacy_policy.html", "../views/privacy_policy.html"]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return "<h1>Política de Privacidade</h1><p>Documento não encontrado.</p>"


# Rotas
app.include_router(clients.router, prefix="/api/v1/clients", tags=["Clients"])
app.include_router(providers.router, prefix="/api/v1/clients/{token}/providers", tags=["Providers"])
app.include_router(meta.router, prefix="/api/v1/meta", tags=["Meta Webhooks"])
app.include_router(forms.router, prefix="/api/v1/forms", tags=["Forms"])


@app.get("/")
async def root():
    """Rota raiz para Health Check fácil (evita 404 no browser)."""
    return {"status": "online", "service": "AIAHUB CONECT API", "docs": "/docs"}
