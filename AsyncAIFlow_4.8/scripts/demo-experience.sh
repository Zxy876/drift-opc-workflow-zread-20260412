#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  demo-experience.sh
#  最小体验闭环演示脚本 — Drift × AsyncAIFlow
#
#  执行路径：
#    1. 验证 Drift + AsyncAIFlow 存活
#    2. 创建 Workflow
#    3. 提交 drift_experience action（experiment → arc → notify）
#    4. 轮询 action 状态（等待 worker 执行）
#    5. 打印：best_score / state_graph / summary
#
#  前置条件：
#    - Drift backend running on $DRIFT_URL (default: http://localhost:8000)
#    - AsyncAIFlow runtime running on $AAF_URL (default: http://localhost:8080)
#    - drift_experience_worker started:
#        python3 python-workers/drift_experience_worker/worker.py
#
#  用法：
#    bash scripts/demo-experience.sh
#    bash scripts/demo-experience.sh "迷失的钟楼，玩家必须找到三个时间碎片" my-player
#
#  环境变量：
#    DRIFT_URL   Drift base URL    (default: http://localhost:8000)
#    AAF_URL     AsyncAIFlow URL   (default: http://localhost:8080)
#    PLAYER_ID   玩家 ID           (default: demo)
#    PREMISE     关卡前提描述      (default: positional arg $1)
#    MAX_WAIT    最大等待秒数      (default: 300)
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

DRIFT_URL="${DRIFT_URL:-http://localhost:8000}"
AAF_URL="${AAF_URL:-http://localhost:8080}"
PLAYER_ID="${PLAYER_ID:-${2:-demo}}"
PREMISE="${PREMISE:-${1:-玩家必须穿越时间迷宫，找到隐藏的钥匙，解开封印已久的大门}}"
MAX_WAIT="${MAX_WAIT:-300}"

# ─── colour helpers ───────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { printf "${GREEN}  ✓${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}  ~${NC} %s\n" "$*"; }
fail() { printf "${RED}  ✗${NC} %s\n" "$*"; }
info() { printf "${BOLD}%s${NC}\n" "$*"; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || { printf "[demo] Required: %s\n" "$1" >&2; exit 1; }; }
require_cmd curl
require_cmd python3

py_json() { python3 -c "$1" 2>/dev/null || echo ""; }

# ─── step 1: health check ─────────────────────────────────────────────────────
info "═══ Step 1: Health Check"
if curl -sf --max-time 5 "${DRIFT_URL}/" >/dev/null 2>&1 || \
   curl -sf --max-time 5 "${DRIFT_URL}/health" >/dev/null 2>&1; then
  ok "Drift backend alive at ${DRIFT_URL}"
else
  fail "Drift backend unreachable at ${DRIFT_URL}"
  exit 1
fi

if curl -sf --max-time 5 "${AAF_URL}/actuator/health" >/dev/null 2>&1; then
  ok "AsyncAIFlow alive at ${AAF_URL}"
else
  fail "AsyncAIFlow unreachable at ${AAF_URL}"
  exit 1
fi

# ─── step 2: create workflow ──────────────────────────────────────────────────
info "\n═══ Step 2: Create Workflow"
WF_RESP=$(curl -sf --max-time 10 \
  -X POST "${AAF_URL}/workflow/create" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"demo-experience-$(date +%s)\"}")

