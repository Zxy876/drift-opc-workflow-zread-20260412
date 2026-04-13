#!/usr/bin/env bash
# =============================================================================
# demo-start.sh — AsyncAIFlow + Drift 一键 Demo 启动脚本
# 目标：任何机器上 100% 可复现的演示环境，使用 JAR 直启（不依赖 Maven）
#
# 启动顺序：
#   1. 停止所有旧进程
#   2. 启动基础设施 (MySQL + Redis: 优先 Docker，否则要求本地已运行)
#   3. 清理过期 action 状态 (QUEUED/RUNNING → BLOCKED)
#   4. 启动 Drift 后端 (FastAPI / uvicorn :8000)
#   5. 启动 AsyncAIFlow Runtime (JAR :8080)
#   6. 启动 Java Workers (repository / gpt / git)
#   7. 启动 drift_trigger_worker (Python)
#   8. 验证所有 worker 已注册
#
# 环境变量 (可选):
#   DRIFT_ROOT          Drift 代码库绝对路径
#   ASYNCAIFLOW_URL     AsyncAIFlow 地址 (default: http://localhost:8080)
#   DRIFT_URL           Drift API 地址   (default: http://localhost:8000)
#   SPRING_DATASOURCE_PASSWORD  覆盖 MySQL 密码 (Docker 模式默认 root)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 路径配置 (支持跨机器覆盖) ─────────────────────────────────────────────────
DRIFT_ROOT="${DRIFT_ROOT:-/Users/zxydediannao/ 4.8opcworkflow/drift-system-clean（very important）_4.8}"
LOG_DIR="${PROJECT_ROOT}/logs"
JAR="${PROJECT_ROOT}/target/asyncaiflow-0.1.0-SNAPSHOT.jar"
DRIFT_TRIGGER_WORKER="${PROJECT_ROOT}/python-workers/drift_trigger_worker/worker.py"
DRIFT_BACKEND_DIR="${DRIFT_ROOT}/backend"
ASYNCAIFLOW_URL="${ASYNCAIFLOW_URL:-http://localhost:8080}"
DRIFT_URL="${DRIFT_URL:-http://localhost:8000}"
DB_NAME="asyncaiflow"
DB_USER="root"

DEMO_PID_FILE="${LOG_DIR}/demo-start.pids"
DEV_PID_FILE="${LOG_DIR}/dev-start.pids"

# ── 工具函数 ──────────────────────────────────────────────────────────────────
log()  { printf '[demo-start] %s\n' "$*"; }
warn() { printf '[demo-start] WARNING: %s\n' "$*" >&2; }
die()  { printf '\n[demo-start] ERROR: %s\n' "$*" >&2; exit 1; }

save_pid() { printf '%s:%s\n' "$1" "$2" >> "${DEMO_PID_FILE}"; }

is_port_open() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

kill_port() {
  local port="$1"
  if is_port_open "${port}"; then
    log "port :${port} in use — killing existing process..."
    lsof -ti tcp:"${port}" | xargs kill 2>/dev/null || true
    sleep 1
    if is_port_open "${port}"; then
      lsof -ti tcp:"${port}" | xargs kill -9 2>/dev/null || true
      sleep 1
    fi
  fi
}

wait_http() {
  local name="$1" url="$2" timeout="${3:-90}"
  local deadline=$((SECONDS + timeout))
  log "  → 等待 ${name} 就绪 (最多 ${timeout}s)..."
  while (( SECONDS < deadline )); do
    if curl -s --noproxy '*' --connect-timeout 1 --max-time 3 \
        -o /dev/null "${url}" 2>/dev/null; then
      log "  ✓ ${name} 已就绪"
      return 0
    fi
    sleep 2
  done
  die "${name} 在 ${timeout}s 内未响应 — 查看日志: ${LOG_DIR}/"
}

