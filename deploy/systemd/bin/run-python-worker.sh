#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:?worker instance is required}"

: "${ASYNC_ROOT:?ASYNC_ROOT is required}"
: "${DRIFT_ROOT:?DRIFT_ROOT is required}"

PYTHON_BIN="${PYTHON_WORKER_PYTHON:-python3}"
PYTHON_ROOT="${ASYNC_ROOT}/python-workers"

export AIFLOW_URL="${AIFLOW_URL:-${ASYNCAIFLOW_URL:-http://127.0.0.1:8080}}"
export ASYNCAIFLOW_URL="${ASYNCAIFLOW_URL:-${AIFLOW_URL}}"
export ASYNCAIFLOW_SERVER_BASE_URL="${ASYNCAIFLOW_SERVER_BASE_URL:-${AIFLOW_URL}}"
export DRIFT_URL="${DRIFT_URL:-http://127.0.0.1:${DRIFT_BACKEND_PORT:-8000}}"
export DRIFT_BACKEND_URL="${DRIFT_BACKEND_URL:-${DRIFT_URL}}"
export DRIFT_REPO_PATH="${DRIFT_REPO_PATH:-${DRIFT_ROOT}}"
export DRIFT_PATCH_DIR="${DRIFT_PATCH_DIR:-${ASYNC_ROOT}/tmp/drift_patches}"
export POLL_INTERVAL_S="${POLL_INTERVAL_S:-2}"
export HEARTBEAT_INTERVAL_S="${HEARTBEAT_INTERVAL_S:-10}"
export ASYNCAIFLOW_POLL_INTERVAL_SECONDS="${ASYNCAIFLOW_POLL_INTERVAL_SECONDS:-2}"

case "${INSTANCE}" in
  drift_trigger)
    WORKER_FILE="${PYTHON_ROOT}/drift_trigger_worker/worker.py"
    export DRIFT_TRIGGER_WORKER_ID="${DRIFT_TRIGGER_WORKER_ID:-drift-trigger-worker-1}"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-${DRIFT_TRIGGER_WORKER_ID}}"
    export ASYNCAIFLOW_CAPABILITIES="drift_trigger"
    ;;
  drift_web_search)
    WORKER_FILE="${PYTHON_ROOT}/drift_web_search_worker/worker.py"
    export DRIFT_WEB_SEARCH_WORKER_ID="${DRIFT_WEB_SEARCH_WORKER_ID:-drift-web-search-worker-1}"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-${DRIFT_WEB_SEARCH_WORKER_ID}}"
    export ASYNCAIFLOW_CAPABILITIES="drift_web_search"
    ;;
  drift_plan)
    WORKER_FILE="${PYTHON_ROOT}/drift_plan_worker/worker.py"
    export DRIFT_PLAN_WORKER_ID="${DRIFT_PLAN_WORKER_ID:-drift-plan-worker-1}"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-${DRIFT_PLAN_WORKER_ID}}"
    export ASYNCAIFLOW_CAPABILITIES="drift_plan"
    ;;
  drift_code)
    WORKER_FILE="${PYTHON_ROOT}/drift_code_worker/worker.py"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-drift-code-worker-py}"
    export ASYNCAIFLOW_CAPABILITIES="drift_code"
    export GLM_BASE_URL="${GLM_BASE_URL:-${GLM_BASE_URL_CODING:-https://open.bigmodel.cn/api/coding/paas/v4}}"
    export GLM_MODEL="${GLM_MODEL:-${GLM_MODEL_CODING:-codegeex-4}}"
    ;;
  drift_review)
    WORKER_FILE="${PYTHON_ROOT}/drift_review_worker/worker.py"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-drift-review-worker-py}"
    export ASYNCAIFLOW_CAPABILITIES="drift_review"
    ;;
  drift_test)
    WORKER_FILE="${PYTHON_ROOT}/drift_test_worker/worker.py"
    export DRIFT_TEST_WORKER_ID="${DRIFT_TEST_WORKER_ID:-drift-test-worker-1}"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-${DRIFT_TEST_WORKER_ID}}"
    export ASYNCAIFLOW_CAPABILITIES="drift_test"
    ;;
  drift_deploy)
    WORKER_FILE="${PYTHON_ROOT}/drift_deploy_worker/worker.py"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-drift-deploy-worker-py}"
    export ASYNCAIFLOW_CAPABILITIES="drift_deploy"
    ;;
  drift_git_push)
    WORKER_FILE="${PYTHON_ROOT}/drift_git_push_worker/worker.py"
    export DRIFT_GIT_PUSH_WORKER_ID="${DRIFT_GIT_PUSH_WORKER_ID:-drift-git-push-worker-1}"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-${DRIFT_GIT_PUSH_WORKER_ID}}"
    export ASYNCAIFLOW_CAPABILITIES="drift_git_push"
    ;;
  drift_refresh)
    WORKER_FILE="${PYTHON_ROOT}/drift_refresh_worker/worker.py"
    export ASYNCAIFLOW_WORKER_ID="${ASYNCAIFLOW_WORKER_ID:-drift-refresh-worker-py}"
    export ASYNCAIFLOW_CAPABILITIES="drift_refresh"
    ;;
  *)
    echo "Unsupported Python worker instance: ${INSTANCE}" >&2
    exit 1
    ;;
esac

if [[ ! -f "${WORKER_FILE}" ]]; then
  echo "Worker file not found: ${WORKER_FILE}" >&2
  exit 1
fi

mkdir -p "${DRIFT_PATCH_DIR}"
cd "$(dirname "${WORKER_FILE}")"
exec "${PYTHON_BIN}" "${WORKER_FILE}"