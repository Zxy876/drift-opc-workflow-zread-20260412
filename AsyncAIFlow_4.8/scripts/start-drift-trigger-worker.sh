#!/bin/zsh
# 启动 drift_trigger_worker

LOGS="/Users/zxydediannao/ 4.8opcworkflow/ AsyncAIFlow_4.8/logs"
WORKER="/Users/zxydediannao/ 4.8opcworkflow/ AsyncAIFlow_4.8/python-workers/drift_trigger_worker/worker.py"

mkdir -p "$LOGS"

nohup python3 "$WORKER" > "$LOGS/drift-trigger-worker.log" 2>&1 &
echo "drift-trigger-worker PID: $!"
