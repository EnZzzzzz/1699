#!/usr/bin/env bash
# 采集平台一键启动：后端 uvicorn(8765) + 前端 vite dev(3000)
# 幂等：已在运行的服务会跳过。日志见 platform/logs/，pid 见 platform/run/。
# 进程脱离终端存活：stdin 接 /dev/null、nohup 挡 SIGHUP，并尽量 setsid 脱离进程组
#（交互式终端后台作业已是进程组组长、setsid 会失败，此时靠 nohup + /dev/null 兜底）。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$DIR/logs"
PID_DIR="$DIR/run"
mkdir -p "$LOG_DIR" "$PID_DIR"

BACKEND_PORT=8765
FRONTEND_PORT=3000

# 脱离终端的启动包装：先 setsid 另起会话（失败则忽略），再 exec 目标命令
DETACH_PY='import os,sys
try: os.setsid()
except OSError: pass
os.execvp(sys.argv[1], sys.argv[1:])'

is_running() { # pidfile
  [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null
}

start_backend() {
  local pidfile="$PID_DIR/server.pid"
  if is_running "$pidfile"; then
    echo "[跳过] 后端已在运行 (pid $(cat "$pidfile"), :$BACKEND_PORT)"
    return
  fi
  if [[ ! -x "$DIR/server/.venv/bin/uvicorn" ]]; then
    echo "[错误] 未找到 server/.venv/bin/uvicorn，请先建虚拟环境："
    echo "       cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
  fi
  echo "[启动] 后端 uvicorn :$BACKEND_PORT ..."
  (
    cd "$DIR/server"
    nohup .venv/bin/python -c "$DETACH_PY" \
      .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
      </dev/null >>"$LOG_DIR/server.log" 2>&1 &
    echo $! >"$pidfile"
  )
  echo "       pid=$(cat "$pidfile")  日志: $LOG_DIR/server.log"
}

start_frontend() {
  local pidfile="$PID_DIR/web.pid"
  if is_running "$pidfile"; then
    echo "[跳过] 前端已在运行 (pid $(cat "$pidfile"), :$FRONTEND_PORT)"
    return
  fi
  echo "[启动] 前端 vite dev :$FRONTEND_PORT ..."
  (
    cd "$DIR/web"
    nohup "$DIR/server/.venv/bin/python" -c "$DETACH_PY" \
      npm run dev -- --port "$FRONTEND_PORT" --host 127.0.0.1 \
      </dev/null >>"$LOG_DIR/web.log" 2>&1 &
    echo $! >"$pidfile"
  )
  echo "       pid=$(cat "$pidfile")  日志: $LOG_DIR/web.log"
}

start_backend
start_frontend

echo
echo "已就绪："
echo "  前端  http://127.0.0.1:$FRONTEND_PORT"
echo "  后端  http://127.0.0.1:$BACKEND_PORT  (docs: http://127.0.0.1:$BACKEND_PORT/docs)"
echo "停止：$DIR/stop.sh"
