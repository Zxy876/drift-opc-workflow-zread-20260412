#!/usr/bin/env bash
# sync-backend-to-cloud.sh
# ─────────────────────────────────────────────────────────────────────────────
# 用法:  bash sync-backend-to-cloud.sh  <user@host>  [ssh_port]
#
# 示例:  bash sync-backend-to-cloud.sh  ubuntu@1.2.3.4
#        bash sync-backend-to-cloud.sh  root@1.2.3.4  2222
#
# 做什么:
#   1. SSH 进服务器
#   2. 进入 DRIFT_ROOT（从 /etc/drift-stack.env 读取）
#   3. git pull origin main
#   4. 重启 drift-backend.service
#   5. 验证后端 /levels 是否响应
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

TARGET="${1:-}"
PORT="${2:-22}"

if [[ -z "$TARGET" ]]; then
  echo "Usage: bash sync-backend-to-cloud.sh <user@host> [ssh_port]"
  echo "Example: bash sync-backend-to-cloud.sh ubuntu@1.2.3.4"
  exit 1
fi

echo "⟶  Connecting to $TARGET:$PORT ..."

ssh -p "$PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$TARGET" bash <<'REMOTE'
set -euo pipefail

# ── Read DRIFT_ROOT from /etc/drift-stack.env ──────────────────────────────
if [[ -f /etc/drift-stack.env ]]; then
  source /etc/drift-stack.env
else
  # fallback to typical default
  DRIFT_ROOT="/opt/drift-demo/drift-system-clean"
fi

echo "[1/4] DRIFT_ROOT = $DRIFT_ROOT"
cd "$DRIFT_ROOT"

# ── git pull ───────────────────────────────────────────────────────────────
echo "[2/4] git pull origin main ..."
git pull origin main

# ── restart drift-backend.service ─────────────────────────────────────────
echo "[3/4] Restarting drift-backend.service ..."
sudo systemctl restart drift-backend.service
sleep 3

# ── health check ──────────────────────────────────────────────────────────
echo "[4/4] Health check ..."
for i in 1 2 3 4 5; do
  if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('http://127.0.0.1:8000/levels', timeout=5)
    print('  OK — backend responding')
    sys.exit(0)
except Exception as e:
    print(f'  Waiting... ({e})')
    sys.exit(1)
" 2>&1; then
    break
  fi
  sleep 3
done

echo ""
echo "✅  Sync complete."
echo "    drift-backend status:"
sudo systemctl status drift-backend.service --no-pager --lines=5
REMOTE
