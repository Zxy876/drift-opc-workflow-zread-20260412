#!/bin/bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
JAR=target/asyncaiflow-0.1.0-SNAPSHOT.jar
DRIFT="/Users/zxydediannao/ 4.8opcworkflow/drift-system-clean（very important）_4.8"

nohup java -cp "$JAR" \
  -Dloader.main=com.asyncaiflow.worker.repository.RepositoryWorkerApplication \
  "-Dasyncaiflow.repository-worker.repository.workspace-root=$DRIFT" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=repository-worker \
  > logs/repository-worker.log 2>&1 &
echo "repo-worker PID: $!"

nohup java -cp "$JAR" \
  -Dloader.main=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dasyncaiflow.gpt-worker.llm.mock-fallback-enabled=true \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=gpt-worker \
  > logs/gpt-worker.log 2>&1 &
echo "gpt-worker PID: $!"

nohup java -cp "$JAR" \
  -Dloader.main=com.asyncaiflow.worker.git.GitWorkerApplication \
  "-Dasyncaiflow.git-worker.repository.workspace-root=$DRIFT" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=git-worker \
  > logs/git-worker.log 2>&1 &
echo "git-worker PID: $!"

sleep 5

PY_WORKERS="/Users/zxydediannao/ 4.8opcworkflow/ AsyncAIFlow_4.8/python-workers"

nohup python3 "$PY_WORKERS/drift_trigger_worker/worker.py"  > logs/drift-trigger-worker.log  2>&1 & echo "drift-trigger-worker  PID: $!"
nohup python3 "$PY_WORKERS/drift_web_search_worker/worker.py" > logs/drift-web-search-worker.log 2>&1 & echo "drift-web-search-worker PID: $!"
nohup python3 "$PY_WORKERS/drift_plan_worker/worker.py"     > logs/drift-plan-worker.log     2>&1 & echo "drift-plan-worker     PID: $!"
nohup python3 "$PY_WORKERS/drift_code_worker/worker.py"     > logs/drift-code-worker.log     2>&1 & echo "drift-code-worker     PID: $!"
nohup python3 "$PY_WORKERS/drift_review_worker/worker.py"   > logs/drift-review-worker.log   2>&1 & echo "drift-review-worker   PID: $!"
nohup python3 "$PY_WORKERS/drift_test_worker/worker.py"     > logs/drift-test-worker.log     2>&1 & echo "drift-test-worker     PID: $!"
nohup python3 "$PY_WORKERS/drift_deploy_worker/worker.py"   > logs/drift-deploy-worker.log   2>&1 & echo "drift-deploy-worker   PID: $!"
nohup python3 "$PY_WORKERS/drift_git_push_worker/worker.py" > logs/drift-git-push-worker.log 2>&1 & echo "drift-git-push-worker PID: $!"
nohup python3 "$PY_WORKERS/drift_refresh_worker/worker.py"    > logs/drift-refresh-worker.log    2>&1 & echo "drift-refresh-worker    PID: $!"
nohup python3 "$PY_WORKERS/drift_experiment_worker/worker.py"  > logs/drift-experiment-worker.log  2>&1 & echo "drift-experiment-worker PID: $!"
nohup python3 "$PY_WORKERS/drift_arc_worker/worker.py"         > logs/drift-arc-worker.log         2>&1 & echo "drift-arc-worker        PID: $!"
nohup python3 "$PY_WORKERS/drift_experience_worker/worker.py"  > logs/drift-experience-worker.log  2>&1 & echo "drift-experience-worker PID: $!"

echo "All workers started!"
