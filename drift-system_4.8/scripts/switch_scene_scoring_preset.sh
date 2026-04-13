#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SCENE_DIR="${ROOT_DIR}/backend/app/content/scenes"
PRESET_DIR="${SCENE_DIR}/presets"
TARGET_FILE="${SCENE_DIR}/semantic_scoring.json"
ACTIVE_FILE="${SCENE_DIR}/.active_scene_scoring_preset"

PRESETS=("high_control" "balanced" "emergent")

usage() {
  cat <<'USAGE'
用法:
  ./scripts/switch_scene_scoring_preset.sh <preset> [--restart]
  ./scripts/switch_scene_scoring_preset.sh status
  ./scripts/switch_scene_scoring_preset.sh list

preset:
  high_control  - 玩家可强力“刷资源控场景”
  balanced      - 默认平衡（当前线上默认）
  emergent      - 更强调演化与多样性

选项:
  --restart     - 切换后自动执行 ./stop_all.sh && ./start_all.sh
USAGE
}

is_valid_preset() {
  local preset="$1"
  for p in "${PRESETS[@]}"; do
    if [[ "$p" == "$preset" ]]; then
      return 0
    fi
  done
  return 1
}

preset_file() {
  local preset="$1"
  echo "${PRESET_DIR}/semantic_scoring.${preset}.json"
}

detect_active_preset() {
  if [[ ! -f "$TARGET_FILE" ]]; then
    echo "missing"
    return
  fi

  for p in "${PRESETS[@]}"; do
    local f
    f="$(preset_file "$p")"
    if [[ -f "$f" ]] && cmp -s "$TARGET_FILE" "$f"; then
      echo "$p"
      return
    fi
  done

  echo "custom"
}

validate_json() {
  local file="$1"
  python3 - <<'PY' "$file"
import json
import sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    json.load(f)
print(f"JSON ok: {path}")
PY
}

restart_services() {
  echo "[switch] restarting services..."
  if [[ ! -x "${ROOT_DIR}/stop_all.sh" || ! -x "${ROOT_DIR}/start_all.sh" ]]; then
    echo "[switch] skip restart: stop_all.sh/start_all.sh 不可执行"
    return
  fi
  (
    cd "$ROOT_DIR"
    ./stop_all.sh
    ./start_all.sh
  )
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

command="$1"
shift || true

case "$command" in
  list)
    echo "available presets: ${PRESETS[*]}"
    exit 0
    ;;
  status)
    active="$(detect_active_preset)"
    echo "active preset: ${active}"
    if [[ -f "$ACTIVE_FILE" ]]; then
      echo "last switched record: $(cat "$ACTIVE_FILE")"
    fi
    exit 0
    ;;
  -h|--help)
    usage
    exit 0
    ;;
esac

preset="$command"
restart_after_switch="false"
if [[ "${1:-}" == "--restart" ]]; then
  restart_after_switch="true"
fi

if ! is_valid_preset "$preset"; then
  echo "[switch] unknown preset: $preset" >&2
  usage
  exit 1
fi

src_file="$(preset_file "$preset")"
if [[ ! -f "$src_file" ]]; then
  echo "[switch] preset file not found: $src_file" >&2
  exit 1
fi

if [[ -f "$TARGET_FILE" ]]; then
  backup_file="${TARGET_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
  cp "$TARGET_FILE" "$backup_file"
  echo "[switch] backup created: $backup_file"
fi

cp "$src_file" "$TARGET_FILE"
validate_json "$TARGET_FILE"

{
  echo "preset=${preset}"
  echo "switched_at=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "target=${TARGET_FILE}"
} > "$ACTIVE_FILE"

active="$(detect_active_preset)"
echo "[switch] active preset: ${active}"
echo "[switch] current config: ${TARGET_FILE}"
echo "[switch] 注意: Python 进程有评分配置缓存，建议重启后端使配置生效。"
echo "[switch] 手动重启命令: ./stop_all.sh && ./start_all.sh"

if [[ "$restart_after_switch" == "true" ]]; then
  restart_services
fi
