#!/usr/bin/env bash
# =============================================================================
# demo-stop.sh — 停止所有由 demo-start.sh 启动的服务
# 包括: Drift backend, AsyncAIFlow runtime + 4 workers, Docker services
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
DEMO_PID_FILE="${LOG_DIR}/demo-start.pids"

log()  { printf '[demo-stop] %s\n' "$*"; }
warn() { printf '[demo-stop] WARNING: %s\n' "$*" >&2; }

stop_pid() {
  local name="$1" pid="$2"

  [[ -z "${pid}" ]] && return 0
  [[ "${pid}" =~ ^[0-9]+$ ]] || { warn "invalid pid for ${name}: ${pid}"; return 0; }

  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    log "  ${name} already stopped (pid=${pid})"
    return 0
  fi

  log "  stopping ${name} (pid=${pid})..."
  kill "${pid}" >/dev/null 2>&1 || true

  for _ in {1..10}; do
    kill -0 "${pid}" >/dev/null 2>&1 || { log "  ✓ ${name} stopped"; return 0; }
    sleep 1
  done

  warn "${name} did not stop — sending SIGKILL..."
  kill -9 "${pid}" >/dev/null 2>&1 || true
}

kill_port() {
  local port="$1"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    log "  killing leftover process on :${port}..."
    lsof -ti tcp:"${port}" | xargs kill -9 2>/dev/null || true
  fi
}

# ── 按 PID 文件停止 ──────────────────────────────────────────────────────────
printf '\n'
log "=== 停止 demo 服务 ==="

if [[ -f "${DEMO_PID_FILE}" ]]; then
  while IFS=':' read -r name pid; do
    [[ -z "${name}" ]] && continue
    stop_pid "${name}" "${pid}"
  done < "${DEMO_PID_FILE}"
  rm -f "${DEMO_PID_FILE}"
else
  log "  未找到 PID 文件 (${DEMO_PID_FILE})"
fi

# ── 调用 dev-stop.sh 清理 AsyncAIFlow Java 进程 ──────────────────────────────
log "  运行 dev-stop.sh 清理 AsyncAIFlow Java 进程..."
"${SCRIPT_DIR}/dev-stop.sh" >/dev/null 2>&1 || true

# ── 按端口 kill 确保干净 (dev-stop.sh 不处理 Drift 和 JAR 模式进程) ─────────
kill_port 8000   # Drift backend
kill_port 8080   # AsyncAIFlow runtime (JAR 模式)

log "  ✓ 所有服务已停止"
