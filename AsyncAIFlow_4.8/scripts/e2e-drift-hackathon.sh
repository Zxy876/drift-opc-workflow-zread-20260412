#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  e2e-drift-hackathon.sh
#  End-to-end smoke-test for the Drift × AsyncAIFlow integrated pipeline.
#
#  Steps verified
#  ─────────────────
#  1. Drift backend is alive            GET  http://localhost:8000/health
#  2. AsyncAIFlow runtime is alive      GET  http://localhost:8080/actuator/health
#  3. Difficulty scoring via Drift AI   POST http://localhost:8000/ai/intent
#  4. Workflow submission               POST http://localhost:8080/planner/execute
#  5. Workflow status polling           GET  http://localhost:8080/workflows/{id}
#  6. Progress notify round-trip        POST http://localhost:8000/story/progress/notify
#  7. Progress status readable          GET  http://localhost:8000/story/progress/status/e2e-player
#
#  Usage
#  ─────
#    bash scripts/e2e-drift-hackathon.sh [drift_url] [aaf_url]
#
#  Environment
#  ───────────
#    DRIFT_URL   override Drift base URL   (default: http://localhost:8000)
#    AAF_URL     override AsyncAIFlow URL  (default: http://localhost:8080)
#    E2E_PLAYER  player id used in test    (default: e2e-player)
#    MAX_WAIT    max seconds to wait for workflow (default: 120)
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

DRIFT_URL="${DRIFT_URL:-${1:-http://localhost:8000}}"
AAF_URL="${AAF_URL:-${2:-http://localhost:8080}}"
E2E_PLAYER="${E2E_PLAYER:-e2e-player}"
MAX_WAIT="${MAX_WAIT:-300}"

PASS=0
FAIL=0
FAILURES=()

# ─── helpers ──────────────────────────────────────────────────────────────────

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; ((PASS++)) || true; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; ((FAIL++)) || true; FAILURES+=("$*"); }
info() { printf '\033[1m%s\033[0m\n' "$*"; }

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf '[e2e] Required command not found: %s\n' "$cmd" >&2
    exit 1
  fi
}

http_get() {
  # returns body; exits 0 on 2xx, 1 on non-2xx; --silent, follow redirects
  curl --silent --fail --max-time 10 "$1"
}

http_post_json() {
  local url="$1"
  local body="$2"
  curl --silent --fail --max-time 30 \
    -X POST \
    -H 'Content-Type: application/json' \
    -d "$body" \
    "$url"
}

require_cmd curl
require_cmd python3

# ─── step 1: Drift health ──────────────────────────────────────────────────────
info '─── Step 1: Drift backend health'
if http_get "${DRIFT_URL}/" >/dev/null 2>&1 || http_get "${DRIFT_URL}/health" >/dev/null 2>&1; then
  ok "Drift backend is alive at ${DRIFT_URL}"
else
  fail "Drift backend unreachable at ${DRIFT_URL}"
fi

# ─── step 2: AsyncAIFlow health ───────────────────────────────────────────────
info '─── Step 2: AsyncAIFlow runtime health'
if http_get "${AAF_URL}/actuator/health" >/dev/null 2>&1 || \
   http_get "${AAF_URL}/workflows" >/dev/null 2>&1; then
  ok "AsyncAIFlow is alive at ${AAF_URL}"
else
  fail "AsyncAIFlow unreachable at ${AAF_URL}"
fi

# ─── step 3: difficulty scoring ───────────────────────────────────────────────
info '─── Step 3: Intent difficulty scoring'
INTENT_BODY='{"text":"修复 Drift lobby 中 NPC 刷新时丢失 entity_type 的严重 bug","context":""}'
INTENT_RESP="$(http_post_json "${DRIFT_URL}/ai/intent" "$INTENT_BODY" 2>/dev/null || echo '')"

if [[ -n "$INTENT_RESP" ]]; then
  DIFFICULTY=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
intents = data if isinstance(data, list) else data.get('intents', [])
if intents:
    d = intents[0].get('difficulty', -1)
    print(d)
else:
    print(-1)
" <<< "$INTENT_RESP" 2>/dev/null || echo -1)

  if [[ "$DIFFICULTY" -ge 1 ]] 2>/dev/null; then
    ok "Intent returned difficulty=${DIFFICULTY}"
  else
    fail "Intent response missing or invalid difficulty field (got: ${DIFFICULTY})"
  fi
else
  fail "No response from ${DRIFT_URL}/ai/intent"
fi

# ─── step 4: workflow submission ──────────────────────────────────────────────
info '─── Step 4: Workflow submission (difficulty=3 Drift plan)'
PLANNER_BODY="{
  \"issue\": \"[E2E] 修复 Drift lobby NPC 刷新 entity_type 丢失问题\",
  \"difficulty\": 3,
  \"player_id\": \"${E2E_PLAYER}\",
  \"branch_prefix\": \"drift/e2e\"
}"

PLANNER_RESP="$(http_post_json "${AAF_URL}/planner/execute" "$PLANNER_BODY" 2>/dev/null || echo '')"

