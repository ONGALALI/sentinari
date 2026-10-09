# Sentinari Cloud Deployment Container (Python 3.12 / Linux)
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8099

WORKDIR /app

# Install system dependencies (Poppler for PDF ingestion, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install core runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir psycopg2-binary numpy

# Copy application source
COPY app/ ./app/
COPY config/ ./config/
COPY sentinel/ ./sentinel/
COPY templates/ ./templates/
COPY run_smi.py .

EXPOSE 8099

# Run via uvicorn (binds to 0.0.0.0 and dynamically reads PORT from environment)
CMD ["python", "run_smi.py", "serve", "--host", "0.0.0.0"]
