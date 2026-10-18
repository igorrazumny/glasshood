#!/usr/bin/env bash
# File: controller/deploy/cutover.sh
# Purpose: REQ-GHA-018 clause 13 — the container app's side of the move, in order.
#   cutover.sh prepare <image>   still always on: new image, CORS for app.glasshood.ai,
#                                120 s termination grace. Nothing can sleep yet.
#   cutover.sh enable            step (e): record an awake intent, switch the reconciler
#                                on, wait until it holds the wake message, then let the
#                                app scale to zero on the queue rule (min 0 / max 1).
#   cutover.sh rollback          back to always on: reconciler off and halted, any
#                                operation it left with Azure waited out, then ingress
#                                open, revision active, min 1 / max 1, no queue rule,
#                                and that final state verified. Tested before (e).
# Needs PY (default python3) with azure-identity, azure-data-tables, azure-storage-queue
# and httpx, for controller/deploy/fence.py.
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
RG=rg-glasshood-azure
APP=glasshood
SA=stghcfgc6c91c0a
FUNC=${FUNC:-func-glasshood-wake}
APP_ORIGINS=${APP_ORIGINS:-https://app.glasshood.ai,https://red-river-0811aa70f.1.azurestaticapps.net}
here=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python3}
SUB=$(az account show --query id -o tsv </dev/null)
export SA CONTAINER_APP_ID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP"
export CONTAINER_APP_FQDN=$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv </dev/null)

say() { printf '== %s\n' "$*"; }
die() { echo "cutover.sh: $*" >&2; exit 1; }
settings() { az functionapp config appsettings set -g "$RG" -n "$FUNC" -o none --settings "$@" </dev/null; }
fence() { "$PY" "$here/fence.py" "$@"; }
field() { "$PY" -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }

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
    "$here/ops.sh" wake >/dev/null || die "operator wake refused; nothing changed"
    intent=$(fence intent)
    [ "$(field desired <<<"$intent")" = awake ] || die "intent is not awake after the wake: $intent"
    fence resume >/dev/null
    settings RECONCILE=on
    say "waiting for the reconciler to place the current generation's wake message"
    ok=
    for _ in $(seq 1 60); do
      intent=$(fence intent)
      if [ "$(field desired <<<"$intent")" != awake ]; then
        ok=; break                                   # someone asked for sleep: stop here
      fi
      if fence has-message "$(field generation <<<"$intent")"; then ok=1; break; fi
      sleep 5
    done
    if [ -z "$ok" ]; then
      settings RECONCILE=off
      fence halt >/dev/null
      die "no wake message for the awake intent ($intent); reconciler switched off and halted, app scale unchanged"
    fi
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
    say "reconciler off and halted: no running or new reconciler can send another change"
    settings RECONCILE=off
    fence halt >/dev/null
    say "waiting out any operation it already handed to Azure"
    fence wait
    say "ingress open, revision active, always on (min 1 / max 1, no queue rule)"
    az containerapp ingress access-restriction remove -g "$RG" -n "$APP" --rule-name asleep -o none </dev/null 2>/dev/null || true
    rev=$(az containerapp show -g "$RG" -n "$APP" --query properties.latestRevisionName -o tsv </dev/null)
    az containerapp revision activate -g "$RG" -n "$APP" --revision "$rev" -o none </dev/null 2>/dev/null || true
    az containerapp update -g "$RG" -n "$APP" --min-replicas 1 --max-replicas 1 \
      --remove-all-scale-rules -o none </dev/null 2>/dev/null \
      || az containerapp update -g "$RG" -n "$APP" --min-replicas 1 --max-replicas 1 -o none </dev/null
    say "verifying the final always-on state"
    for _ in $(seq 1 60); do
      state=$(az containerapp show -g "$RG" -n "$APP" -o json </dev/null | "$PY" -c '
import json, sys
p = json.load(sys.stdin)["properties"]
r = [x for x in (p["configuration"]["ingress"].get("ipSecurityRestrictions") or []) if x.get("name") == "asleep"]
s = p["template"]["scale"]
print("ok" if not r and s.get("minReplicas") == 1 and not s.get("rules") else "pending")')
      active=$(az containerapp revision show -g "$RG" -n "$APP" --revision "$rev" --query properties.active -o tsv </dev/null)
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://$CONTAINER_APP_FQDN/api/health" || true)
      if [ "$state" = ok ] && [ "$active" = true ] && [ "$code" = 200 ]; then
        say "rolled back: open, active, min 1, no queue rule, health 200"
        exit 0
      fi
      sleep 5
    done
    die "final state not reached (scale/ingress: $state, revision active: $active, health: $code)"
    ;;

  *) echo "usage: cutover.sh prepare <image> | enable | rollback" >&2; exit 2 ;;
esac
