#!/usr/bin/env python3
"""Workload Identity Federation token broker (Azure managed identity -> GCP).

Azure Container Apps exposes its managed identity through IDENTITY_ENDPOINT /
IDENTITY_HEADER (not the plain VM IMDS at 169.254.169.254), so GCP's stock
url-sourced credential can't reach it directly. This tiny broker fetches the
Entra managed-identity token for the GCP-trusted audience and prints it in the
format google-auth's executable credential source expects. No keys are stored
anywhere — the token is short-lived and fetched on demand.
"""
import json
import os
import urllib.request

# Audience the GCP provider is configured to trust (the app registration URI).
AUDIENCE = os.environ.get(
    "AZURE_WIF_AUDIENCE", "api://00000000-0000-0000-0000-000000000000"
)

endpoint = os.environ["IDENTITY_ENDPOINT"]
header = os.environ["IDENTITY_HEADER"]
url = f"{endpoint}?resource={AUDIENCE}&api-version=2019-08-01"

req = urllib.request.Request(url, headers={"X-IDENTITY-HEADER": header})
with urllib.request.urlopen(req, timeout=4) as resp:
    data = json.load(resp)

print(json.dumps({
    "version": 1,
    "success": True,
    "token_type": "urn:ietf:params:oauth:token-type:jwt",
    "id_token": data["access_token"],
    "expiration_time": int(data["expires_on"]),
}))
