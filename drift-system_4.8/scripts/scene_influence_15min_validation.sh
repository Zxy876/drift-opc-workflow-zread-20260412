#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SWITCH_SCRIPT="${ROOT_DIR}/scripts/switch_scene_scoring_preset.sh"

PRESET="high_control"
PLAYER="vivn"
DO_SWITCH="false"
DO_RESTART="false"
USE_CLIPBOARD="true"
HAS_PBCOPY="false"

if command -v pbcopy >/dev/null 2>&1; then
  HAS_PBCOPY="true"
fi

usage() {
  cat <<'USAGE'
用法:
  ./scripts/scene_influence_15min_validation.sh [preset] [--switch] [--restart] [--player <name>] [--no-clipboard]

参数:
  preset          high_control | balanced | emergent（默认 high_control）

选项:
  --switch        测试前自动执行预设切换
  --restart       与 --switch 一起使用，切换后自动重启服务
  --player <name> 报告中记录玩家名（默认 vivn）
  --no-clipboard  不自动复制命令到剪贴板
USAGE
}

is_valid_preset() {
  case "$1" in
    high_control|balanced|emergent) return 0 ;;
    *) return 1 ;;
  esac
}

normalize_token() {
  local raw="$1"
  echo "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[[:space:]-]+/_/g; s/^_+//; s/_+$//'
}

copy_command() {
  local cmd="$1"
  if [[ "$USE_CLIPBOARD" == "true" && "$HAS_PBCOPY" == "true" ]]; then
    printf "%s" "$cmd" | pbcopy
    echo "   (已复制到剪贴板)"
  fi
}

wait_enter() {
  read -r -p "   完成后按回车继续..." _
}

run_command_step() {
  local title="$1"
  local cmd="$2"
  echo
  echo "▶ ${title}"
  echo "   ${cmd}"
  copy_command "$cmd"
  wait_enter
}

run_manual_step() {
  local title="$1"
  echo
  echo "▶ ${title}"
  wait_enter
}

append_array() {
  local array_name="$1"
  local value="$2"
  eval "$array_name+=(\"\$value\")"
}

array_csv() {
  local array_name="$1"
  local arr=()
  eval "arr=(\"\${${array_name}[@]}\")"
  local out=""
  local i
  for ((i = 0; i < ${#arr[@]}; i++)); do
    if [[ -z "$out" ]]; then
      out="${arr[$i]}"
    else
      out="${out}, ${arr[$i]}"
    fi
  done
  if [[ -z "$out" ]]; then
    out="(none)"
  fi
  echo "$out"
}

count_hits() {
  local array_name="$1"
  shift
  local arr=()
  eval "arr=(\"\${${array_name}[@]}\")"
  local count=0
  local item expected
  for item in "${arr[@]}"; do
    for expected in "$@"; do
      if [[ "$item" == "$expected" ]]; then
        count=$((count + 1))
        break
      fi
    done
  done
  echo "$count"
}

capture_root() {
  local phase="$1"
  local round="$2"
  local array_name="$3"
  local observed=""

  echo
  read -r -p "   [${phase} R${round}] 输入本轮 selected_root: " observed
  observed="$(normalize_token "$observed")"
  if [[ -z "$observed" ]]; then
    observed="unknown"
  fi
  append_array "$array_name" "$observed"
  echo "   已记录 root=${observed}"
}

run_phase_round() {
  local phase="$1"
  local round="$2"
  local profile="$3"
  local array_name="$4"

  echo
  echo "------------------------------------------------------------"
  echo "${phase} | Round ${round}/2"
  echo "------------------------------------------------------------"

  run_command_step "重置运行态" "/storyreset"

  if [[ "$profile" == "trade" ]]; then
    run_command_step "投放翡翠" '/summon item ~ ~1 ~ {Item:{id:"minecraft:emerald",Count:32b}}'
    run_command_step "投放面包" '/summon item ~ ~1 ~ {Item:{id:"minecraft:bread",Count:16b}}'
    run_command_step "投放木头" '/summon item ~ ~1 ~ {Item:{id:"minecraft:oak_log",Count:16b}}'
    run_manual_step "在游戏里走动并拾取所有掉落物（确保触发 collect 事件）"
  elif [[ "$profile" == "forge" ]]; then
    run_command_step "投放铁锭" '/summon item ~ ~1 ~ {Item:{id:"minecraft:iron_ingot",Count:32b}}'
    run_command_step "投放石头" '/summon item ~ ~1 ~ {Item:{id:"minecraft:stone",Count:32b}}'
    run_command_step "投放营火" '/summon item ~ ~1 ~ {Item:{id:"minecraft:campfire",Count:8b}}'
    run_manual_step "在游戏里走动并拾取所有掉落物（确保触发 collect 事件）"
  elif [[ "$profile" == "camp" ]]; then
    run_command_step "投放木头" '/summon item ~ ~1 ~ {Item:{id:"minecraft:oak_log",Count:32b}}'
    run_command_step "投放火把" '/summon item ~ ~1 ~ {Item:{id:"minecraft:torch",Count:32b}}'
    run_command_step "投放生猪排" '/summon item ~ ~1 ~ {Item:{id:"minecraft:raw_porkchop",Count:16b}}'
    run_manual_step "在游戏里走动并拾取所有掉落物（确保触发 collect 事件）"
  fi

  run_command_step "生成场景" "/spawnfragment"
  run_command_step "查看影响与根节点" "/debuginventory"
  capture_root "$phase" "$round" "$array_name"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    high_control|balanced|emergent)
      PRESET="$1"
      shift
      ;;
    --switch)
      DO_SWITCH="true"
      shift
      ;;
    --restart)
      DO_SWITCH="true"
      DO_RESTART="true"
      shift
      ;;
    --player)
      PLAYER="${2:-}"
      if [[ -z "$PLAYER" ]]; then
        echo "--player 需要一个玩家名" >&2
        exit 1
      fi
      shift 2
      ;;
    --no-clipboard)
      USE_CLIPBOARD="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! is_valid_preset "$PRESET"; then
  echo "无效 preset: $PRESET" >&2
  exit 1
