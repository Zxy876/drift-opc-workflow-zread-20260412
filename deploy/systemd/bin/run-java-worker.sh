#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:?worker instance is required}"

: "${ASYNC_ROOT:?ASYNC_ROOT is required}"
: "${DRIFT_ROOT:?DRIFT_ROOT is required}"
: "${AIFLOW_JAR:?AIFLOW_JAR is required}"

cd "${ASYNC_ROOT}"

case "${INSTANCE}" in
  repository)
    exec java -cp "${AIFLOW_JAR}" \
      -Dloader.main=com.asyncaiflow.worker.repository.RepositoryWorkerApplication \
      "-Dasyncaiflow.repository-worker.repository.workspace-root=${DRIFT_ROOT}" \
      org.springframework.boot.loader.launch.PropertiesLauncher \
      --spring.profiles.active=repository-worker
    ;;
  gpt)
    exec java -cp "${AIFLOW_JAR}" \
      -Dloader.main=com.asyncaiflow.worker.gpt.GptWorkerApplication \
      "-Dasyncaiflow.gpt-worker.llm.mock-fallback-enabled=${GPT_MOCK_FALLBACK_ENABLED:-false}" \
      org.springframework.boot.loader.launch.PropertiesLauncher \
      --spring.profiles.active=gpt-worker
    ;;
  git)
    exec java -cp "${AIFLOW_JAR}" \
      -Dloader.main=com.asyncaiflow.worker.git.GitWorkerApplication \
      "-Dasyncaiflow.git-worker.repository.workspace-root=${DRIFT_ROOT}" \
      org.springframework.boot.loader.launch.PropertiesLauncher \
      --spring.profiles.active=git-worker
    ;;
  *)
    echo "Unsupported Java worker instance: ${INSTANCE}" >&2
    exit 1
    ;;
esac