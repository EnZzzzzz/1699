#!/usr/bin/env bash
# 1688 采集平台 - 一键启动后端三件套（redis + celery + uvicorn）
# 前端开发服务器由 Kimi Work 预览托管，或手动: cd web && npm run dev
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$ROOT/server"
VENV="$SERVER/.venv"
LOGS="$SERVER/logs"
PIDS="$SERVER/logs/pids"
mkdir -p "$LOGS" "$PIDS"

# --- 1. Redis ---
if redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "[start] redis 已在运行 (6379)"
else
  echo "[start] 启动 redis ..."
  redis-server --port 6379 --daemonize yes --logfile "$LOGS/redis.log"
  for i in $(seq 1 20); do
    redis-cli -p 6379 ping >/dev/null 2>&1 && break
    sleep 0.5
  done
  redis-cli -p 6379 ping >/dev/null 2>&1 || { echo "[start] redis 启动失败"; exit 1; }
  echo "[start] redis 就绪"
fi

# --- 2. FastAPI (uvicorn, 8765) ---
if lsof -iTCP:8765 -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  echo "[start] uvicorn 已在运行 (8765)"
else
  echo "[start] 启动 uvicorn (8765) ..."
  cd "$SERVER"
  nohup "$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8765 \
    >> "$LOGS/uvicorn.log" 2>&1 &
  echo $! > "$PIDS/uvicorn.pid"
  cd "$ROOT"
fi

# --- 3. Celery worker ---
if pgrep -f "celery -A app.workers.celery_app" >/dev/null 2>&1; then
  echo "[start] celery worker 已在运行"
else
  echo "[start] 启动 celery worker (threads x8) ..."
  cd "$SERVER"
  nohup "$VENV/bin/celery" -A app.workers.celery_app worker \
    --pool=threads --concurrency=8 --loglevel=info \
    >> "$LOGS/celery.log" 2>&1 &
  echo $! > "$PIDS/celery.pid"
  cd "$ROOT"
fi

sleep 2
echo
echo "[start] 完成。状态："
echo "  - API:      http://127.0.0.1:8765/api/stats/overview"
echo "  - 日志:     $LOGS/{uvicorn,celery,redis}.log"
echo "  - 停止:     ./stop.sh"
echo "  - 前端:     cd web && npm run dev （或用 Kimi Work 预览卡片）"
