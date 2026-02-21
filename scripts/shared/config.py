"""
Configurações compartilhadas para todos os workers.
Centraliza variáveis de ambiente usadas por Uazapi e LancePilot.
"""

import os

# Redis Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Buffer Configuration
BUFFER_KEY_SUFIX = os.getenv("BUFFER_KEY_SUFIX", "_buffer")
BUFFER_TTL = int(os.getenv("BUFFER_TTL", "300"))
DEBOUNCE_SECONDS = int(os.getenv("DEBOUNCE_SECONDS", "5"))

# Database (fallback if not set)
DATABASE_URL = os.getenv("DATABASE_CONNECTION_URI") or os.getenv("DATABASE_URL", "")

# LLM Providers
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
