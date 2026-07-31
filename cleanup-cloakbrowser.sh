#!/bin/bash
# cleanup-cloakbrowser.sh
# 清理 CloakBrowser 卡住的云端会话租约（free license 只能同时跑 1 个实例，
# 进程被强杀后租约不会自动注销，导致下次启动报 "session limit reached"）。
#
# 原理：调用 cloakbrowser.dev 的 session/end 接口释放该 install_id 下的租约，
# 然后轮询 session/count 确认服务端计数归零（计数接口有延迟，需等 1~2 分钟）。
#
# 用法:  bash cleanup-cloakbrowser.sh

set -u

CB_DIR="$HOME/.cloakbrowser"
KEY_FILE="$CB_DIR/license.key"
IID_FILE="$CB_DIR/install_id"
API="https://cloakbrowser.dev/api/license"

if [ ! -f "$KEY_FILE" ]; then
  echo "❌ 未找到 $KEY_FILE —— 请先运行 'cloakbrowser login' 激活 free license"
  exit 1
fi

KEY=$(cat "$KEY_FILE")
IID=$([ -f "$IID_FILE" ] && cat "$IID_FILE" || echo "")

echo "==> 1/3 检查本地是否有残留 cloakbrowser 进程"
PIDS=$(ps -A -o pid,command | grep -i "\.cloakbrowser" | grep -v grep | awk '{print $1}')
if [ -n "$PIDS" ]; then
  echo "    发现残留进程: $PIDS"
  echo "    正在终止（先 TERM 后 KILL）..."
  echo "$PIDS" | xargs kill 2>/dev/null
  sleep 2
  echo "$PIDS" | xargs kill -9 2>/dev/null
  echo "    已终止。"
else
  echo "    无本地残留进程（问题在服务端租约）。"
fi

echo "==> 2/3 调用 session/end 释放云端租约"
RESP=$(curl -s -m 15 -X POST "$API/session/end" \
  -H 'Content-Type: application/json' \
  -d "{\"license_key\": \"$KEY\", \"install_id\": \"$IID\", \"lease_id\": \"x\", \"instance_id\": \"x\"}")
echo "    服务端响应: $RESP"

echo "==> 3/3 轮询 session/count，等待计数归零（最多等 3 分钟）"
for i in $(seq 1 18); do
  COUNT=$(curl -s -m 10 -X POST "$API/session/count" \
    -H 'Content-Type: application/json' \
    -d "{\"license_key\": \"$KEY\"}")
  ACTIVE=$(echo "$COUNT" | sed -n 's/.*"active":[ ]*\([0-9]*\).*/\1/p')
  TS=$(date "+%H:%M:%S")
  if [ "$ACTIVE" = "0" ]; then
    echo "    [$TS] ✅ active = 0，租约已释放，可以正常启动了。"
    exit 0
  fi
  echo "    [$TS] active = ${ACTIVE:-未知}（计数接口有延迟，继续等待...）"
  sleep 10
done

echo ""
echo "⚠️  等了 3 分钟计数仍不为 0。注意 count 接口有明显缓存延迟——"
echo "    可以直接试着启动一次浏览器，能启动就说明实际已经放行；"
echo "    若仍报 session limit（exit code 76），过几分钟再运行一次本脚本，"
echo "    或联系 support@cloakbrowser.dev。"
exit 2
