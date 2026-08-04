#!/usr/bin/env bash
# 采集平台一键停止：先按 platform/run/*.pid 优雅停止，再按进程特征兜底 pkill。
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$DIR/run"

graceful_stop() { # pidfile name
  local pidfile="$1" name="$2"
  if [[ ! -f "$pidfile" ]]; then
    return
  fi
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "[停止] $name (pid $pid) SIGTERM ..."
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "[强制] $name (pid $pid) SIGKILL"
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$pidfile"
}

graceful_stop "$PID_DIR/server.pid" "后端 uvicorn"
graceful_stop "$PID_DIR/web.pid" "前端 vite"

# 兜底：pid 文件丢失或子进程（npm 派生的 vite）残留时按特征清理
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8765" 2>/dev/null && echo "[兜底] 清理残留 uvicorn 进程" || true
pkill -f "vite.*--port 3000" 2>/dev/null && echo "[兜底] 清理残留 vite 进程" || true

echo "已全部停止。"
