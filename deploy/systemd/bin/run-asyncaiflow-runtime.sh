#!/usr/bin/env bash
set -euo pipefail

: "${ASYNC_ROOT:?ASYNC_ROOT is required}"
: "${AIFLOW_JAR:?AIFLOW_JAR is required}"

cd "${ASYNC_ROOT}"
exec java -jar "${AIFLOW_JAR}"