# File: src/api/routes/demo_data.py
# Purpose: Static demo topology data — curated for sales presentations
# Separate from router so data can grow without bloating the route file.

_TS = "2026-02-26T10:00:00Z"

DEMO_NODES = [
    {
        "id": "lb",
        "label": "Cloud Armor / LB",
        "type": "lb",
        "status": "healthy",
        "icon": "shield",
        "metrics": {
            "latency_ms": 42,
            "requests_1h": 1847,
            "ip": "34.8.142.111",
            "waf_rules": 23,
            "blocked_1h": 7,
        },
        "diagnostics": (
            "[2026-02-26T09:59:58Z] Health check: backend-service-coldvault → HEALTHY\n"
            "[2026-02-26T09:59:58Z] Active backends: 3/3 (europe-west6-a, europe-west6-b, europe-west6-c)\n"
            "[2026-02-26T09:59:58Z] Cloud Armor policy: cv-waf-policy (23 rules active)\n"
            "[2026-02-26T09:59:58Z] DDoS protection: Google Cloud Armor Managed Protection Plus\n"
            "[2026-02-26T09:59:58Z] SSL: TLS 1.3, cert expires 2026-05-27\n"
            "[2026-02-26T10:00:00Z] p50 latency: 42ms, p99: 189ms — within SLA"
        ),
        "last_checked": _TS,
    },
    {
        "id": "nginx",
        "label": "nginx",
        "type": "nginx",
        "status": "healthy",
        "icon": "globe",
        "metrics": {
            "active_connections": 12,
            "requests_per_sec": 8.3,
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] nginx/1.25.4 — status: active\n"
            "[2026-02-26T10:00:00Z] Worker processes: 4, connections: 12/1024\n"
            "[2026-02-26T10:00:00Z] Upstream: fastapi-app (3 servers), all up\n"
            "[2026-02-26T10:00:00Z] Rate limiting: 100 req/s per IP, 0 rejected last 5m\n"
            "[2026-02-26T10:00:00Z] SSL termination: handled by LB (passthrough mode)"
        ),
        "last_checked": _TS,
    },
        {
        "id": "mig",
        "label": "MIG Autoscaler",
        "type": "mig",
        "status": "disabled",
        "icon": "layers",
        "metrics": {
            "min_instances": "-",
            "max_instances": "-",
            "current_instances": 0,
            "scaling_policy": "Not configured",
            "note": "Planned — Confidential VMs require manual scaling",
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] MIG Autoscaler: NOT CONFIGURED\n"
            "[2026-02-26T10:00:00Z] Reason: Confidential VMs (SEV-SNP) use static instance group\n"
            "[2026-02-26T10:00:00Z] Current: nginx proxies directly to VM instances\n"
            "[2026-02-26T10:00:00Z] Planned: MIG with health-check-based autoscaling\n"
            "[2026-02-26T10:00:00Z] Blocker: MIG template needs SEV-SNP + attestation boot script\n"
            "[2026-02-26T10:00:00Z] Status: DISABLED — manual VM management via gcloud"
        ),
        "last_checked": _TS,
    },
{
        "id": "vm1",
        "label": "ColdVault VM-1",
        "type": "vm",
        "status": "healthy",
        "icon": "server",
        "metrics": {
            "ram_percent": 42.1,
            "cpu_percent": 38.5,
            "disk_percent": 31.2,
            "uptime_s": 432000,
            "version": "v2026-02-26.1",
            "confidential": "AMD SEV-SNP",
            "attestation": "verified",
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] VM: n2d-highmem-8, AMD EPYC Milan, SEV-SNP enabled\n"
            "[2026-02-26T10:00:00Z] Attestation: AMD SEV-SNP report verified (nonce: 0x7f3a...)\n"
            "[2026-02-26T10:00:00Z] Uptime: 5 days 0h — last restart: scheduled maintenance\n"
            "[2026-02-26T10:00:00Z] Docker: coldvault:v2026-02-26.1 running, health: OK\n"
            "[2026-02-26T10:00:00Z] Memory: 33.7 GB / 80 GB (42.1%), no swap\n"
            "[2026-02-26T10:00:00Z] Disk: /data/vault 31.2% used (encrypted at rest)"
        ),
        "last_checked": _TS,
    },
    {
        "id": "vm2",
        "label": "ColdVault VM-2",
        "type": "vm",
        "status": "healthy",
        "icon": "server",
        "metrics": {
            "ram_percent": 37.8,
            "cpu_percent": 29.1,
            "disk_percent": 28.4,
            "uptime_s": 259200,
            "version": "v2026-02-26.1",
            "confidential": "AMD SEV-SNP",
            "attestation": "verified",
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] VM: n2d-highmem-8, AMD EPYC Milan, SEV-SNP enabled\n"
            "[2026-02-26T10:00:00Z] Attestation: AMD SEV-SNP report verified (nonce: 0x2b8c...)\n"
            "[2026-02-26T10:00:00Z] Uptime: 3 days 0h\n"
            "[2026-02-26T10:00:00Z] Docker: coldvault:v2026-02-26.1 running, health: OK\n"
            "[2026-02-26T10:00:00Z] Memory: 30.2 GB / 80 GB (37.8%), no swap\n"
            "[2026-02-26T10:00:00Z] Disk: /data/vault 28.4% used (encrypted at rest)"
        ),
        "last_checked": _TS,
    },
    {
        "id": "vm3",
        "label": "ColdVault VM-3",
        "type": "vm",
        "status": "healthy",
        "icon": "server",
        "metrics": {
            "ram_percent": 15.2,
            "cpu_percent": 12.0,
            "disk_percent": 22.1,
            "uptime_s": 720,
            "version": "v2026-02-26.1",
            "confidential": "AMD SEV-SNP",
            "attestation": "verified",
            "note": "Recently scaled up",
        },
        "diagnostics": (
            "[2026-02-26T09:48:42Z] Instance created by MIG autoscaler\n"
            "[2026-02-26T09:48:45Z] SEV-SNP attestation: generating report...\n"
            "[2026-02-26T09:48:48Z] Attestation VERIFIED (nonce: 0x9d1f...)\n"
            "[2026-02-26T09:49:00Z] Docker pull coldvault:v2026-02-26.1 — complete\n"
            "[2026-02-26T09:49:05Z] Container started, warming up...\n"
            "[2026-02-26T09:49:12Z] Health check PASSED\n"
            "[2026-02-26T10:00:00Z] Uptime: 12 min — FAISS stores loading from Cloud SQL"
        ),
        "last_checked": _TS,
    },
    {
        "id": "faiss",
        "label": "FAISS RAG",
        "type": "rag",
        "status": "healthy",
        "icon": "database",
        "metrics": {
            "active_stores": 47,
            "total_vectors": 284103,
            "dirty_stores": 2,
            "index_type": "IVF-HNSW",
            "encryption": "AES-256-GCM at rest",
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] FAISS RAG service: healthy\n"
            "[2026-02-26T10:00:00Z] Active stores: 47 (47 users with RAG enabled)\n"
            "[2026-02-26T10:00:00Z] Total vectors: 284,103 across all stores\n"
            "[2026-02-26T10:00:00Z] Dirty stores: 2 (pending flush to Cloud SQL)\n"
            "[2026-02-26T10:00:00Z] Index type: IVF-HNSW, dims: 1024 (bge-m3)\n"
            "[2026-02-26T10:00:00Z] All stores encrypted: AES-256-GCM at rest\n"
            "[2026-02-26T10:00:00Z] Last periodic flush: 2 min ago (0 errors)"
        ),
        "last_checked": _TS,
    },
    {
        "id": "cloudsql",
        "label": "Cloud SQL",
        "type": "db",
        "status": "healthy",
        "icon": "database",
        "metrics": {
            "pool_size": 15,
            "pool_checked_out": 4,
            "replication_lag_ms": 12,
            "connections_active": 4,
            "storage_gb": 24.7,
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] PostgreSQL 15.4 — Cloud SQL (db-custom-4-16384)\n"
            "[2026-02-26T10:00:00Z] Connection pool: 4/15 active, 0 overflow\n"
            "[2026-02-26T10:00:00Z] Replication: async standby, lag 12ms\n"
            "[2026-02-26T10:00:00Z] Storage: 24.7 GB / 100 GB (auto-resize enabled)\n"
            "[2026-02-26T10:00:00Z] Backups: daily at 02:00 UTC, last: SUCCESS\n"
            "[2026-02-26T10:00:00Z] SSL: required, server cert valid until 2027-01-15"
        ),
        "last_checked": _TS,
    },
    {
        "id": "embeddings",
        "label": "Embeddings",
        "type": "embeddings",
        "status": "healthy",
        "icon": "fingerprint",
        "metrics": {
            "model": "BAAI/bge-m3",
            "dims": 1024,
            "on_vm": True,
            "note": "Local \u2014 zero data leakage",
        },
        "diagnostics": (
            "[2026-02-26T10:00:00Z] Model: BAAI/bge-m3 (1024 dims)\n"
            "[2026-02-26T10:00:00Z] Runtime: ONNX on CPU (AMD EPYC Milan)\n"
            "[2026-02-26T10:00:00Z] Avg latency: 23ms per embedding (single doc)\n"
            "[2026-02-26T10:00:00Z] Batch latency: 142ms per 50 docs\n"
            "[2026-02-26T10:00:00Z] Runs ON-VM \u2014 text never leaves Confidential VM\n"
            "[2026-02-26T10:00:00Z] Memory footprint: 1.2 GB (shared across VMs)"
        ),
        "last_checked": _TS,
    },
    # --- Auth0 ---
    {
        "id": "auth0",
        "label": "Auth0",
        "type": "auth",
        "status": "healthy",
        "icon": "lock",
        "metrics": {"tenant": "dev-lyl7xbutt77zddl7", "logins_1h": 23, "mfa_rate": "94%"},
        "diagnostics": (
            "[2026-02-26T10:00:00Z] Auth0 tenant: dev-lyl7xbutt77zddl7\n"
            "[2026-02-26T10:00:00Z] Custom domain: auth.9robots.ai — ACTIVE\n"
            "[2026-02-26T10:00:00Z] Logins last 1h: 23 (0 failures)\n"
            "[2026-02-26T10:00:00Z] MFA adoption: 94% of active users\n"
            "[2026-02-26T10:00:00Z] Token TTL: access 3600s, refresh 86400s"
        ),
        "last_checked": _TS,
    },
    # --- LLM API Router ---
    {
        "id": "llm_router",
        "label": "API Router",
        "type": "router",
        "status": "healthy",
        "icon": "git-branch",
        "metrics": {"total_calls_1h": 841, "avg_latency_ms": 1840, "cost_1h_usd": 2.83, "models": "20 (16 API + 4 self-hosted)"},
        "diagnostics": (
            "[2026-02-26T10:00:00Z] Model router: 20 models (16 API + 4 self-hosted vLLM)\n"
            "[2026-02-26T10:00:00Z] Routing: user-selected + debate + fallback chain\n"
            "[2026-02-26T10:00:00Z] Active fallbacks: grok-4 \u2192 claude-sonnet-4.5\n"
            "[2026-02-26T10:00:00Z] API calls: 405/h ($2.83) | Self-hosted: 436/h ($0)\n"
            "[2026-02-26T10:00:00Z] Circuit breakers: 1 OPEN (grok-4)"
        ),
        "last_checked": _TS,
    },
    # --- Individual LLM nodes (real ColdVault config) ---
    # Gemini (Vertex AI)
    {
        "id": "gemini_3_flash", "label": "Gemini 3 Flash", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "global", "calls_1h": 89, "latency_ms": 340, "cost_1h": "$0.05"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI global: OK\n[2026-02-26T10:00:00Z] Model: gemini-3-flash-preview, p50: 340ms, p99: 890ms\n[2026-02-26T10:00:00Z] 89 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    {
        "id": "gemini_3_pro", "label": "Gemini 3 Pro", "type": "llm",
        "status": "degraded", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "europe-west6", "calls_1h": 34, "latency_ms": 3800, "cost_1h": "$1.42", "note": "Regional latency spike"},
        "diagnostics": (
            "[2026-02-26T09:58:01Z] Vertex AI europe-west6: latency spike detected\n"
            "[2026-02-26T09:58:01Z] p50: 3800ms (normal: 580ms), p99: 8420ms (normal: 1200ms)\n"
            "[2026-02-26T09:58:01Z] Google Cloud Status: europe-west6 \u2014 Elevated error rates\n"
            "[2026-02-26T09:58:01Z] Incident ID: GCP-eu6-vertex-20260226\n"
            "[2026-02-26T09:58:01Z] Mitigation: failover to us-central1 active\n"
            "[2026-02-26T09:58:01Z] Current routing: 60% us-central1, 40% europe-west6\n"
            "[2026-02-26T10:00:00Z] Status: DEGRADED \u2014 monitoring recovery"
        ),
        "last_checked": _TS,
    },
    # Claude (Vertex AI)
    {
        "id": "claude_opus_45", "label": "Claude Opus 4.5", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-east5", "calls_1h": 5, "latency_ms": 4200, "cost_1h": "$0.38"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-east5: OK\n[2026-02-26T10:00:00Z] Model: claude-opus-4-5@20251101, p50: 4200ms\n[2026-02-26T10:00:00Z] 5 calls last 1h (premium tier only), 0 errors",
        "last_checked": _TS,
    },
    {
        "id": "claude_sonnet_45", "label": "Claude Sonnet 4.5", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "global", "calls_1h": 67, "latency_ms": 1240, "cost_1h": "$1.01"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI global: OK\n[2026-02-26T10:00:00Z] Model: claude-sonnet-4-5@20250929, p50: 1240ms\n[2026-02-26T10:00:00Z] 67 calls last 1h (incl. grok-4 fallback traffic), 0 errors",
        "last_checked": _TS,
    },
    {
        "id": "claude_haiku_45", "label": "Claude Haiku 4.5", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-east5", "calls_1h": 41, "latency_ms": 380, "cost_1h": "$0.21"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-east5: OK\n[2026-02-26T10:00:00Z] Model: claude-haiku-4-5@20251001, p50: 380ms\n[2026-02-26T10:00:00Z] 41 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # OpenAI (direct API)
    {
        "id": "gpt52", "label": "GPT-5.2", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "OpenAI (direct)", "calls_1h": 38, "latency_ms": 950, "cost_1h": "$0.53"},
        "diagnostics": "[2026-02-26T10:00:00Z] OpenAI API (direct key): OK\n[2026-02-26T10:00:00Z] Model: gpt-5.2, p50: 950ms, p99: 2400ms\n[2026-02-26T10:00:00Z] 38 calls last 1h, 0 errors, rate limit: 8% used",
        "last_checked": _TS,
    },
    {
        "id": "gpt5_mini", "label": "GPT-5 Mini", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "OpenAI (direct)", "calls_1h": 32, "latency_ms": 420, "cost_1h": "$0.06"},
        "diagnostics": "[2026-02-26T10:00:00Z] OpenAI API (direct key): OK\n[2026-02-26T10:00:00Z] Model: gpt-5-mini, p50: 420ms, p99: 980ms\n[2026-02-26T10:00:00Z] 32 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # Grok (xAI direct API)
    {
        "id": "grok4", "label": "Grok 4", "type": "llm",
        "status": "error", "icon": "brain",
        "metrics": {"provider": "xAI (direct)", "calls_1h": 0, "latency_ms": None, "cost_1h": "$0.00", "note": "CIRCUIT BREAKER OPEN"},
        "diagnostics": (
            "[2026-02-26T09:47:12Z] POST https://api.x.ai/v1/chat/completions\n"
            "[2026-02-26T09:47:12Z] HTTP 503 Service Unavailable\n"
            "[2026-02-26T09:47:12Z] {\"error\":{\"message\":\"Service temporarily unavailable\"}}\n"
            "[2026-02-26T09:47:12Z] Retry 1/3 after 2s backoff...\n"
            "[2026-02-26T09:47:14Z] HTTP 503 Service Unavailable\n"
            "[2026-02-26T09:47:14Z] Retry 2/3 after 4s backoff...\n"
            "[2026-02-26T09:47:18Z] HTTP 503 Service Unavailable\n"
            "[2026-02-26T09:47:18Z] Circuit breaker OPEN \u2014 grok-4 marked unavailable\n"
            "[2026-02-26T09:47:18Z] Fallback: routing to claude-sonnet-4.5\n"
            "[2026-02-26T09:52:18Z] Health check: still 503. Next retry in 5m.\n"
            "[2026-02-26T09:57:18Z] Health check: still 503. Next retry in 5m.\n"
            "[2026-02-26T10:02:18Z] Health check: still 503. xAI status page: investigating."
        ),
        "last_checked": _TS,
    },
    {
        "id": "grok_fast", "label": "Grok Fast", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "xAI (direct)", "calls_1h": 22, "latency_ms": 580, "cost_1h": "$0.11"},
        "diagnostics": "[2026-02-26T10:00:00Z] xAI API (direct key): OK\n[2026-02-26T10:00:00Z] Model: grok-4-fast-reasoning, p50: 580ms\n[2026-02-26T10:00:00Z] 22 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # Qwen (Vertex AI)
    {
        "id": "qwen3_235b", "label": "Qwen3 235B", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-south1", "calls_1h": 18, "latency_ms": 2800, "cost_1h": "$0.02"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-south1: OK\n[2026-02-26T10:00:00Z] Model: qwen3-235b-a22b-instruct, p50: 2800ms\n[2026-02-26T10:00:00Z] 18 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    {
        "id": "qwen3_next", "label": "Qwen3-Next", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "global", "calls_1h": 12, "latency_ms": 1100, "cost_1h": "$0.01"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI global: OK\n[2026-02-26T10:00:00Z] Model: qwen3-next-80b-a3b-instruct, p50: 1100ms\n[2026-02-26T10:00:00Z] 12 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    {
        "id": "qwen3_coder", "label": "Qwen3 Coder 480B", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-south1", "calls_1h": 15, "latency_ms": 3200, "cost_1h": "$0.02"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-south1: OK\n[2026-02-26T10:00:00Z] Model: qwen3-coder-480b-a35b-instruct, p50: 3200ms\n[2026-02-26T10:00:00Z] 15 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # Llama (Vertex AI)
    {
        "id": "llama4_maverick", "label": "Llama 4 Maverick", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-east5", "calls_1h": 14, "latency_ms": 890, "cost_1h": "$0.01"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-east5: OK\n[2026-02-26T10:00:00Z] Model: llama-4-maverick-17b-128e-instruct, p50: 890ms\n[2026-02-26T10:00:00Z] 14 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    {
        "id": "llama4_scout", "label": "Llama 4 Scout", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-east5", "calls_1h": 8, "latency_ms": 720, "cost_1h": "$0.00"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-east5: OK\n[2026-02-26T10:00:00Z] Model: llama-4-scout-17b-16e-instruct, p50: 720ms\n[2026-02-26T10:00:00Z] 8 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # Mistral (Vertex AI)
    {
        "id": "mistral_medium3", "label": "Mistral Medium 3", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "us-central1", "calls_1h": 7, "latency_ms": 1100, "cost_1h": "$0.01"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI us-central1: OK\n[2026-02-26T10:00:00Z] Model: mistral-medium-3, p50: 1100ms\n[2026-02-26T10:00:00Z] 7 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # MiniMax (Vertex AI)
    {
        "id": "minimax_m2", "label": "MiniMax M2", "type": "llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"provider": "Vertex AI", "region": "europe-west6", "calls_1h": 3, "latency_ms": 1600, "cost_1h": "$0.00"},
        "diagnostics": "[2026-02-26T10:00:00Z] Vertex AI europe-west6: OK\n[2026-02-26T10:00:00Z] Model: minimax-m2, p50: 1600ms\n[2026-02-26T10:00:00Z] 3 calls last 1h, 0 errors",
        "last_checked": _TS,
    },
    # --- Self-hosted Models (vLLM on 8x H200, a3-ultragpu-8g) ---
    {
        "id": "model_glm47_flash", "label": "GLM-4.7-Flash", "type": "self_hosted_llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"params": "30B", "quant": "FP8", "vram_gb": 30, "tp": 1, "gpus": "H200 #0", "reqs_1h": 142, "latency_ms": 280, "queue": 0},
        "diagnostics": (
            "[2026-02-26T10:00:00Z] vLLM v0.7.3 serving GLM-4.7-Flash (30B FP8)\n"
            "[2026-02-26T10:00:00Z] Tensor parallel: 1 (GPU 0), VRAM: 30/141 GB\n"
            "[2026-02-26T10:00:00Z] Role: debate aggregation (randomly assigned)\n"
            "[2026-02-26T10:00:00Z] Requests last 1h: 142, p50: 280ms, p99: 720ms\n"
            "[2026-02-26T10:00:00Z] KV cache: 45 GB allocated, 12% utilization\n"
            "[2026-02-26T10:00:00Z] Encrypted: AMD SEV-SNP VM + NVIDIA CC GPU"
        ),
        "last_checked": _TS,
    },
    {
        "id": "model_ministral3", "label": "Ministral 3 14B", "type": "self_hosted_llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"params": "14B", "quant": "FP8", "vram_gb": 14, "tp": 1, "gpus": "H200 #0", "reqs_1h": 138, "latency_ms": 190, "queue": 0},
        "diagnostics": (
            "[2026-02-26T10:00:00Z] vLLM v0.7.3 serving Ministral-3-14B (FP8)\n"
            "[2026-02-26T10:00:00Z] Tensor parallel: 1 (GPU 0, shared), VRAM: 14/141 GB\n"
            "[2026-02-26T10:00:00Z] Role: debate aggregation (randomly assigned)\n"
            "[2026-02-26T10:00:00Z] Requests last 1h: 138, p50: 190ms, p99: 510ms\n"
            "[2026-02-26T10:00:00Z] KV cache: 40 GB allocated, 9% utilization\n"
            "[2026-02-26T10:00:00Z] Encrypted: AMD SEV-SNP VM + NVIDIA CC GPU"
        ),
        "last_checked": _TS,
    },
    {
        "id": "model_qwen35", "label": "Qwen3.5-397B", "type": "self_hosted_llm",
        "status": "healthy", "icon": "brain",
        "metrics": {"params": "397B", "quant": "FP8", "vram_gb": 400, "tp": 4, "gpus": "H200 #1-#4", "reqs_1h": 89, "latency_ms": 3200, "queue": 1, "gpqa": "88.4%"},
        "diagnostics": (
            "[2026-02-26T10:00:00Z] vLLM v0.7.3 serving Qwen3.5-397B (FP8)\n"
            "[2026-02-26T10:00:00Z] Tensor parallel: 4 (GPUs 1-4), VRAM: 400/564 GB\n"
            "[2026-02-26T10:00:00Z] GPQA: 88.4% \u2014 frontier-class reasoning\n"
            "[2026-02-26T10:00:00Z] Requests last 1h: 89 (debate participant)\n"
            "[2026-02-26T10:00:00Z] p50: 3200ms, p99: 8100ms \u2014 thinking model\n"
            "[2026-02-26T10:00:00Z] KV cache: 120 GB allocated, 34% utilization\n"
            "[2026-02-26T10:00:00Z] Encrypted: AMD SEV-SNP VM + NVIDIA CC GPU"
        ),
        "last_checked": _TS,
    },
    {
        "id": "model_glm5", "label": "GLM-5-744B", "type": "self_hosted_llm",
        "status": "degraded", "icon": "brain",
        "metrics": {"params": "744B", "quant": "FP4", "vram_gb": 372, "tp": 3, "gpus": "H200 #5-#7", "reqs_1h": 67, "latency_ms": 5400, "queue": 3, "gpqa": "80.2%", "note": "GPU #5 thermal throttle"},
        "diagnostics": (
            "[2026-02-26T09:54:00Z] vLLM v0.7.3 serving GLM-5-744B (FP4)\n"
            "[2026-02-26T09:54:00Z] Tensor parallel: 3 (GPUs 5-7), VRAM: 372/423 GB\n"
            "[2026-02-26T09:55:12Z] WARN: GPU #5 temp 87\u00b0C (threshold: 83\u00b0C)\n"
            "[2026-02-26T09:55:12Z] GPU #5 clock throttled: 1980\u21921620 MHz (-18%)\n"
            "[2026-02-26T09:55:12Z] Impact: TP shard 0 slower, p99 latency +40%\n"
            "[2026-02-26T10:00:00Z] Queue depth: 3 (backing up due to throttle)\n"
            "[2026-02-26T10:00:00Z] Status: DEGRADED \u2014 thermal management active"
        ),
        "last_checked": _TS,
    },
    # --- 8x NVIDIA H200 141GB (a3-ultragpu-8g, us-central1) ---
    {
        "id": "gpu_h200_0", "label": "H200 #0", "type": "gpu",
        "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 44, "vram_total_gb": 141, "kv_free_gb": 85, "temp_c": 62, "power_w": 310, "util_pct": 45},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #0: OK | GLM-4.7-Flash 30GB + Ministral-3 14GB = 44GB\n[2026-02-26T10:00:00Z] KV cache: 85 GB free \u2014 high concurrency headroom\n[2026-02-26T10:00:00Z] Temp: 62\u00b0C | Power: 310/700W | Util: 45%\n[2026-02-26T10:00:00Z] NVIDIA CC attestation: verified",
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_1", "label": "H200 #1", "type": "gpu", "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 100, "vram_total_gb": 141, "kv_free_gb": 30, "temp_c": 71, "power_w": 520, "util_pct": 78},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #1: OK | Qwen3.5 TP shard 0/4, VRAM 100/141 GB\n[2026-02-26T10:00:00Z] Temp: 71\u00b0C | Power: 520/700W | Util: 78%\n[2026-02-26T10:00:00Z] NVLink: 900 GB/s all-reduce healthy",
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_2", "label": "H200 #2", "type": "gpu", "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 100, "vram_total_gb": 141, "kv_free_gb": 30, "temp_c": 69, "power_w": 510, "util_pct": 76},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #2: OK | Qwen3.5 TP shard 1/4, VRAM 100/141 GB\n[2026-02-26T10:00:00Z] Temp: 69\u00b0C | Power: 510/700W | Util: 76%",
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_3", "label": "H200 #3", "type": "gpu", "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 100, "vram_total_gb": 141, "kv_free_gb": 30, "temp_c": 70, "power_w": 515, "util_pct": 77},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #3: OK | Qwen3.5 TP shard 2/4, VRAM 100/141 GB\n[2026-02-26T10:00:00Z] Temp: 70\u00b0C | Power: 515/700W | Util: 77%",
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_4", "label": "H200 #4", "type": "gpu", "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 100, "vram_total_gb": 141, "kv_free_gb": 30, "temp_c": 72, "power_w": 525, "util_pct": 79},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #4: OK | Qwen3.5 TP shard 3/4, VRAM 100/141 GB\n[2026-02-26T10:00:00Z] Temp: 72\u00b0C | Power: 525/700W | Util: 79%",
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_5", "label": "H200 #5", "type": "gpu", "status": "degraded", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 124, "vram_total_gb": 141, "kv_free_gb": 5, "temp_c": 87, "power_w": 680, "util_pct": 94, "note": "THERMAL THROTTLE"},
        "diagnostics": (
            "[2026-02-26T09:55:12Z] H200 #5: WARNING | GLM-5 TP shard 0/3, VRAM 124/141 GB\n"
            "[2026-02-26T09:55:12Z] Temp: 87\u00b0C \u2014 exceeds 83\u00b0C threshold\n"
            "[2026-02-26T09:55:12Z] Thermal throttle: clock 1980\u21921620 MHz (-18%)\n"
            "[2026-02-26T09:55:12Z] Power: 680/700W (near TDP)\n"
            "[2026-02-26T09:55:12Z] Impact: TP shard 0 bottlenecking all-reduce\n"
            "[2026-02-26T10:00:00Z] DCGM requesting increased airflow"
        ),
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_6", "label": "H200 #6", "type": "gpu", "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 124, "vram_total_gb": 141, "kv_free_gb": 5, "temp_c": 74, "power_w": 560, "util_pct": 82},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #6: OK | GLM-5 TP shard 1/3, VRAM 124/141 GB\n[2026-02-26T10:00:00Z] Temp: 74\u00b0C | Power: 560/700W | Util: 82%\n[2026-02-26T10:00:00Z] Note: idle bubbles from shard 0 (GPU #5 throttle)",
        "last_checked": _TS,
    },
    {
        "id": "gpu_h200_7", "label": "H200 #7", "type": "gpu", "status": "healthy", "icon": "cpu",
        "metrics": {"gpu": "H200 141GB", "zone": "us-central1-a", "vram_used_gb": 124, "vram_total_gb": 141, "kv_free_gb": 5, "temp_c": 73, "power_w": 555, "util_pct": 81},
        "diagnostics": "[2026-02-26T10:00:00Z] H200 #7: OK | GLM-5 TP shard 2/3, VRAM 124/141 GB\n[2026-02-26T10:00:00Z] Temp: 73\u00b0C | Power: 555/700W | Util: 81%\n[2026-02-26T10:00:00Z] Note: idle bubbles from shard 0 (GPU #5 throttle)",
        "last_checked": _TS,
    },
]

DEMO_EDGES = [
    # Ingress
    {"source": "lb", "target": "nginx", "label": "HTTPS", "status": "healthy"},
    {"source": "lb", "target": "auth0", "label": "OAuth2", "status": "healthy"},
    {"source": "auth0", "target": "nginx", "label": "token", "status": "healthy"},
    # Proxy -> Compute (MIG planned but not configured — traffic direct)
    {"source": "nginx", "target": "mig", "label": "planned", "status": "disconnected"},
    {"source": "mig", "target": "vm1", "label": "", "status": "disconnected"},
    {"source": "mig", "target": "vm2", "label": "", "status": "disconnected"},
    {"source": "mig", "target": "vm3", "label": "", "status": "disconnected"},
    {"source": "nginx", "target": "vm1", "label": "proxy", "status": "healthy"},
    {"source": "nginx", "target": "vm2", "label": "proxy", "status": "healthy"},
    {"source": "nginx", "target": "vm3", "label": "proxy", "status": "healthy"},
    # Compute -> Data
    {"source": "vm1", "target": "faiss", "label": "vectors", "status": "healthy"},
    {"source": "vm2", "target": "faiss", "label": "vectors", "status": "healthy"},
    {"source": "vm1", "target": "cloudsql", "label": "SQL", "status": "healthy"},
    {"source": "vm2", "target": "cloudsql", "label": "SQL", "status": "healthy"},
    {"source": "vm1", "target": "embeddings", "label": "embed", "status": "healthy"},
    {"source": "vm2", "target": "embeddings", "label": "embed", "status": "healthy"},
    # Compute -> LLM Router
    {"source": "vm1", "target": "llm_router", "label": "API", "status": "healthy"},
    {"source": "vm2", "target": "llm_router", "label": "API", "status": "healthy"},
    # LLM Router -> Individual LLMs (16 API models)
    {"source": "llm_router", "target": "gemini_3_flash", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "gemini_3_pro", "label": "", "status": "degraded"},
    {"source": "llm_router", "target": "claude_opus_45", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "claude_sonnet_45", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "claude_haiku_45", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "gpt52", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "gpt5_mini", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "grok4", "label": "", "status": "error"},
    {"source": "llm_router", "target": "grok_fast", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "qwen3_235b", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "qwen3_next", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "qwen3_coder", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "llama4_maverick", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "llama4_scout", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "mistral_medium3", "label": "", "status": "healthy"},
    {"source": "llm_router", "target": "minimax_m2", "label": "", "status": "healthy"},
    # LLM Router -> Self-hosted models
    {"source": "llm_router", "target": "model_glm47_flash", "label": "vLLM", "status": "healthy"},
    {"source": "llm_router", "target": "model_ministral3", "label": "vLLM", "status": "healthy"},
    {"source": "llm_router", "target": "model_qwen35", "label": "vLLM", "status": "healthy"},
    {"source": "llm_router", "target": "model_glm5", "label": "vLLM", "status": "degraded"},
    # Models -> GPUs (tensor parallel mapping)
    {"source": "model_glm47_flash", "target": "gpu_h200_0", "label": "TP=1", "status": "healthy"},
    {"source": "model_ministral3", "target": "gpu_h200_0", "label": "TP=1", "status": "healthy"},
    {"source": "model_qwen35", "target": "gpu_h200_1", "label": "TP=4", "status": "healthy"},
    {"source": "model_qwen35", "target": "gpu_h200_2", "label": "", "status": "healthy"},
    {"source": "model_qwen35", "target": "gpu_h200_3", "label": "", "status": "healthy"},
    {"source": "model_qwen35", "target": "gpu_h200_4", "label": "", "status": "healthy"},
    {"source": "model_glm5", "target": "gpu_h200_5", "label": "TP=3", "status": "degraded"},
    {"source": "model_glm5", "target": "gpu_h200_6", "label": "", "status": "healthy"},
    {"source": "model_glm5", "target": "gpu_h200_7", "label": "", "status": "healthy"},
]

DEMO_TOPOLOGY = {
    "nodes": DEMO_NODES,
    "edges": DEMO_EDGES,
    "overall_status": "degraded",
    "last_updated": _TS,
    "logging": {"error_count_15m": 0, "recent_errors": []},
    "security": {"rate_limiter_active": True, "blocked_requests_1h": 7},
    "user_stats": {"active_users": 47, "total_requests_1h": 1847},
}

DEMO_ANALYSIS = {
    "score": 7,
    "summary": (
        "Infrastructure partially degraded. Grok 4 API returning 503 "
        "(circuit breaker open, fallback active). Vertex AI europe-west6 "
        "experiencing elevated latency affecting Gemini 3 Pro. GPU H200 #5 "
        "thermal throttling \u2014 GLM-5-744B inference degraded (queue depth 3). "
        "8x H200 cluster: 7/8 GPUs healthy, 4 self-hosted models serving. "
        "3 Confidential VM instances, 47 active users, 284K encrypted vectors."
    ),
    "issues": [
        "Grok 4 API: circuit breaker OPEN \u2014 503 from xAI, traffic rerouted to Claude Sonnet 4.5",
        "Gemini 3 Pro: degraded \u2014 Vertex AI europe-west6 latency spike (p99: 8420ms)",
        "H200 #5: thermal throttle at 87\u00b0C \u2014 clock reduced 18%, GLM-5 TP shard 0 bottlenecked",
        "GLM-5-744B: inference queue depth 3 \u2014 p99 latency +40% due to GPU #5 throttle",
    ],
    "recommendations": [
        "Monitor xAI status page for Grok 4 recovery \u2014 current ETA unknown",
        "Consider full failover of Gemini 3 Pro to us-central1 until europe-west6 stabilizes",
        "Investigate H200 #5 cooling \u2014 DCGM has requested increased airflow from datacenter",
        "Monitor KV cache pressure on GLM-5 GPUs (5 GB free per shard) \u2014 may need request throttling",
        "VM-3 recently scaled up (12 min ago) \u2014 monitor FAISS store warm-up",
    ],
    "timestamp": 1740567600,
    "stale": False,
}
