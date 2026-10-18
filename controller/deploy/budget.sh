#!/usr/bin/env bash
# File: controller/deploy/budget.sh
# Purpose: REQ-GHA-018 clause 10 — email Igor when a month's GlassHood bill is on
# course to pass CHF 10 (forecast), and again if it actually does. Safe to re-run.
# Test: THRESHOLD=1 controller/deploy/budget.sh, then restore with the default.
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
SUB=c6c91c0a-c86d-45f2-9c4a-ffdc7c67cb00
RG=rg-glasshood-azure
NAME=${NAME:-glasshood-monthly}
AMOUNT=${AMOUNT:-10}
TO=${TO:?set TO to the alert email address}
START=$(date -u +%Y-%m-01)

az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Consumption/budgets/$NAME?api-version=2023-05-01" \
  --body "$(cat <<EOF
{
  "properties": {
    "category": "Cost",
    "amount": $AMOUNT,
    "timeGrain": "Monthly",
    "timePeriod": { "startDate": "${START}T00:00:00Z", "endDate": "2036-12-31T00:00:00Z" },
    "notifications": {
      "forecast100": { "enabled": true, "operator": "GreaterThan", "threshold": 100,
                       "thresholdType": "Forecasted", "contactEmails": ["$TO"] },
      "actual100":   { "enabled": true, "operator": "GreaterThan", "threshold": 100,
                       "thresholdType": "Actual", "contactEmails": ["$TO"] }
    }
  }
}
EOF
)" -o none </dev/null
echo "budget $NAME: CHF $AMOUNT/month on $RG, forecast and actual alerts to $TO"
