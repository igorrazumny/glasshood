#!/usr/bin/env bash
# File: controller/deploy/setup.sh
# Purpose: REQ-GHA-018 — create (or bring up to date) the wake controller's Azure
# pieces. Safe to re-run. It does NOT change the container app's scale or ingress:
# that is the cutover (cutover.sh), done only after verification (clause 13).
#
# Needs: az logged in, and the reCAPTCHA secret already in Key Vault as
# wake-recaptcha-secret (written there straight from Google, never printed).
# Usage: controller/deploy/setup.sh
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

SUB=c6c91c0a-c86d-45f2-9c4a-ffdc7c67cb00
RG=rg-glasshood-azure
LOC=switzerlandnorth
SA=stghcfgc6c91c0a
KV=kv-glasshood-prod
APP=glasshood
FUNC=${FUNC:-func-glasshood-wake}
APP_ID=/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP
APP_FQDN=$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv </dev/null)
ORIGINS=${ORIGINS:-https://app.glasshood.ai,https://red-river-0811aa70f.1.azurestaticapps.net,https://glasshood.ai,https://architecture.glasshood.ai,https://ashy-sea-07717d00f.4.azurestaticapps.net,https://lemon-sand-00849da0f.5.azurestaticapps.net}
APP_ORIGINS=${APP_ORIGINS:-https://app.glasshood.ai,https://red-river-0811aa70f.1.azurestaticapps.net}
RECAPTCHA_HOSTS=${RECAPTCHA_HOSTS:-app.glasshood.ai,red-river-0811aa70f.1.azurestaticapps.net}

say() { printf '== %s\n' "$*"; }

say "storage: tables, queues, lease container"
for t in wakestate wakeevents; do
  az storage table create --account-name "$SA" --auth-mode login -n "$t" -o none </dev/null
done
for q in glasshood-wake wake-control; do
  az storage queue create --account-name "$SA" --auth-mode login -n "$q" -o none </dev/null
done
az storage container create --account-name "$SA" --auth-mode login -n wake -o none </dev/null
az storage container create --account-name "$SA" --auth-mode login -n func-deploy -o none </dev/null

say "function app (Flex Consumption, Python 3.12, no Application Insights)"
if ! az functionapp show -g "$RG" -n "$FUNC" -o none </dev/null 2>/dev/null; then
  az functionapp create -g "$RG" -n "$FUNC" --storage-account "$SA" \
    --flexconsumption-location "$LOC" --runtime python --runtime-version 3.12 \
    --instance-memory 512 --maximum-instance-count 40 \
    --deployment-storage-name "$SA" --deployment-storage-container-name func-deploy \
    --deployment-storage-auth-type SystemAssignedIdentity \
    --disable-app-insights true -o none </dev/null
fi
az functionapp identity assign -g "$RG" -n "$FUNC" -o none </dev/null
PRINCIPAL=$(az functionapp identity show -g "$RG" -n "$FUNC" --query principalId -o tsv </dev/null)
SA_ID=$(az storage account show -g "$RG" -n "$SA" --query id -o tsv </dev/null)

say "roles for the controller's identity (scoped to the storage account and the one app)"
grant() {
  az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "$1" --scope "$2" -o none </dev/null 2>/dev/null || true
}
grant "Storage Table Data Contributor" "$SA_ID"
grant "Storage Queue Data Contributor" "$SA_ID"
grant "Storage Blob Data Owner" "$SA_ID"
grant "Contributor" "$APP_ID"
# ARM reports an accepted operation's progress at a subscription-level URL
# (.../providers/Microsoft.App/locations/<loc>/containerappOperationStatuses/<id>),
# which the app-scoped Contributor does not cover: a read-only role for just that.
ROLE="GlassHood wake operation reader"
if [ -z "$(az role definition list --custom-role-only true --name "$ROLE" --query "[0].id" -o tsv </dev/null)" ]; then
  az role definition create -o none --role-definition "{
    \"Name\": \"$ROLE\",
    \"Description\": \"REQ-GHA-018: read Container Apps operation status and results only\",
    \"Actions\": [\"Microsoft.App/locations/containerappOperationStatuses/read\",
                  \"Microsoft.App/locations/containerappOperationResults/read\"],
    \"AssignableScopes\": [\"/subscriptions/$SUB\"]}" </dev/null
fi
grant "$ROLE" "/subscriptions/$SUB"
grant "Key Vault Secrets User" "$(az keyvault show -n "$KV" --query id -o tsv </dev/null)"

say "secrets in Key Vault (use-token key generated once; reCAPTCHA secret must already be there)"
az keyvault secret show --vault-name "$KV" -n wake-recaptcha-secret --query id -o none </dev/null \
  || { echo "wake-recaptcha-secret is missing from $KV" >&2; exit 1; }
if ! az keyvault secret show --vault-name "$KV" -n wake-use-token-secret -o none </dev/null 2>/dev/null; then
  az keyvault secret set --vault-name "$KV" -n wake-use-token-secret \
    --value "$(openssl rand -hex 32)" -o none </dev/null
fi

say "settings"
ref() { echo "@Microsoft.KeyVault(VaultName=$KV;SecretName=$1)"; }
az functionapp config appsettings set -g "$RG" -n "$FUNC" -o none --settings \
  STORAGE_ACCOUNT="$SA" \
  ControlQueue__queueServiceUri="https://$SA.queue.core.windows.net" \
  CONTAINER_APP_ID="$APP_ID" \
  CONTAINER_APP_FQDN="$APP_FQDN" \
  ALLOWED_ORIGINS="$APP_ORIGINS" \
  RECAPTCHA_HOSTS="$RECAPTCHA_HOSTS" \
  USE_TOKEN_SECRET="$(ref wake-use-token-secret)" \
  RECAPTCHA_SECRET="$(ref wake-recaptcha-secret)" </dev/null
# The reconciler stays off until the cutover turns it on; never switch it off here.
if [ "$(az functionapp config appsettings list -g "$RG" -n "$FUNC" --query "[?name=='RECONCILE'].value | [0]" -o tsv </dev/null)" != "on" ]; then
  az functionapp config appsettings set -g "$RG" -n "$FUNC" -o none --settings RECONCILE=off </dev/null
fi

say "CORS: the public pages read /status; app.glasshood.ai also posts /wake and /use"
EXISTING=$(az functionapp cors show -g "$RG" -n "$FUNC" --query allowedOrigins -o tsv </dev/null || true)
for o in ${ORIGINS//,/ }; do
  grep -qx "$o" <<<"$EXISTING" || az functionapp cors add -g "$RG" -n "$FUNC" --allowed-origins "$o" -o none </dev/null
done

say "done: https://$(az resource show -g "$RG" -n "$FUNC" --resource-type Microsoft.Web/sites --query properties.defaultHostName -o tsv </dev/null)"