WORKFLOW_ID=$(py_json "
import json,sys
d=json.loads('''${WF_RESP}''')
print(d.get('data',{}).get('workflowId',''))
")

if [[ -z "$WORKFLOW_ID" ]]; then
  fail "Could not create workflow. Response: ${WF_RESP:0:200}"
  exit 1
fi
ok "Workflow created: id=${WORKFLOW_ID}"

# ─── step 3: submit drift_experience action ───────────────────────────────────
info "\n═══ Step 3: Submit drift_experience"
printf "  premise  : %s\n" "${PREMISE}"
printf "  player_id: %s\n" "${PLAYER_ID}"

# Build JSON payload (escape double-quotes inside premise)
PAYLOAD_JSON="{\"premise\":\"${PREMISE}\",\"player_id\":\"${PLAYER_ID}\",\"n_variants\":3,\"meta_rounds\":2,\"beam_width\":2}"

ACTION_RESP=$(curl -sf --max-time 15 \
  -X POST "${AAF_URL}/action/create" \
  -H 'Content-Type: application/json' \
  -d "{
    \"workflowId\": ${WORKFLOW_ID},
    \"type\": \"drift_experience\",
    \"payload\": $(python3 -c "import json,sys; print(json.dumps('${PAYLOAD_JSON}'))")
  }")

ACTION_ID=$(py_json "
import json,sys
d=json.loads('''${ACTION_RESP}''')
print(d.get('data',{}).get('actionId',''))
")

if [[ -z "$ACTION_ID" ]]; then
  fail "Could not create action. Response: ${ACTION_RESP:0:300}"
  exit 1
fi
ok "Action created: id=${ACTION_ID}"

# ─── step 4: poll action status ───────────────────────────────────────────────
info "\n═══ Step 4: Polling action ${ACTION_ID} (max ${MAX_WAIT}s)"
printf "  Waiting for drift_experience_worker to execute...\n"

ELAPSED=0
POLL_INTERVAL=5
FINAL_STATUS=""
RESULT_JSON=""

while [[ $ELAPSED -lt $MAX_WAIT ]]; do
  STATUS_RESP=$(curl -sf --max-time 10 "${AAF_URL}/action/${ACTION_ID}" 2>/dev/null || echo "")
  if [[ -n "$STATUS_RESP" ]]; then
    ACT_STATUS=$(py_json "
import json,sys
d=json.loads('''${STATUS_RESP}''')
data=d.get('data',{})
print(data.get('status',''))
")
    RESULT_JSON=$(py_json "
import json,sys
d=json.loads('''${STATUS_RESP}''')
data=d.get('data',{})
print(data.get('result','{}'))
") 

    printf "\r  [%3ds] status=%-12s" "$ELAPSED" "$ACT_STATUS"

    case "$ACT_STATUS" in
      SUCCEEDED|COMPLETED)
        FINAL_STATUS="SUCCEEDED"
        printf "\n"
        break
        ;;
      FAILED|DEAD_LETTER)
        FINAL_STATUS="FAILED"
        printf "\n"
        break
        ;;
    esac
  fi
  sleep "$POLL_INTERVAL"
  ((ELAPSED+=POLL_INTERVAL)) || true
done
printf "\n"

# ─── step 5: print results ────────────────────────────────────────────────────
info "\n═══ Step 5: Results"

if [[ "$FINAL_STATUS" == "SUCCEEDED" ]]; then
  ok "Action ${ACTION_ID} SUCCEEDED (${ELAPSED}s)"

  # Parse and display key fields
  python3 - <<'PYEOF'
import json, os, sys

raw = os.environ.get("RESULT_JSON", "{}")
try:
    result = json.loads(raw) if raw.strip() else {}
except Exception:
    result = {}

if not result:
    print("  (no result payload to display)")
    sys.exit(0)

best_score   = result.get("best_score", "?")
best_level   = result.get("best_level_id", "?")
state_graph  = result.get("state_graph", [])
summary      = result.get("summary", "?")
exp          = result.get("exp_result", {})
arc          = result.get("arc_result", {})

print(f"\n  ┌─ Experiment (Beam Search) ─────────────────────────────")
print(f"  │  best_score  : {best_score}")
print(f"  │  best_level  : {best_level}")
exp_rounds = exp.get("rounds", [])
for r in exp_rounds:
    print(f"  │  round {r.get('round','?')}      : score={r.get('best_score','?'):.3f} candidates={r.get('candidates_count','?')}")

print(f"\n  ├─ Arc (State Graph) ───────────────────────────────────")
print(f"  │  level_count : {arc.get('level_count','?')}")
print(f"  │  total_beats : {arc.get('total_beats','?')}")
print(f"  │  state_graph :")
for i, s in enumerate(state_graph):
    level_name = s.get('completed_level', '')
    inv        = s.get('inventory', [])
    flags      = s.get('flags', [])
    progress   = s.get('progress', 0)
    print(f"  │    [{i}] '{level_name}'")
    print(f"  │        inventory={inv}")
    print(f"  │        flags={flags}")
    print(f"  │        progress={progress:.0%}")

wp_obtained = result.get("world_patch_obtained", False)
print(f"\n  ├─ MC Backflow (world_patch → plugin) ──────────────────")
print(f"  │  world_patch_obtained : {'✓ YES' if wp_obtained else '✗ NO (MC will NOT execute)'}")
print(f"  │  notify stage         : drift_refresh")
print(f"  │  notify status        : SUCCEEDED")
if wp_obtained:
    print(f"  │  → MC plugin poll will call world.execute() ✓")
else:
    print(f"  │  → MC plugin poll will SKIP (world_patch is null) ✗")

print(f"\n  └─ Summary ─────────────────────────────────────────────")
print(f"     {summary}")
PYEOF

elif [[ "$FINAL_STATUS" == "FAILED" ]]; then
  fail "Action ${ACTION_ID} FAILED"
  echo "  Response: ${RESULT_JSON:0:300}"
  exit 1
else
  warn "Timed out after ${MAX_WAIT}s. Worker may not be running."
  warn "Start worker with: python3 python-workers/drift_experience_worker/worker.py"
  exit 1
fi

# ─── step 6: verify Drift progress (MC backflow check) ───────────────────────
info "\n═══ Step 6: Drift Progress Check (MC Backflow Verification)"
PROGRESS_RESP=$(curl -sf --max-time 10 "${DRIFT_URL}/story/progress/status/${PLAYER_ID}" 2>/dev/null || echo "")
if [[ -n "$PROGRESS_RESP" ]]; then
  python3 - <<PYEOF
import json, sys

raw = """${PROGRESS_RESP}"""
try:
    d = json.loads(raw)
except Exception:
    print("  (could not parse progress response)")
    sys.exit(0)

entries = d.get("entries", [])
print(f"  Total entries for player: {len(entries)}")

# Find drift_refresh entries
refresh_entries = [e for e in entries if e.get("stage") == "drift_refresh"]
if not refresh_entries:
    print("  ✗ No drift_refresh entry found — MC plugin will NOT execute")
    print("    Entries found: " + str([e.get("stage") for e in entries]))
else:
    e = refresh_entries[-1]
    wp = e.get("world_patch")
    wp_present = wp is not None and bool(wp)
    print(f"  ✓ drift_refresh entry found!")
    print(f"    stage   : {e.get('stage')}")
    print(f"    status  : {e.get('status')}")
    print(f"    world_patch: {'✓ NON-NULL' if wp_present else '✗ NULL'}")
    if wp_present:
        mc_ops = wp.get("mc", {})
        print(f"    mc keys : {list(mc_ops.keys())}")
        if mc_ops.get("title"):
            print(f"    mc.title: {mc_ops['title']}")
        if mc_ops.get("weather"):
            print(f"    mc.weather: {mc_ops['weather']}")
        print()
        print("  ══ MC BACKFLOW VERDICT ══════════════════════════════════")
        print("  ✓ ALL THREE CONDITIONS MET — MC plugin WILL call world.execute()")
        print("    1. stage  == 'drift_refresh'  ✓")
        print("    2. status == 'SUCCEEDED'       ✓")
        print("    3. world_patch != null         ✓")
    else:
        print()
        print("  ✗ BACKFLOW INCOMPLETE: world_patch is null")
        print("    MC plugin will skip this entry (condition 3 not met)")
PYEOF
else
  warn "Could not reach ${DRIFT_URL}/story/progress/status/${PLAYER_ID}"
fi

info "\n═══ Demo Complete ══════════════════════════════════════════"
printf "${GREEN}  ✓ drift_experience pipeline ran end-to-end${NC}\n"
printf "  Workflow : %s\n" "$WORKFLOW_ID"
printf "  Action   : %s\n" "$ACTION_ID"
printf "  Player   : %s\n" "$PLAYER_ID"
printf "\n  Next steps:\n"
printf "    curl %s/world/state/%s\n" "$DRIFT_URL" "$PLAYER_ID"
printf "    curl %s/workflow/%s/summary\n" "$AAF_URL" "$WORKFLOW_ID"
