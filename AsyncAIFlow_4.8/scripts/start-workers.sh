#!/bin/zsh
# 启动所有 Worker 进程（使用 PropertiesLauncher 指定各自 main class）

JAR="/Users/zxydediannao/ 4.8opcworkflow/ AsyncAIFlow_4.8/target/asyncaiflow-0.1.0-SNAPSHOT.jar"
DRIFT_WORKSPACE="/Users/zxydediannao/ 4.8opcworkflow/drift-system-clean（very important）_4.8"
LOGS="/Users/zxydediannao/ 4.8opcworkflow/ AsyncAIFlow_4.8/logs"

mkdir -p "$LOGS"

# Kill any existing workers (by profile identifier in command line)
pkill -f "repository-worker" 2>/dev/null || true
pkill -f "gpt-worker" 2>/dev/null || true
pkill -f "git-worker" 2>/dev/null || true
sleep 2

echo "Starting repository-worker..."
nohup java \
  -cp "$JAR" \
  -Dloader.main=com.asyncaiflow.worker.repository.RepositoryWorkerApplication \
  "-Dasyncaiflow.repository-worker.repository.workspace-root=$DRIFT_WORKSPACE" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=repository-worker \
  > "$LOGS/repository-worker.log" 2>&1 &
REPO_PID=$!
echo "repository-worker PID: $REPO_PID"

echo "Starting gpt-worker..."
nohup java \
  -cp "$JAR" \
  -Dloader.main=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dasyncaiflow.gpt-worker.llm.mock-fallback-enabled=true \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=gpt-worker \
  > "$LOGS/gpt-worker.log" 2>&1 &
GPT_PID=$!
echo "gpt-worker PID: $GPT_PID"

echo "Starting git-worker..."
nohup java \
  -cp "$JAR" \
  -Dloader.main=com.asyncaiflow.worker.git.GitWorkerApplication \
  "-Dasyncaiflow.git-worker.repository.workspace-root=$DRIFT_WORKSPACE" \
  org.springframework.boot.loader.launch.PropertiesLauncher \
  --spring.profiles.active=git-worker \
  > "$LOGS/git-worker.log" 2>&1 &
GIT_PID=$!
echo "git-worker PID: $GIT_PID"

echo ""
echo "=== Workers started ==="
echo "repository-worker: $REPO_PID"
echo "gpt-worker:        $GPT_PID"
echo "git-worker:        $GIT_PID"
echo ""
echo "Logs at: $LOGS/"
echo "Waiting 12s for workers to register..."
sleep 12

echo ""
echo "=== repository-worker log (last 8 lines) ==="
tail -8 "$LOGS/repository-worker.log"
echo ""
echo "=== gpt-worker log (last 8 lines) ==="
tail -8 "$LOGS/gpt-worker.log"
echo ""
echo "=== git-worker log (last 8 lines) ==="
tail -8 "$LOGS/git-worker.log"
