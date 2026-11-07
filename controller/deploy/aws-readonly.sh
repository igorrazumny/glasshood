#!/usr/bin/env bash
# File: controller/deploy/aws-readonly.sh
# Purpose: REQ-GHA-035 — GlassHood reads TestRobin in AWS with no stored key. AWS trusts
#   GlassHood's own Azure identity token (the same token Google trusts for ColdVault):
#   an identity provider for Microsoft's token issuer, and one read-only role that only
#   GlassHood's identity can take. The role can describe TestRobin's service and load
#   balancer, read its metrics, and read the /ecs/testrobin log group, nothing else.
#   Safe to run again.
set -euo pipefail
ACCOUNT=049056029791
REGION=us-east-2
TENANT=03c666bf-0d66-4a82-a1bd-02ded076cbe3
AUDIENCE=api://5a5c7756-1e09-472c-9df4-76f49afb17a2
PRINCIPAL=30d8edd1-cab7-4861-be4b-ef0ca48066a2   # GlassHood container app's system identity
ROLE=glasshood-readonly
ISSUER_HOST=sts.windows.net/$TENANT/
PROVIDER_ARN=arn:aws:iam::$ACCOUNT:oidc-provider/$ISSUER_HOST

say() { printf '== %s\n' "$*"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

say "identity provider for Microsoft's token issuer"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  aws iam add-client-id-to-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" \
    --client-id "$AUDIENCE" 2>/dev/null || true
else
  aws iam create-open-id-connect-provider --url "https://$ISSUER_HOST" --client-id-list "$AUDIENCE" >/dev/null
fi

say "role $ROLE, takeable only by GlassHood's identity"
cat > "$tmp/trust.json" <<EOF
{"Version": "2012-10-17", "Statement": [{
  "Effect": "Allow",
  "Principal": {"Federated": "$PROVIDER_ARN"},
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {"StringEquals": {"$ISSUER_HOST:aud": "$AUDIENCE", "$ISSUER_HOST:sub": "$PRINCIPAL"}}
}]}
EOF
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "file://$tmp/trust.json"
else
  aws iam create-role --role-name "$ROLE" --max-session-duration 3600 \
    --description "GlassHood read-only view of TestRobin (REQ-GHA-035)" \
    --assume-role-policy-document "file://$tmp/trust.json" >/dev/null
fi

say "read-only permissions"
cat > "$tmp/policy.json" <<EOF
{"Version": "2012-10-17", "Statement": [
  {"Sid": "TestRobinLogs", "Effect": "Allow",
   "Action": ["logs:FilterLogEvents", "logs:GetLogEvents", "logs:DescribeLogStreams"],
   "Resource": ["arn:aws:logs:$REGION:$ACCOUNT:log-group:/ecs/testrobin", "arn:aws:logs:$REGION:$ACCOUNT:log-group:/ecs/testrobin:*"]},
  {"Sid": "Describe", "Effect": "Allow",
   "Action": ["logs:DescribeLogGroups", "ecs:DescribeClusters", "ecs:DescribeServices", "ecs:DescribeTasks",
              "ecs:ListTasks", "ecs:ListServices", "ecs:DescribeTaskDefinition",
              "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTargetGroups",
              "elasticloadbalancing:DescribeTargetHealth", "elasticloadbalancing:DescribeListeners",
              "cloudwatch:GetMetricData", "cloudwatch:ListMetrics"],
   "Resource": "*"}
]}
EOF
aws iam put-role-policy --role-name "$ROLE" --policy-name glasshood-readonly --policy-document "file://$tmp/policy.json"
say "done: arn:aws:iam::$ACCOUNT:role/$ROLE"
