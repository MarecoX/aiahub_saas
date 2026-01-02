FROM python:3.11-slim

WORKDIR /app

# Copia e instala dependências
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Cria diretório de scripts para garantir permissões (opcional)
RUN mkdir -p Kestra/scripts
