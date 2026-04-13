#!/usr/bin/env bash
set -euo pipefail

: "${DRIFT_ROOT:?DRIFT_ROOT is required}"

BACKEND_DIR="${DRIFT_ROOT}/backend"
VENV_DIR="${DRIFT_BACKEND_VENV:-${BACKEND_DIR}/venv}"
HOST="${DRIFT_BACKEND_HOST:-0.0.0.0}"
PORT="${DRIFT_BACKEND_PORT:-8000}"

if [[ ! -x "${VENV_DIR}/bin/uvicorn" ]]; then
  echo "uvicorn not found in ${VENV_DIR}. Create the venv and install backend requirements first." >&2
  exit 1
fi

cd "${BACKEND_DIR}"
exec "${VENV_DIR}/bin/uvicorn" app.main:app --host "${HOST}" --port "${PORT}"