#!/usr/bin/env bash
# File: controller/deploy/ops.sh
# Purpose: REQ-GHA-018 clause 10 — operator commands. All are safe to repeat.
#   ops.sh status         state, last use, hold, and recent events
#   ops.sh wake           wake the app
#   ops.sh sleep          put it to sleep (ends any hold)
#   ops.sh hold <hours>   keep it awake for that long (wakes it if needed)
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
RG=rg-glasshood-azure
FUNC=${FUNC:-func-glasshood-wake}

host=$(az functionapp show -g "$RG" -n "$FUNC" --query defaultHostName -o tsv </dev/null)
key=$(az functionapp keys list -g "$RG" -n "$FUNC" --query functionKeys.default -o tsv </dev/null)
call() { curl -sS -X "$1" -H "x-functions-key: $key" "https://$host/api/$2"; echo; }

case "${1:-}" in
  status) call GET ops/status ;;
  wake)   call POST ops/wake ;;
  sleep)  call POST ops/sleep ;;
  hold)   [[ "${2:-}" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "usage: ops.sh hold <hours>" >&2; exit 2; }
          call POST "ops/hold?hours=$2" ;;
  *)      echo "usage: ops.sh status|wake|sleep|hold <hours>" >&2; exit 2 ;;
esac
