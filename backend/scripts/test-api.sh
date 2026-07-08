#!/usr/bin/env bash
# ============================================================================
# Smoke test for the ML Serving & Monitoring Platform API.
#
# Prereqs: `python scripts/dev.py` running in another terminal; bash, curl, jq.
#
# ROLE NOTE: this script exercises what is reachable as the CURRENTLY
# CONFIGURED dev role (see DEV_USER_ROLE in .env). The seeded default is
# LeadDataScientist in tenant acme-capital, which can do everything below
# EXCEPT the PlatformAdmin-only tenant-create call -- for any non-admin role
# that call returns 403, which this script treats as the expected outcome
# and counts as a pass.
#
# To test other roles (manual follow-up):
#   1. Edit .env: DEV_USER_ROLE=PlatformAdmin   (or DataScientist)
#   2. Restart scripts/dev.py (env vars are read once at startup)
#   3. Re-run this script -- write calls should now 403, reads still 200.
# ============================================================================
set -u

API="${API_URL:-http://localhost:8000}"
PASS=0
FAIL=0

# jq is preferred but not always present on Windows Git Bash -- fall back to
# python for JSON field extraction. Usage: printf '%s' "$BODY" | json '.role'
if command -v jq >/dev/null 2>&1; then
  json() {
    # Translate the two convenience keywords into real jq expressions.
    case "$1" in
      steps_join)    jq -r '[.steps[].status] | join(",")' ;;
      awaiting_step) jq -r '.steps[] | select(.status=="awaiting_approval") | .stepId' ;;
      *)             jq -r "$1" ;;
    esac
  }
else
  json() {
    python -c "
import json, sys
expr = sys.argv[1]
data = json.load(sys.stdin)
if expr == 'steps_join':
    print(','.join(s['status'] for s in data['steps']))
elif expr == 'awaiting_step':
    print(next(s['stepId'] for s in data['steps'] if s['status'] == 'awaiting_approval'))
else:
    cur = data
    for part in expr.lstrip('.').split('.'):
        cur = cur[part] if isinstance(cur, dict) else cur
    print(cur)
" "$1"
  }
fi

