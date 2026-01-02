FROM python:3.11-slim

WORKDIR /app

# Install System Dependencies (if needed for psycopg)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Install Python Libs
# Adicione outros requirements se tiver (pandas, streamlit secrets fallback, etc)
RUN pip install fastapi uvicorn[standard] psycopg[binary] google-genai python-multipart requests python-dotenv

# Copy Application Code
# Assumindo que o build context é a raiz (onde está Kestra_2.0)
COPY Kestra_2.0 /app/Kestra_2.0

# Set Python Path to find 'scripts' and 'api'
ENV PYTHONPATH=/app/Kestra_2.0

# Expose Port
EXPOSE 8000

# Run Application
# O workdir é /app, então 'Kestra_2.0.api.main:app' ou muda workdir
WORKDIR /app/Kestra_2.0
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
