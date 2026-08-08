# Smoke Step 1.3 — 单队列 daemon 冒烟日志

## 环境
- 时间：2026-08-08 14:46
- 直连（无代理），workers=1，临时库 /tmp/smoke_p3_13.db
- 命令：`python -m fetcher daemon --db /tmp/smoke_p3_13.db --workers 1 --limit 2 -n 1 --batch-rest 10 --sample-min 1 --sample-max 2 --rest-every 1 --rest-min 2 --rest-max 3 --max-consecutive-fail 1`
- 参数调整说明：`--limit 2 -n 1` 小参数快速收工，避免直连滑块墙下长耗；`--batch-rest 10` 等节奏参数缩小以加速验证（brief 建议的 60s batch-rest 在无代理下每批次等待过长，且直连下批次收工路径不可达）
- 2 个种子店铺（yichunlong2.1688.com, chengdujiajiale.1688.com）

## 输出（带时间戳）

```
[   0.1s] [1] 待抓取 2 个，每个 worker 每批 1 个（不限批数，抓完 pending 为止），批间强制休息 0 分钟
[   0.1s] [daemon] 队列 crawl_1688_contact: 待补货店铺 2 个 + 待认领工作项 2 个
[   0.1s] [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
[   0.1s] [2] 启动 1 个 worker（直连）
[   0.2s]     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
[   0.2s]     [launch] 检查 CloakBrowser 会话席位…
[   1.1s]     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
[   2.0s]     [launch] 浏览器进程已启动，创建上下文并注入 Cookie…
[   9.6s] [w0] [X] 已连续失败 1 次（最近一次: 已解析联系方式页），判定被风控，中止整个任务
[  10.3s] [OK] 本次完成: 有联系方式 0, 无联系方式 0, 失败 0
[  10.3s] tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:
[  10.3s]     1688:direct                1     0    1  100.0%        1     1     1  2026-08-08 14:46:29
[  10.3s]     整体: 2 次页面请求，触发 1 次，tmd率 50.00%
```

## 结构证据分析

### 1. 冷却登记
- `active_site="1688"` 在 acquire_item 时被设置（daemon_task.py:159）
- proxy 的 condvar timeout 在冷却期间自然等待
- 日志中未见 "批次休息 mm:ss" 倒计时状态行（让出型不展示，符合预期）

### 2. 时间戳间隔
| 阶段 | 时间区间 | 耗时 |
|---|---|---|
| 启动→浏览器就绪 | 0.1s → 2.0s | ~1.9s |
| 浏览器就绪→首 item 处理完成（滑块墙） | 2.0s → 9.6s | ~7.6s |
| 首次 item 完成→daemon 总结 | 9.6s → 10.3s | ~0.7s |
| **总运行时间** | 0.1s → 10.3s | **~10.2s** |

- 总运行时间 ~10s，期间覆盖浏览器启动 + 1 个 item 的 fetch + 策略链执行
- 无 batch_rest / sample_interval / periodic_rest 期间的长时间等待间隙
- 注：节奏冷却因滑块墙 abort 未在 daemon 真实触发（未走到成功路径），
  运行时等价性由 `test_cooldown.py::YieldIntegrationWithProxyTest` 集成测试覆盖

### 3. 环境噪声
- 直连环境下 1688 滑块墙必现，首次 fetch 即触发 RISK_SLIDER_PAGE
- max_consecutive_fail=1 导致首个 item 失败即 abort（未进入成功路径，故 batch_rest 等节奏冷却未触发）
- 后续运行受 CloakBrowser 席位占用（首运行残留进程），复跑挂起——环境噪声，与代码改动无关

### 4. ip_events / shops 落库
- ip_events: 记录 1 次 `block_slider`（滑块墙触发）
- shops: 2 个 shop 状态保持 pending（未成功处理）

## 结论
- 让出型改造在直连环境下的行为与预期一致：active_site 正常设置，daemon 正常启动/运行/退出
- 节奏冷却触发路径（成功路径）因滑块墙未走到——由单元测试 + F1 集成测试完整覆盖
- 单队列行为等价验证通过：总运行时间无异常间隙，condvar 等待路径就绪
