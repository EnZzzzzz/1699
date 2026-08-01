#!/usr/bin/env bash
# 1688 采集平台 - 停止前后端服务
# 策略：优先用 pid 文件精准停止；pid 文件缺失或失效时，按进程特征查找并 kill
# （先 TERM 优雅退出，超时后 KILL）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS="$ROOT/server/logs/pids"

wait_gone() { # $1=pid  等待进程退出，返回 0=已退出
  local pid="$1"
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  return 1
}

stop_one() { # $1=名字  $2=进程特征 pattern
  local name="$1" pattern="$2"
  local f="$PIDS/$name.pid"

  # 1) pid 文件存在且进程还活着：按 pid 停
  if [ -f "$f" ]; then
    local pid
    pid="$(cat "$f" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "[stop] 用 pid 文件停止 $name (pid $pid) ..."
      kill "$pid" 2>/dev/null || true
      if ! wait_gone "$pid"; then
        echo "[stop] $name 未退出，强制 kill -9"
        kill -9 "$pid" 2>/dev/null || true
      fi
    else
      echo "[stop] $name 的 pid 文件已失效，改用进程查找"
    fi
    rm -f "$f"
  fi

  # 2) 进程特征兜底清扫（无 pid 文件、pid 文件失效、或 pid 杀漏时都靠它兜住）
  local pids
  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    echo "[stop] $name 已停止"
    return 0
  fi
  echo "[stop] 按进程查找停止 $name (pid: $(echo $pids | tr '\n' ' ')) ..."
  echo "$pids" | xargs kill 2>/dev/null || true
  for _ in $(seq 1 20); do
    pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
    [ -z "$pids" ] && break
    sleep 0.5
  done
  if [ -n "$pids" ]; then
    echo "[stop] $name 未退出，强制 kill -9"
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
  echo "[stop] $name 已停止"
}

stop_one "vite"    "node_modules/.bin/vite"
stop_one "celery"  "celery -A app.workers.celery_app"
stop_one "uvicorn" "uvicorn app.main:app"

echo "[stop] 完成（redis 保持运行；如需停止: redis-cli shutdown）"
