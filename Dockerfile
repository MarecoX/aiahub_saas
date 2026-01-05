FROM python:3.11-slim

WORKDIR /app


# Instala dependências do sistema para Mime Types (Fix HTML raw text)
RUN apt-get update && \
    apt-get install -y --no-install-recommends media-types && \
    rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia todo o código fonte
COPY . .

# Expose ports for both API and Streamlit
EXPOSE 8000
EXPOSE 8501

# Cria diretório de scripts para garantir permissões (opcional)
RUN mkdir -p scripts

