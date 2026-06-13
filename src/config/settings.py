# File: src/config/settings.py
# Purpose: Environment-based configuration

import os
from dotenv import load_dotenv

load_dotenv()

# ColdVault connection
COLDVAULT_URL = os.getenv("COLDVAULT_URL", "https://coldvault.ai")
COLDVAULT_ADMIN_KEY = os.getenv("COLDVAULT_ADMIN_KEY", "")

# GCP
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "example-monitoring-project")
GCP_PROJECT_DISPLAY_NAME = os.getenv("GCP_PROJECT_DISPLAY_NAME", "ColdVault Prod")
GCP_ZONE = os.getenv("GCP_ZONE", "us-central1-a")
GCP_VM_NAME = os.getenv("GCP_VM_NAME", "example-vm")
GCP_BACKEND_SERVICE = os.getenv("GCP_BACKEND_SERVICE", "")

# ColdVault API (for AI analysis — replaces direct Gemini)
COLDVAULT_API_KEY = os.getenv("COLDVAULT_API_KEY", "")
ANALYSIS_ESCALATION_THRESHOLD = int(os.getenv("ANALYSIS_ESCALATION_THRESHOLD", "5"))

# Legacy (kept for transition — will be removed)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Auth
GLASSHOOD_PASSWORD = os.getenv("GLASSHOOD_PASSWORD", "")
GLASSHOOD_LOGIN = os.getenv("GLASSHOOD_LOGIN", "admin@example.com")
GLASSHOOD_API_KEY = os.getenv("GLASSHOOD_API_KEY", "")
GLASSHOOD_ADMIN_ROLE = os.getenv("GLASSHOOD_ADMIN_ROLE", "true").lower() == "true"

# Auth0 (SSO / corporate login)
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "your-tenant.us.auth0.com")
AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID", "YOUR_AUTH0_CLIENT_ID")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "https://api.9robots.ai")

# JWT session (Annex 11 §10.2: 15-min idle timeout)
JWT_SECRET = os.getenv("JWT_SECRET", "")  # MUST be set in production
JWT_ACCESS_TTL = int(os.getenv("JWT_ACCESS_TTL", "900"))  # 15 min access token
JWT_REFRESH_TTL = int(os.getenv("JWT_REFRESH_TTL", "86400"))  # 24h refresh token

# Discovery
DISCOVERY_ENABLED = os.getenv("DISCOVERY_ENABLED", "true").lower() == "true"
DISCOVERY_INTERVAL = int(os.getenv("DISCOVERY_INTERVAL", "300"))  # 5 minutes
TOPOLOGY_OVERRIDES_PATH = os.getenv("TOPOLOGY_OVERRIDES_PATH", "config/topology_overrides.yaml")

# Multi-project / org-level discovery
ORG_DISCOVERY_ENABLED = os.getenv("ORG_DISCOVERY_ENABLED", "false").lower() == "true"
ORG_DISCOVERY_CONFIG_PATH = os.getenv("ORG_DISCOVERY_CONFIG_PATH", "config/org_discovery.yaml")
GCP_ORG_ID = os.getenv("GCP_ORG_ID", "000000000000")

# Billing (BigQuery billing export)
BILLING_ENABLED = os.getenv("BILLING_ENABLED", "false").lower() == "true"
BILLING_PROJECT = os.getenv("BILLING_PROJECT", "")
BILLING_DATASET = os.getenv("BILLING_DATASET", "billing_export")
BILLING_TABLE = os.getenv("BILLING_TABLE", "")
MODEL_CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH", "config/model_settings.yaml")
RULES_CONFIG_PATH = os.getenv("RULES_CONFIG_PATH", "config/rules.yaml")
SECURITY_SCAN_CONFIG_PATH = os.getenv("SECURITY_SCAN_CONFIG_PATH", "config/security_scan.yaml")
SECURITY_SCAN_ENABLED = os.getenv("SECURITY_SCAN_ENABLED", "true").lower() == "true"
NVD_API_KEY = os.getenv("NVD_API_KEY", "")
ANOMALY_DETECTION_ENABLED = os.getenv("ANOMALY_DETECTION_ENABLED", "true").lower() == "true"
ANOMALY_CONFIG_PATH = os.getenv("ANOMALY_CONFIG_PATH", "config/anomaly_thresholds.yaml")
COMPLIANCE_CONFIG_PATH = os.getenv("COMPLIANCE_CONFIG_PATH", "config/compliance.yaml")

# ServiceNow integration
SNOW_INSTANCE_URL = os.getenv("SNOW_INSTANCE_URL", "")
SNOW_USERNAME = os.getenv("SNOW_USERNAME", "")
SNOW_PASSWORD = os.getenv("SNOW_PASSWORD", "")
SNOW_CONFIG_PATH = os.getenv("SNOW_CONFIG_PATH", "config/integrations/servicenow.yaml")
SNOW_ENABLED = os.getenv("SNOW_ENABLED", "false").lower() == "true"

# Black box recorder
BLACKBOX_ENABLED = os.getenv("BLACKBOX_ENABLED", "true").lower() == "true"
BLACKBOX_LOCAL_DIR = os.getenv("BLACKBOX_LOCAL_DIR", "/tmp/glasshood-blackbox")
BLACKBOX_BUCKET = os.getenv("BLACKBOX_BUCKET", "")

# Ingestion
INGEST_ENABLED = os.getenv("INGEST_ENABLED", "true").lower() == "true"
INGEST_BUFFER_SIZE = int(os.getenv("INGEST_BUFFER_SIZE", "5000"))
INGEST_MAX_BATCH_SIZE = int(os.getenv("INGEST_MAX_BATCH_SIZE", "500"))
INGEST_RULES_ENABLED = os.getenv("INGEST_RULES_ENABLED", "true").lower() == "true"

# Storage tiers (Phase 7)
STORAGE_ENABLED = os.getenv("STORAGE_ENABLED", "false").lower() == "true"
STORAGE_BQ_PROJECT = os.getenv("STORAGE_BQ_PROJECT", "")
STORAGE_BQ_DATASET = os.getenv("STORAGE_BQ_DATASET", "glasshood")
STORAGE_BQ_TABLE = os.getenv("STORAGE_BQ_TABLE", "events")
STORAGE_LOCAL_DIR = os.getenv("STORAGE_LOCAL_DIR", "/tmp/glasshood-storage")
STORAGE_FLUSH_INTERVAL = int(os.getenv("STORAGE_FLUSH_INTERVAL", "30"))

# Retention (Phase 7)
RETENTION_ENABLED = os.getenv("RETENTION_ENABLED", "false").lower() == "true"
RETENTION_CONFIG_PATH = os.getenv("RETENTION_CONFIG_PATH", "config/retention.yaml")
RETENTION_ARCHIVE_BUCKET = os.getenv("RETENTION_ARCHIVE_BUCKET", "")

# Column encryption (AEAD — AES-256-GCM for message field)
STORAGE_ENCRYPTION_KEY = os.getenv("STORAGE_ENCRYPTION_KEY", "")  # hex-encoded 32-byte key

# Polling intervals (seconds)
COLDVAULT_POLL_INTERVAL = 30
GCP_POLL_INTERVAL = 60
ANALYSIS_INTERVAL = 300  # 5 minutes
ANALYSIS_COOLDOWN = 60   # manual refresh rate limit
