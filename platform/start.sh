#!/usr/bin/env bash
# 采集平台一键启动：后端 uvicorn(8765) + 前端 vite dev(3000) + 调度器 daemon
# 幂等：已在运行的服务会跳过。日志见 platform/logs/，pid 见 platform/run/。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$DIR/logs"
PID_DIR="$DIR/run"
mkdir -p "$LOG_DIR" "$PID_DIR"

BACKEND_PORT=8765
FRONTEND_PORT=3000

# daemon 可选参数（如 --queues 子集 / --workers 调整），默认全量 5+1 队列
# 注意：daemon 1 进程多 context 只占 1 席 CloakBrowser，默认直连 1 worker；
# 生产多 worker 由运维在此显式加 --workers N
# daemon 全局有头运行：桌面会弹出浏览器窗口，属预期行为，勿当异常关闭
DAEMON_ARGS=${DAEMON_ARGS:---workers 1}
# 有头为全局硬性要求：即使外部覆盖了 DAEMON_ARGS，也强制保留 --headed
[[ " $DAEMON_ARGS " == *" --headed "* ]] || DAEMON_ARGS="$DAEMON_ARGS --headed"

# wa_check 查号账号池（逗号分隔，对应 vendor/wa-check/auth_info-<name>/）；
# 缺省 default 无登录态，wa_check 批次会全部「未登录」空跑放弃
export WA_CHECK_ACCOUNTS=${WA_CHECK_ACCOUNTS:-xiaohao-4,xiaohao-5}

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
    echo "       cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt --no-deps -e ../../fetcher"
    exit 1
  fi
  echo "[启动] 后端 uvicorn :$BACKEND_PORT ..."
  ( cd "$DIR/server" && nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >>"$LOG_DIR/server.log" 2>&1 & echo $! >"$pidfile" )
  echo "       pid=$(cat "$pidfile")  日志: $LOG_DIR/server.log"
}

start_frontend() {
  local pidfile="$PID_DIR/web.pid"
  if is_running "$pidfile"; then
    echo "[跳过] 前端已在运行 (pid $(cat "$pidfile"), :$FRONTEND_PORT)"
    return
  fi
  echo "[启动] 前端 vite dev :$FRONTEND_PORT ..."
  ( cd "$DIR/web" && nohup npm run dev -- --port "$FRONTEND_PORT" --host 127.0.0.1 >>"$LOG_DIR/web.log" 2>&1 & echo $! >"$pidfile" )
  echo "       pid=$(cat "$pidfile")  日志: $LOG_DIR/web.log"
}

start_daemon() {
  local pidfile="$PID_DIR/daemon.pid"
  if is_running "$pidfile"; then
    echo "[跳过] 调度器 daemon 已在运行 (pid $(cat "$pidfile"))"
    return
  fi
  if [[ ! -x "$DIR/server/.venv/bin/python" ]]; then
    echo "[错误] 未找到 server/.venv/bin/python，请先建虚拟环境"
    exit 1
  fi
  echo "[启动] 调度器 daemon（fetcher daemon ${DAEMON_ARGS}）..."
  ( cd "$DIR/.." && nohup "$DIR/server/.venv/bin/python" -m fetcher daemon $DAEMON_ARGS >>"$LOG_DIR/daemon.log" 2>&1 & echo $! >"$pidfile" )
  echo "       pid=$(cat "$pidfile")  日志: $LOG_DIR/daemon.log"
  echo "       注意：平台已纳管 daemon，不要再手动启动（防双 daemon）"
}

start_backend
start_frontend
start_daemon

echo
echo "已就绪："
echo "  前端  http://127.0.0.1:$FRONTEND_PORT"
echo "  后端  http://127.0.0.1:$BACKEND_PORT  (docs: http://127.0.0.1:$BACKEND_PORT/docs)"
echo "停止：$DIR/stop.sh"