fi

if [[ "$DO_SWITCH" == "true" ]]; then
  if [[ ! -x "$SWITCH_SCRIPT" ]]; then
    echo "未找到切换脚本: $SWITCH_SCRIPT" >&2
    exit 1
  fi
  echo
  echo "[setup] 切换评分预设 -> $PRESET"
  if [[ "$DO_RESTART" == "true" ]]; then
    "$SWITCH_SCRIPT" "$PRESET" --restart
  else
    "$SWITCH_SCRIPT" "$PRESET"
  fi
fi

echo
echo "============================================================"
echo "DriftSystem 15分钟内测脚本（逐步执行版）"
echo "============================================================"
echo "preset : $PRESET"
echo "player : $PLAYER"
echo "提示   : collect 依赖“拾取地面掉落物”，不是 /give。"
echo
echo "建议先在游戏中准备好命令面板。"
wait_enter

baseline_roots=()
trade_roots=()
forge_roots=()
camp_roots=()

echo
echo "[00:00 - 03:00] Phase A 基线（无定向刷资源）"
run_phase_round "Phase A Baseline" 1 "baseline" baseline_roots
run_phase_round "Phase A Baseline" 2 "baseline" baseline_roots

echo
echo "[03:00 - 07:00] Phase B 贸易导向（目标 market/village）"
run_phase_round "Phase B Trade" 1 "trade" trade_roots
run_phase_round "Phase B Trade" 2 "trade" trade_roots

echo
echo "[07:00 - 11:00] Phase C 锻造导向（目标 forge）"
run_phase_round "Phase C Forge" 1 "forge" forge_roots
run_phase_round "Phase C Forge" 2 "forge" forge_roots

echo
echo "[11:00 - 15:00] Phase D 营地导向（目标 camp）"
run_phase_round "Phase D Camp" 1 "camp" camp_roots
run_phase_round "Phase D Camp" 2 "camp" camp_roots

required_hits=1
if [[ "$PRESET" == "high_control" ]]; then
  required_hits=2
fi

trade_hits="$(count_hits trade_roots market village)"
forge_hits="$(count_hits forge_roots forge)"
camp_hits="$(count_hits camp_roots camp)"

trade_pass="false"
forge_pass="false"
camp_pass="false"
overall_pass="false"

if [[ "$trade_hits" -ge "$required_hits" ]]; then
  trade_pass="true"
fi
if [[ "$forge_hits" -ge "$required_hits" ]]; then
  forge_pass="true"
fi
if [[ "$camp_hits" -ge "$required_hits" ]]; then
  camp_pass="true"
fi
if [[ "$trade_pass" == "true" && "$forge_pass" == "true" && "$camp_pass" == "true" ]]; then
  overall_pass="true"
fi

REPORT_DIR="${ROOT_DIR}/logs/playtest"
mkdir -p "$REPORT_DIR"
REPORT_FILE="${REPORT_DIR}/scene_influence_playtest_${PRESET}_$(date +%Y%m%d_%H%M%S).md"

{
  echo "# Scene Influence 内测报告"
  echo
  echo "- player: ${PLAYER}"
  echo "- preset: ${PRESET}"
  echo "- required_hits_per_phase: ${required_hits}/2"
  echo "- generated_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  echo "## Root 记录"
  echo "- baseline_roots: $(array_csv baseline_roots)"
  echo "- trade_roots: $(array_csv trade_roots)"
  echo "- forge_roots: $(array_csv forge_roots)"
  echo "- camp_roots: $(array_csv camp_roots)"
  echo
  echo "## 判定"
  echo "- trade_hits: ${trade_hits}/2 (目标: market|village) -> ${trade_pass}"
  echo "- forge_hits: ${forge_hits}/2 (目标: forge) -> ${forge_pass}"
  echo "- camp_hits: ${camp_hits}/2 (目标: camp) -> ${camp_pass}"
  echo "- overall_pass: ${overall_pass}"
} > "$REPORT_FILE"

echo
echo "====================== 测试完成 ======================"
echo "baseline roots : $(array_csv baseline_roots)"
echo "trade roots    : $(array_csv trade_roots)"
echo "forge roots    : $(array_csv forge_roots)"
echo "camp roots     : $(array_csv camp_roots)"
echo
echo "trade hits: ${trade_hits}/2  (target market|village)"
echo "forge hits: ${forge_hits}/2  (target forge)"
echo "camp  hits: ${camp_hits}/2  (target camp)"
echo "required : ${required_hits}/2 per guided phase"
echo "overall  : ${overall_pass}"
echo "report   : ${REPORT_FILE}"
