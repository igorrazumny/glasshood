#!/usr/bin/env bash
# File: controller/deploy/state.sh
# Purpose: REQ-GHA-029 — a writable folder that survives restarts, for AI alarms and their
#   investigation reports. Creates the file share glasshood-state, registers it with the
#   container app environment (read-write), mounts it at /app/state and sets AI_STATE_DIR.
#   Also drops the dead NINE_ROBOTS_PLATFORM_KEY setting (the platform it served is off).
#   Safe to run again. The storage key goes straight from az to az and is never printed.
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
RG=rg-glasshood-azure
APP=glasshood
ENV_NAME=cae-glasshood
SA=stghcfgc6c91c0a
SHARE=glasshood-state
STORE=statestore
MOUNT=/app/state

say() { printf '== %s\n' "$*"; }

say "file share $SHARE (1 GiB)"
az storage share-rm create -g "$RG" --storage-account "$SA" -n "$SHARE" --quota 1 -o none </dev/null

say "environment storage $STORE (ReadWrite)"
az containerapp env storage set -g "$RG" -n "$ENV_NAME" --storage-name "$STORE" \
  --azure-file-account-name "$SA" --azure-file-share-name "$SHARE" --access-mode ReadWrite \
  --azure-file-account-key "$(az storage account keys list -g "$RG" -n "$SA" --query '[0].value' -o tsv </dev/null)" \
  -o none </dev/null

say "mount $MOUNT, AI_STATE_DIR, drop NINE_ROBOTS_PLATFORM_KEY (one new revision)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
az containerapp show -g "$RG" -n "$APP" --query properties.template -o json </dev/null > "$tmp/template.json"
python3 - "$tmp/template.json" "$STORE" "$MOUNT" <<'PY'
import json, sys
path, store, mount = sys.argv[1:]
t = json.load(open(path))
vols = [v for v in (t.get("volumes") or []) if v.get("name") != "statevol"]
vols.append({"name": "statevol", "storageName": store, "storageType": "AzureFile"})
t["volumes"] = vols
for c in t["containers"]:
    c["volumeMounts"] = [m for m in (c.get("volumeMounts") or []) if m.get("volumeName") != "statevol"]
    c["volumeMounts"].append({"volumeName": "statevol", "mountPath": mount})
    env = [e for e in (c.get("env") or []) if e.get("name") not in ("AI_STATE_DIR", "NINE_ROBOTS_PLATFORM_KEY")]
    env.append({"name": "AI_STATE_DIR", "value": mount})
    c["env"] = env
t.pop("revisionSuffix", None)
json.dump({"properties": {"template": t}}, open(path, "w"))
PY
SUB=$(az account show --query id -o tsv </dev/null)
az rest --method patch -o none \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP?api-version=2025-01-01" \
  --body "@$tmp/template.json" </dev/null

say "remove the unused platform-key secret"
for _ in $(seq 1 30); do  # a secret change is refused while the new revision is provisioning
  [ "$(az containerapp show -g "$RG" -n "$APP" --query properties.provisioningState -o tsv </dev/null)" = Succeeded ] && break
  sleep 10
done
if az containerapp secret list -g "$RG" -n "$APP" --query "[].name" -o tsv </dev/null | grep -qx platform-key; then
  az containerapp secret remove -g "$RG" -n "$APP" --secret-names platform-key -o none </dev/null
fi
say "done"
