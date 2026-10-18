#!/usr/bin/env bash
# File: controller/deploy/cutover.sh
# Purpose: REQ-GHA-018 clause 13 — the container app's side of the move, in order.
#   cutover.sh prepare <image>   still always on: new image, CORS for app.glasshood.ai,
#                                120 s termination grace. Nothing can sleep yet.
#   cutover.sh enable            step (e): record an awake intent, switch the reconciler
#                                on, wait until it holds the wake message, then let the
#                                app scale to zero on the queue rule (min 0 / max 1).
#   cutover.sh rollback          back to always on: reconciler off, ingress open,
#                                min 1 / max 1, no queue rule. Tested before (e).
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
RG=rg-glasshood-azure
APP=glasshood
SA=stghcfgc6c91c0a
FUNC=${FUNC:-func-glasshood-wake}
APP_ORIGINS=${APP_ORIGINS:-https://app.glasshood.ai,https://red-river-0811aa70f.1.azurestaticapps.net}
here=$(cd "$(dirname "$0")" && pwd)

say() { printf '== %s\n' "$*"; }
settings() { az functionapp config appsettings set -g "$RG" -n "$FUNC" -o none --settings "$@" </dev/null; }

case "${1:-}" in
  prepare)
    image=${2:?usage: cutover.sh prepare <image>}
    say "image $image, CORS_ORIGINS, termination grace 120 s (min 1 / max 1 unchanged)"
    az containerapp update -g "$RG" -n "$APP" --image "$image" \
      --set-env-vars "CORS_ORIGINS=$APP_ORIGINS" -o none </dev/null
    az containerapp update -g "$RG" -n "$APP" \
      --termination-grace-period 120 -o none </dev/null
    ;;

  enable)
    say "awake intent first, so turning the reconciler on cannot put the app to sleep"
    "$here/ops.sh" wake >/dev/null
    settings RECONCILE=on
    say "waiting for the reconciler to place the wake message"
    for _ in $(seq 1 60); do
      n=$(az storage message peek --account-name "$SA" --auth-mode login -q glasshood-wake \
            --num-messages 32 --query "length(@)" -o tsv </dev/null 2>/dev/null || echo 0)
      [ "${n:-0}" -ge 1 ] && break
      sleep 5
    done
    [ "${n:-0}" -ge 1 ] || { echo "no wake message after 5 minutes; nothing changed on the app" >&2; exit 1; }
    say "the app's own identity may read the wake queue (for its scale rule)"
    az containerapp identity assign -g "$RG" -n "$APP" --system-assigned -o none </dev/null
    pid=$(az containerapp identity show -g "$RG" -n "$APP" --query principalId -o tsv </dev/null)
    az role assignment create --assignee-object-id "$pid" --assignee-principal-type ServicePrincipal \
      --role "Storage Queue Data Reader" \
      --scope "$(az storage account show -g "$RG" -n "$SA" --query id -o tsv </dev/null)" -o none </dev/null 2>/dev/null || true
    say "queue scale rule, min 0 / max 1, cooldown 30 s"
    az containerapp update -g "$RG" -n "$APP" --min-replicas 0 --max-replicas 1 \
      --scale-rule-name wake --scale-rule-type azure-queue \
      --scale-rule-metadata queueName=glasshood-wake queueLength=1 accountName="$SA" \
      --scale-rule-identity system -o none </dev/null
    az resource update -g "$RG" -n "$APP" --resource-type Microsoft.App/containerApps \
      --set properties.template.scale.cooldownPeriod=30 -o none </dev/null
    "$here/ops.sh" status
    ;;

  rollback)
    say "reconciler off, ingress open, always on (min 1 / max 1, no queue rule)"
    settings RECONCILE=off
    az containerapp ingress access-restriction remove -g "$RG" -n "$APP" --rule-name asleep -o none </dev/null 2>/dev/null || true
    rev=$(az containerapp show -g "$RG" -n "$APP" --query properties.latestRevisionName -o tsv </dev/null)
    az containerapp revision activate -g "$RG" -n "$APP" --revision "$rev" -o none </dev/null 2>/dev/null || true
    az containerapp update -g "$RG" -n "$APP" --min-replicas 1 --max-replicas 1 \
      --remove-all-scale-rules -o none </dev/null 2>/dev/null \
      || az containerapp update -g "$RG" -n "$APP" --min-replicas 1 --max-replicas 1 -o none </dev/null
    curl -s -o /dev/null -w "health %{http_code}\n" \
      "https://$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv </dev/null)/api/health"
    ;;

  *) echo "usage: cutover.sh prepare <image> | enable | rollback" >&2; exit 2 ;;
esac
