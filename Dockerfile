# Build frontend
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/ .
RUN npm ci && npm run build

# Python backend + static files
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/
COPY VERSION .
COPY --from=frontend /build/dist /app/static

# Workload Identity Federation (Azure managed identity -> GCP) — no stored keys.
# az-token.py brokers an Entra MI token; google-auth exchanges it for short-lived
# GCP credentials via the external_account cred-config.
COPY az-token.py /app/az-token.py
COPY gcp-cred-config.json /app/gcp-cred-config.json
RUN chmod +x /app/az-token.py
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-cred-config.json
ENV GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES=1

ENV MODE=production
ENV PORT=8080

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8080"]
