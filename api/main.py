from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API_Manager")

app = FastAPI(
    title="AIAHUB Client Management API",
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


from api.routers import clients  # noqa: E402

app.include_router(clients.router)
