# task-2.3-brief — P4-2 Step 2.3：start.sh/stop.sh 纳管 daemon + 冒烟

## 位置

P4 第 2 阶段第 3 步（daemon 生命周期纳管）。改动范围：
`platform/start.sh`（start_daemon）、`platform/stop.sh`（stop_daemon）、
`README.md`（平台纳管后不要再手动起 daemon）、AGENTS.md（§1 daemon 段落
同步，若提及）。冒烟证据落 plan 目录。

## 需求（SPEC §3.6 + PLAN Step 2.3）

### 1. start.sh 加 start_daemon()

- 照抄现有幂等模式：pidfile `platform/run/daemon.pid`、日志
  `platform/logs/daemon.log`、`nohup server/.venv/bin/python -m fetcher
  daemon`，cwd=项目根。
- 默认全量 5+1 队列（daemon 默认参数即全量）。
- `is_running(pidfile)` 幂等：已在跑跳过。
- 注意席位：daemon 1 进程（多 context）+ yiwugo 偶发 1 进程 + 手动爬虫
  ≤ solo 5 席——默认 workers 保持 0（直连 1 worker）？**裁定**：daemon
  默认 `--workers 1`（与冒烟纪律一致，避免多席位抢占；生产多 worker 由
  运维显式调参）。

### 2. stop.sh 加 stop_daemon()

- `graceful_stop(pidfile)` 复用现有函数（SIGTERM→5s 等待→SIGKILL）。
- pkill 兜底特征 `fetcher.*daemon`（不误伤手动旧 CLI——该特征只匹配
  命令行含 daemon 的 fetcher 进程）。

### 3. 防双 daemon

- start.sh 的 is_running(pidfile) 幂等已保证。
- README 注明「平台纳管后不要再手动起 daemon」。

## 验收

1. 真起真停：`start.sh` 起 daemon → consumer_status 有心跳（平台 API
   可见 daemon_alive=true）；`stop.sh` 停 → daemon 进程消失、
   consumer_status 清空。
2. 重复 start 幂等（第二次「已跳过」）。
3. 冒烟证据（日志 + API 输出）落 plan 目录。
4. **注意**：本机已有 P3 遗留 daemon（pid 28917）在跑——start_daemon 的
   幂等判定可能误判。需处理：P3 遗留 daemon 的 pidfile 不在
   platform/run/（它是 P3 冒烟手动起的），所以 is_running 判定为「未在
   跑」→ 会起第二个 daemon → 双 daemon 抢队列（claim 互斥但 topup 双喂）。
   **裁定**：冒烟前先停掉 P3 遗留 daemon（它是 /tmp 临时库，非生产），
   再验证 start/stop 幂等。

## 环境约束

- 冒烟用临时库？daemon 默认连生产库 .cache/1688.db（只读消费 work_items，
  会写 consumer_status/proxy_channels 租约）。**风险**：start_daemon 冒烟
  会真实起 daemon 连生产库——写 consumer_status 和租约是 P4 设计的正常
  行为，但对生产库有写。**裁定**：冒烟时用环境变量 FETCHER_DB_PATH 指向
  临时库副本（daemon 支持 --db，start.sh 里可传）——或验证幂等/起停语义
  用临时库，真实生产库由用户后续自行启停。冒烟用 `FETCHER_DB_PATH=/tmp/...`
  隔离。