wait_worker() {
  local name="$1" worker_id="$2" timeout="${3:-60}"
  local deadline=$((SECONDS + timeout))
  log "  → 等待 worker 注册: ${name} (${worker_id})..."
  while (( SECONDS < deadline )); do
    local code
    code=$(curl -sS --noproxy '*' --connect-timeout 2 --max-time 5 \
      -H 'Content-Type: application/json' \
      -d "{\"workerId\":\"${worker_id}\"}" \
      -o /dev/null -w "%{http_code}" \
      "${ASYNCAIFLOW_URL}/worker/heartbeat" 2>/dev/null || printf '000')
    if [[ "${code}" == "200" ]]; then
      log "  ✓ ${name} 已注册"
      return 0
    fi
    sleep 2
  done
  warn "${name} 未在 ${timeout}s 内注册 — 继续 (检查日志确认)"
}

mkdir -p "${LOG_DIR}"
: > "${DEMO_PID_FILE}"

# ── Step 1: 停止所有现有进程 ────────────────────────────────────────────────────
printf '\n'
log "=== [1/8] 停止现有进程 ==="

# dev-stop.sh 清理 AsyncAIFlow Java 进程 + Docker 服务 (仅停不删)
"${SCRIPT_DIR}/dev-stop.sh" >/dev/null 2>&1 || true

# 也清除 dev-start.pids，防止后续 dev-stop.sh 混淆
: > "${DEV_PID_FILE}" 2>/dev/null || true

# 直接按端口 kill，确保干净 (dev-stop.sh 不处理 Drift)
kill_port 8080   # AsyncAIFlow runtime (JAR 模式启动时不在 dev-start.pids 中)
kill_port 8000   # Drift FastAPI backend

log "  进程清理完成"

# ── Step 2: 启动基础设施 (MySQL + Redis) ────────────────────────────────────────
printf '\n'
log "=== [2/8] 启动基础设施 ==="