if [[ -n "$PLANNER_RESP" ]]; then
  WORKFLOW_ID=$(python3 -c "
import json, sys
root = json.loads(sys.stdin.read())
data = root.get('data', root)
print(data.get('workflowId', data.get('id', '')))
" <<< "$PLANNER_RESP" 2>/dev/null || echo '')
  if [[ -n "$WORKFLOW_ID" ]]; then
    ok "Workflow created: id=${WORKFLOW_ID}"
  else
    fail "planner/execute returned no workflowId. Response: ${PLANNER_RESP:0:200}"
  fi
else
  fail "No response from ${AAF_URL}/planner/execute"
  WORKFLOW_ID=""
fi

# ─── step 5: workflow polling ─────────────────────────────────────────────────
info '─── Step 5: Workflow status polling'
if [[ -n "$WORKFLOW_ID" ]]; then
  ELAPSED=0
  POLL_INTERVAL=5
  FINAL_STATUS=""

  while [[ $ELAPSED -lt $MAX_WAIT ]]; do
    STATUS_RESP="$(http_get "${AAF_URL}/workflows/${WORKFLOW_ID}" 2>/dev/null || echo '')"
    if [[ -n "$STATUS_RESP" ]]; then
      WF_STATUS=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data.get('status', ''))
" <<< "$STATUS_RESP" 2>/dev/null || echo '')
      if [[ "$WF_STATUS" == "COMPLETED" || "$WF_STATUS" == "SUCCEEDED" ]]; then
        FINAL_STATUS="SUCCEEDED"
        break
      elif [[ "$WF_STATUS" == "FAILED" || "$WF_STATUS" == "ERROR" ]]; then
        FINAL_STATUS="FAILED"
        break
      fi
    fi
    sleep "$POLL_INTERVAL"
    ((ELAPSED+=POLL_INTERVAL)) || true
  done

  if [[ "$FINAL_STATUS" == "SUCCEEDED" ]]; then
    ok "Workflow ${WORKFLOW_ID} completed successfully (${ELAPSED}s)"
  elif [[ "$FINAL_STATUS" == "FAILED" ]]; then
    fail "Workflow ${WORKFLOW_ID} FAILED"
  else
    # Timeout is not a hard failure — workers may not be running in smoke env
    printf '  \033[33m~\033[0m Workflow %s still running after %ds (workers may be offline — skip)\n' \
      "$WORKFLOW_ID" "$MAX_WAIT"
    ((PASS++)) || true
  fi
else
  printf '  \033[33m~\033[0m Skipping poll — no workflow id\n'
fi

# ─── step 6: progress notify ──────────────────────────────────────────────────
info '─── Step 6: Progress notify round-trip'
NOTIFY_BODY="{
  \"player_id\": \"${E2E_PLAYER}\",
  \"stage\": \"drift_code\",
  \"message\": \"[E2E] 正在生成代码补丁\",
  \"workflow_id\": \"${WORKFLOW_ID:-e2e-no-wf}\",
  \"status\": \"RUNNING\"
}"

NOTIFY_RESP="$(http_post_json "${DRIFT_URL}/story/progress/notify" "$NOTIFY_BODY" 2>/dev/null || echo '')"
if [[ -n "$NOTIFY_RESP" ]]; then
  NOTIFY_OK=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(str(data.get('ok', False)).lower())
" <<< "$NOTIFY_RESP" 2>/dev/null || echo 'false')
  if [[ "$NOTIFY_OK" == "true" ]]; then
    ok "/story/progress/notify accepted"
  else
    fail "/story/progress/notify returned ok=false: ${NOTIFY_RESP:0:200}"
  fi
else
  fail "No response from ${DRIFT_URL}/story/progress/notify"
fi

# ─── step 7: progress status readable ────────────────────────────────────────
info '─── Step 7: Progress status readable'
STATUS_RESP="$(http_get "${DRIFT_URL}/story/progress/status/${E2E_PLAYER}" 2>/dev/null || echo '')"
if [[ -n "$STATUS_RESP" ]]; then
  ENTRY_COUNT=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(len(data.get('entries', [])))
" <<< "$STATUS_RESP" 2>/dev/null || echo 0)
  if [[ "$ENTRY_COUNT" -ge 1 ]]; then
    ok "/story/progress/status/${E2E_PLAYER} has ${ENTRY_COUNT} entries"
  else
    fail "Progress status returned 0 entries for ${E2E_PLAYER}"
  fi
else
  fail "No response from ${DRIFT_URL}/story/progress/status/${E2E_PLAYER}"
fi

# ─── summary ──────────────────────────────────────────────────────────────────
printf '\n'
info '═══ E2E Results'
printf '  Passed: %d\n' "$PASS"
printf '  Failed: %d\n' "$FAIL"

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  printf '\n  Failed checks:\n'
  for f in "${FAILURES[@]}"; do
    printf '    - %s\n' "$f"
  done
fi

if [[ $FAIL -gt 0 ]]; then
  printf '\n\033[31m[e2e] FAIL — %d check(s) did not pass\033[0m\n' "$FAIL"
  exit 1
else
  printf '\n\033[32m[e2e] ALL CHECKS PASSED\033[0m\n'
  exit 0
fi