say()  { printf '\n== %s ==\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf 'PASS: %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$*"; }

req() { # method path [json-body] -> sets BODY and CODE
  local method="$1" path="$2" data="${3:-}"
  if [ -n "$data" ]; then
    BODY=$(curl -s -w '\n%{http_code}' -X "$method" "$API$path" \
      -H 'Content-Type: application/json' -d "$data")
  else
    BODY=$(curl -s -w '\n%{http_code}' -X "$method" "$API$path")
  fi
  CODE=$(printf '%s' "$BODY" | tail -n1)
  BODY=$(printf '%s' "$BODY" | sed '$d')
}

say "Health"
req GET /health
[ "$CODE" = "200" ] && ok "GET /health -> 200" || bad "GET /health -> $CODE"

say "Auth"
req GET /auth/me
if [ "$CODE" = "200" ]; then
  ROLE=$(printf '%s' "$BODY" | json .role)
  TENANT=$(printf '%s' "$BODY" | json .tenantId)
  ok "GET /auth/me -> 200 (role=$ROLE tenant=$TENANT)"
else
  bad "GET /auth/me -> $CODE"; ROLE=unknown; TENANT=unknown
fi

say "Tenant create (PlatformAdmin-only endpoint)"
req POST /tenants '{"name":"Smoke Test Capital"}'
if [ "$ROLE" = "PlatformAdmin" ]; then
  { [ "$CODE" = "201" ] || [ "$CODE" = "409" ]; } \
    && ok "POST /tenants -> $CODE as PlatformAdmin" \
    || bad "POST /tenants -> $CODE as PlatformAdmin (expected 201/409)"
else
  [ "$CODE" = "403" ] \
    && ok "POST /tenants -> 403 as $ROLE (correctly denied)" \
    || bad "POST /tenants -> $CODE as $ROLE (expected 403)"
fi

say "List tenants (admin-console endpoint)"
req GET "/tenants?page=1&pageSize=10"
if [ "$ROLE" = "PlatformAdmin" ]; then
  [ "$CODE" = "200" ] && ok "GET /tenants -> 200 (total=$(printf '%s' "$BODY" | json .total))" || bad "GET /tenants -> $CODE"
else
  [ "$CODE" = "403" ] && ok "GET /tenants -> 403 as $ROLE (admin console only)" || bad "GET /tenants -> $CODE as $ROLE (expected 403)"
fi

if [ "$ROLE" = "LeadDataScientist" ]; then
  say "Create pipeline (LeadDataScientist)"
  req POST /pipelines '{
    "name": "Smoke Test Pipeline",
    "description": "Created by test-api.sh",
    "requiresApproval": true,
    "steps": [
      {"step_id": "step-1", "type": "data_pipeline", "dependsOn": [], "config": {
        "sourceType": "snowflake", "snowflakeDatabase": "FIN_DW", "snowflakeSchema": "SCORING",
        "snowflakeTable": "SMOKE", "snowflakeWarehouse": "WH", "destinationS3Uri": "s3://smoke/in/"}},
      {"step_id": "step-2", "type": "execute_model", "dependsOn": ["step-1"], "config": {
        "modelName": "credit-risk-scorer", "modelVersion": 1, "emrApplicationId": "app-1",
        "executionRoleArn": "arn:aws:iam::123456789012:role/x", "entryPointS3Uri": "s3://smoke/ep.py",
        "inputS3Uri": "s3://smoke/in/", "outputS3Uri": "s3://smoke/out/"}},
      {"step_id": "step-3", "type": "data_quality_check", "dependsOn": ["step-2"], "config": {
        "checks": [{"name": "nulls", "type": "null_rate", "threshold": 0.5}], "inputS3Uri": "s3://smoke/out/"}},
      {"step_id": "step-4", "type": "approval", "dependsOn": ["step-3"], "config": {}}
    ]}'
  if [ "$CODE" = "201" ]; then
    PIPELINE_ID=$(printf '%s' "$BODY" | json .pipelineId)
    ok "POST /pipelines -> 201 ($PIPELINE_ID)"

    say "Submit job"
    req POST /jobs "{\"pipeline_id\": \"$PIPELINE_ID\"}"
    if [ "$CODE" = "201" ]; then
      JOB_ID=$(printf '%s' "$BODY" | json .jobId)
      ok "POST /jobs -> 201 ($JOB_ID, status=$(printf '%s' "$BODY" | json .status))"

      say "Poll job until awaiting_approval or terminal (EMR mock takes ~10s)"
      STATUS=unknown
      for i in $(seq 1 15); do
        sleep 3
        req GET "/jobs/$JOB_ID"
        STATUS=$(printf '%s' "$BODY" | json .status)
        printf '  poll %2d: status=%s steps=[%s]\n' "$i" "$STATUS" \
          "$(printf '%s' "$BODY" | json steps_join)"
        case "$STATUS" in
          awaiting_approval|success|failed|cancelled) break ;;
        esac
      done
      case "$STATUS" in
        awaiting_approval) ok "job reached awaiting_approval" ;;
        success|failed)    ok "job reached terminal status $STATUS" ;;
        *)                 bad "job stuck in status $STATUS" ;;
      esac

      if [ "$STATUS" = "awaiting_approval" ]; then
        say "Approve the approval step"
        STEP_ID=$(printf '%s' "$BODY" | json awaiting_step)
        req POST "/jobs/$JOB_ID/steps/$STEP_ID/approve"
        [ "$CODE" = "200" ] \
          && ok "approve -> 200 (job status=$(printf '%s' "$BODY" | json .status))" \
          || bad "approve -> $CODE"
      fi
    else
      bad "POST /jobs -> $CODE"
    fi
  else
    bad "POST /pipelines -> $CODE"
  fi
else
  say "Skipping pipeline/job write tests (role=$ROLE is not LeadDataScientist)"
  req POST /pipelines '{"name":"x","steps":[]}'
  [ "$CODE" = "403" ] && ok "POST /pipelines correctly 403 for $ROLE" || bad "POST /pipelines -> $CODE (expected 403)"
fi

say "List pipelines / jobs / models / monitoring / audit"
for path in "/pipelines" "/jobs" "/models" "/monitoring/snapshots" "/audit"; do
  req GET "$path?page=1&pageSize=5"
  [ "$CODE" = "200" ] \
    && ok "GET $path -> 200 (total=$(printf '%s' "$BODY" | json .total))" \
    || bad "GET $path -> $CODE"
done

say "Monitoring dashboard"
req GET /monitoring/dashboard
[ "$CODE" = "200" ] && ok "GET /monitoring/dashboard -> 200" || bad "GET /monitoring/dashboard -> $CODE"

printf '\n=================================\n'
printf 'RESULT: %d passed, %d failed\n' "$PASS" "$FAIL"
printf '=================================\n'
[ "$FAIL" -eq 0 ]