USE_DOCKER=false
DB_PASS=""

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "  Docker 可用 — 使用 docker compose 启动 MySQL + Redis"
  (cd "${PROJECT_ROOT}" && docker compose up -d mysql redis >/dev/null 2>&1)

  # 等待 MySQL 健康
  log "  → 等待 MySQL 容器健康..."
  deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    cid=$(cd "${PROJECT_ROOT}" && docker compose ps -q mysql 2>/dev/null || true)
    if [[ -n "${cid}" ]]; then
      status=$(docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' \
        "${cid}" 2>/dev/null || true)
      if [[ "${status}" == "healthy" ]]; then
        log "  ✓ MySQL 健康"
        break
      fi
    fi
    sleep 2
  done

  # 等待 Redis
  log "  → 等待 Redis..."
  deadline=$((SECONDS + 30))
  while (( SECONDS < deadline )); do
    if (cd "${PROJECT_ROOT}" && \
        docker compose exec -T redis redis-cli ping >/dev/null 2>&1); then
      log "  ✓ Redis 就绪"
      break
    fi
    sleep 1
  done

  USE_DOCKER=true
  DB_PASS="${SPRING_DATASOURCE_PASSWORD:-root}"

else
  log "  Docker 不可用 — 使用本地 MySQL:3306 / Redis:6379"
  is_port_open 3306 || die "MySQL 未在 :3306 运行，且 Docker 不可用"
  is_port_open 6379 || die "Redis 未在 :6379 运行，且 Docker 不可用"
  DB_PASS="${SPRING_DATASOURCE_PASSWORD:-}"
  log "  ✓ 本地 MySQL + Redis 已就绪"
fi

# ── Step 3: 清理过期 action 状态 ────────────────────────────────────────────────
printf '\n'
log "=== [3/8] 清理过期 action 状态 ==="

_db_cleanup_sql="UPDATE action SET status='BLOCKED' WHERE status IN ('QUEUED','RUNNING');"

if [[ "${USE_DOCKER}" == "true" ]]; then
  (cd "${PROJECT_ROOT}" && docker compose exec -T mysql \
    mysql -uroot -p"${DB_PASS}" "${DB_NAME}" \
    -e "${_db_cleanup_sql}") >/dev/null 2>&1 \
    || warn "DB 清理跳过 (首次启动表尚未创建，属正常)"
else
  if [[ -n "${DB_PASS}" ]]; then
    mysql -u"${DB_USER}" -p"${DB_PASS}" "${DB_NAME}" \
      -e "${_db_cleanup_sql}" >/dev/null 2>&1 \
      || warn "DB 清理跳过 (首次启动或密码不匹配)"
  else
    mysql -u"${DB_USER}" "${DB_NAME}" \
      -e "${_db_cleanup_sql}" >/dev/null 2>&1 \
      || warn "DB 清理跳过 (首次启动表尚未创建，属正常)"
  fi
fi
log "  ✓ 过期 action 状态已重置 (QUEUED/RUNNING → BLOCKED)"

# ── Step 4: 启动 Drift 后端 ─────────────────────────────────────────────────────
printf '\n'
log "=== [4/8] 启动 Drift 后端 (FastAPI :8000) ==="

if [[ ! -d "${DRIFT_BACKEND_DIR}" ]]; then
  die "Drift 后端目录不存在: ${DRIFT_BACKEND_DIR}\n  请设置环境变量: export DRIFT_ROOT=/path/to/drift-system"
fi

DRIFT_VENV="${DRIFT_BACKEND_DIR}/venv"
if [[ ! -f "${DRIFT_VENV}/bin/uvicorn" ]]; then
  log "  首次安装 Drift 依赖 (请稍候)..."
  python3 -m venv "${DRIFT_VENV}"
  "${DRIFT_VENV}/bin/pip" install -q -r "${DRIFT_BACKEND_DIR}/requirements.txt"
  log "  ✓ Drift 依赖安装完成"
fi

(
  cd "${DRIFT_BACKEND_DIR}"
  "${DRIFT_VENV}/bin/uvicorn" app.main:app \
    --host 127.0.0.1 --port 8000 \
    >> "${LOG_DIR}/drift-backend.log" 2>&1
) &
drift_pid=$!
save_pid drift-backend "${drift_pid}"
log "  Drift backend PID: ${drift_pid}"

wait_http "Drift backend" "${DRIFT_URL}/" 60

# ── Step 5: 启动 AsyncAIFlow Runtime ────────────────────────────────────────────
printf '\n'
log "=== [5/8] 启动 AsyncAIFlow Runtime (JAR :8080) ==="

if [[ ! -f "${JAR}" ]]; then
  die "JAR 不存在: ${JAR}\n  请先构建: cd '${PROJECT_ROOT}' && mvn -q package -DskipTests"
fi

# 按需传入 DB 密码 (空密码不传，保持 application.yml 默认)
if [[ -n "${DB_PASS}" ]]; then
  nohup java -jar "${JAR}" \
    --spring.datasource.password="${DB_PASS}" \
    >> "${LOG_DIR}/asyncaiflow-runtime.log" 2>&1 &
else
  nohup java -jar "${JAR}" \
    >> "${LOG_DIR}/asyncaiflow-runtime.log" 2>&1 &
fi
runtime_pid=$!
save_pid asyncaiflow-runtime "${runtime_pid}"
log "  Runtime PID: ${runtime_pid}"

wait_http "AsyncAIFlow runtime" "${ASYNCAIFLOW_URL}/action/poll?workerId=demo-probe" 120

# ── Step 6: 启动 Java Workers ────────────────────────────────────────────────────
printf '\n'
log "=== [6/8] 启动 Java Workers ==="

log "  启动 repository-worker..."
nohup java -cp "${JAR}" \
  -Dloader.main=com.asyncaiflow.worker.repository.RepositoryWorkerApplication \
  "-Dasyncaiflow.repository-worker.repository.workspace-root=${DRIFT_ROOT}" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=repository-worker \
  >> "${LOG_DIR}/repository-worker.log" 2>&1 &
save_pid repository-worker $!
log "  repository-worker PID: $!"

log "  启动 gpt-worker..."

# ── 加载 LLM 密钥（从 .aiflow/config.json，与 dev-start.sh 保持一致）────────────────
AIFLOW_CONFIG="${PROJECT_ROOT}/.aiflow/config.json"
if [[ -f "${AIFLOW_CONFIG}" ]]; then
  _openai_key=$(python3 -c "import json,sys; d=json.load(open('${AIFLOW_CONFIG}')); print(d.get('openai_api_key',''))" 2>/dev/null || echo "")
  _glm_key=$(python3 -c "import json,sys; d=json.load(open('${AIFLOW_CONFIG}')); print(d.get('llm_api_key',''))" 2>/dev/null || echo "")
  _deepseek_key=$(python3 -c "import json,sys; d=json.load(open('${AIFLOW_CONFIG}')); print(d.get('deepseek_api_key',''))" 2>/dev/null || echo "")
  [[ -n "${_openai_key}" ]]  && export OPENAI_API_KEY="${_openai_key}"   && log "  ✅ OPENAI_API_KEY loaded"
  [[ -n "${_glm_key}" ]]     && export GLM_API_KEY="${_glm_key}"         && log "  ✅ GLM_API_KEY loaded"
  [[ -n "${_deepseek_key}" ]] && export DEEPSEEK_API_KEY="${_deepseek_key}" && log "  ✅ DEEPSEEK_API_KEY loaded"
  unset _openai_key _glm_key _deepseek_key
else
  warn ".aiflow/config.json not found — gpt-worker will use mock fallback"
fi
# ────────────────────────────────────────────────────────────────────────────────

nohup java -cp "${JAR}" \
  -Dloader.main=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dasyncaiflow.gpt-worker.llm.mock-fallback-enabled=false \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=gpt-worker \
  >> "${LOG_DIR}/gpt-worker.log" 2>&1 &
save_pid gpt-worker $!
log "  gpt-worker PID: $!"

log "  启动 git-worker..."
nohup java -cp "${JAR}" \
  -Dloader.main=com.asyncaiflow.worker.git.GitWorkerApplication \
  "-Dasyncaiflow.git-worker.repository.workspace-root=${DRIFT_ROOT}" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=git-worker \
  >> "${LOG_DIR}/git-worker.log" 2>&1 &
save_pid git-worker $!
log "  git-worker PID: $!"

# ── Step 7: 启动 drift_trigger_worker ────────────────────────────────────────────
printf '\n'
log "=== [7/8] 启动 drift_trigger_worker ==="

# 等待 Java workers 初始化连接再 poll (避免 drift worker 抢到 drift_trigger 动作)
sleep 6

if [[ ! -f "${DRIFT_TRIGGER_WORKER}" ]]; then
  die "drift_trigger_worker 不存在: ${DRIFT_TRIGGER_WORKER}"
fi

nohup python3 "${DRIFT_TRIGGER_WORKER}" \
  >> "${LOG_DIR}/drift-trigger-worker.log" 2>&1 &
save_pid drift-trigger-worker $!
log "  drift-trigger-worker PID: $!"

# ── Step 8: 验证 Worker 注册 ─────────────────────────────────────────────────────
printf '\n'
log "=== [8/8] 验证 Worker 注册 ==="
sleep 3

wait_worker "repository-worker" "repository-worker-1" 60
wait_worker "gpt-worker"        "gpt-worker-1"        60
wait_worker "git-worker"        "git-worker-1"        60
wait_worker "drift-trigger-worker" "drift-trigger-worker-1" 60

# ── 完成 ─────────────────────────────────────────────────────────────────────────
printf '\n'
printf '=%.0s' {1..60}; printf '\n'
log "  AsyncAIFlow + Drift Demo 已就绪!"
printf '=%.0s' {1..60}; printf '\n'
log ""
log "  服务地址:"
log "    AsyncAIFlow API:  ${ASYNCAIFLOW_URL}"
log "    Drift API:        ${DRIFT_URL}"
log ""
log "  日志目录:  ${LOG_DIR}"
log "  PID 文件:  ${DEMO_PID_FILE}"
log ""
log "  停止所有服务:"
log "    bash '${SCRIPT_DIR}/demo-stop.sh'"
log ""
log "  运行 Demo (任选其一):"
log "    bash '${SCRIPT_DIR}/demo-planner.sh' --text 'Fix NPC behavior bug'"
log "    ./aiflow issue 'Fix NPC behavior bug'"
printf '=%.0s' {1..60}; printf '\n'
