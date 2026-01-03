FROM python:3.11-slim

WORKDIR /app


# Copia e instala dependências
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

