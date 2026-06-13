# GlassHood on Azure

Live, cross-cloud infrastructure monitoring running on **Azure Container Apps**, reading telemetry from a **Google Cloud** estate in real time — with **no stored credentials**, using **Workload Identity Federation**.

A portable deployment of GlassHood (a topology / observability tool) onto Azure that demonstrates a multi-cloud, security-first architecture: the Azure workload assumes a Google Cloud identity through federation, so there are **zero long-lived service-account keys anywhere** in the system.

## Architecture

```
   Azure                                            Google Cloud
 ┌───────────────────────────────┐               ┌──────────────────────────┐
 │ Azure Container App            │   federated   │ Cloud Logging            │
 │  • FastAPI + React (one image) │   identity    │ Cloud Monitoring         │
 │  • managed identity (Entra ID) │ ─────────────▶│ Compute / Asset / ...    │
 │  • token broker (az-token.py)  │  short-lived  │                          │
 │                                │  GCP tokens   │ (read-only, via a        │
 │                                │               │  federated SA — no keys) │
 └───────────────────────────────┘               └──────────────────────────┘
```

**The credential flow (no keys):**
1. The Container App runs with an Azure **managed identity** (Microsoft Entra ID).
2. `az-token.py` brokers an Entra token for the federated audience. (Azure Container Apps exposes its managed identity via `IDENTITY_ENDPOINT` — not the VM IMDS — so a small executable credential source bridges it to Google's client libraries.)
3. Google Cloud **Workload Identity Federation** exchanges that token at STS and impersonates a **read-only** service account.
4. The standard Google client libraries (Application Default Credentials) use the short-lived federated credentials — no key files, ever.

Why it matters: the target cloud's security posture *disables* service-account key creation. Rather than work around it, the design federates identity across clouds — the correct, key-less pattern for a regulated environment.

## Stack
- **Azure:** Container Apps, Container Registry, Microsoft Entra ID (managed identity), Workload Identity Federation
- **Google Cloud:** Cloud Logging / Monitoring / Compute / Asset Inventory (read-only)
- **App:** FastAPI (Python 3.11) + React (Vite), single container

## Layout
- `src/` — FastAPI backend (topology, log/metric collectors, auth)
- `frontend/` — React topology UI
- `az-token.py` — Workload Identity Federation token broker (Azure MI → GCP)
- `gcp-cred-config.example.json` — example external-account config (the real one is injected at deploy, never committed)
- `config/manifests/platform.yaml.example` — example topology manifest (the real one is deployment config, injected at runtime)
- `architecture-site/` — static architecture portal
- `Dockerfile` — multi-stage (Vite build → Python runtime)
- `docs/BACKLOG.md` — roadmap

## Configuration
All deployment-specific values — project identifiers, identities, endpoints, the topology manifest — are **externalized** and supplied at runtime via environment / secret store. Nothing infra-specific is hardcoded. The repo ships `.example` files; bring your own config.

## Roadmap (`docs/BACKLOG.md`)
- "Sign in with Microsoft" (Entra ID SSO)
- Config fully runtime-injected (generic, attestable image)
- Azure Confidential Computing + hardware-rooted attestation
- Lakehouse reporting (uptime / analytics) on Azure Databricks + Power BI

---
*A multi-cloud, key-less monitoring deployment, built as a reference architecture.*
