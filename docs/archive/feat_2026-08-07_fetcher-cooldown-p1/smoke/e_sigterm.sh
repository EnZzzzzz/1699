#!/bin/bash
# Step 3.1 E 段：daemon 批休窗口内 SIGTERM 秒级中断取证
# 用法：e_sigterm.sh <python_pid> <db> —— 轮询 work_items 终态数≥3 后等 8s（落进批休窗口）发 SIGTERM
set -u
PYPID="$1"; DB="$2"
echo "[e] $(date +%H:%M:%S) 开始轮询 ${DB} 终态数（目标 pid=${PYPID}）"
while true; do
  n=$(sqlite3 -readonly "$DB" "SELECT COUNT(*) FROM work_items WHERE status IN ('done','failed')")
  if [ "$n" -ge 3 ]; then break; fi
  kill -0 "$PYPID" 2>/dev/null || { echo "[e] 进程已死，终态数=$n"; exit 1; }
  sleep 2
done
third=$(sqlite3 -readonly "$DB" "SELECT MAX(finished_at) FROM work_items WHERE status IN ('done','failed')")
echo "[e] $(date +%H:%M:%S) 第 3 个 item 已落终态（finished_at=${third}），等 8s 落进批休窗口…"
sleep 8
t0=$(python3 -c 'import time;print(time.time())')
echo "[e] $(date +%H:%M:%S).$(python3 -c 'import time;print(int(time.time()%1*1000))') 发送 SIGTERM → pid $PYPID"
kill -TERM "$PYPID"
while kill -0 "$PYPID" 2>/dev/null; do sleep 0.2; done
t1=$(python3 -c 'import time;print(time.time())')
echo "[e] $(date +%H:%M:%S) 进程已退出，kill→退出耗时 $(python3 -c "print(f'{$t1-$t0:.1f}')")s"
echo "[e] 杀后 shops 状态（item 4 应仍 pending=未被认领，证明 SIGTERM 落在批间）："
sqlite3 -readonly "$DB" "SELECT id,status FROM shops ORDER BY id"
