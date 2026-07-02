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
# Auto-version: stamp the build time so the version moves on every build
RUN date -u +%Y.%m.%d.%H%M > VERSION
COPY --from=frontend /build/dist /app/static
COPY architecture/ /app/architecture

# Workload Identity Federation (Azure managed identity -> GCP) — no stored keys.
# az-token.py brokers an Entra MI token; google-auth exchanges it for short-lived
# GCP credentials via the external_account cred-config.
COPY az-token.py /app/az-token.py
RUN chmod +x /app/az-token.py
# The WIF trust-binding config is NOT baked into the image. It lives in Azure Key Vault
# and is mounted at runtime as a Container Apps secret volume; the deployment sets
# GOOGLE_APPLICATION_CREDENTIALS to the mounted path (/secrets/gcp-cred-config).
ENV GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES=1

ENV MODE=production
ENV PORT=8080

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "src.api.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
