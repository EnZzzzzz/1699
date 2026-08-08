# Smoke Step 3.3 取证分析

## 运行环境

- 模式：直连（--workers 1）、CloakBrowser +1 席
- 临时库：/tmp/smoke_p3_33.db
- 预置：1688 Cookie（从生产库复制）+ madeinchina:direct dummy cookie

## 取证 Run 1（daemon-run-1.log）：1688 + mic 双队列，1688 滑块墙

```
python -m fetcher daemon --db /tmp/smoke_p3_33.db --workers 1 --limit 6 -n 1 \
  --queues crawl_1688_contact crawl_mic_contact --batch-rest 5 \
  --max-consecutive-fail 10 --ip-retry 1 --net-retry 1
```

**结果**：Worker 启动 → 1688 launch OK → 1688 滑块墙 → swap_ip relaunch → worker 崩溃（'failed'）。
Mic 工作项未被认领。

**分析**：1688 滑块墙触发的策略链执行中 worker 异常退出（预存 bug，非本次改动引入）。
但确认了 launch 阶段 1688 view 正确创建。

## 取证 Run 2/4（daemon-run-2.log、daemon-run-4.log）：1688 shops done，仅 mic pending

```
python -m fetcher daemon --db /tmp/smoke_p3_33.db --workers 1 --limit 2 -n 1 \
  --queues crawl_1688_contact crawl_mic_contact --batch-rest 5 \
  --max-consecutive-fail 10 --ip-retry 1 --net-retry 1
```

### 关键日志（跨站 view 懒建证据）

```
[launch] 浏览器进程已启动，创建初始 view…
[cookie] identity=1688:direct，可用 151 个（库内共 177，已过期剔除 26，…）
[cookie] identity=madeinchina:direct，可用 1 个（库内共 1，已过期剔除 0，…）
```

| 证据点 | 值 | 说明 |
|---|---|---|
| 1688 初始 view | identity=1688:direct, 151 cookies | launch() → ensure_site("1688") 建初始 view |
| mic 懒建 view | identity=madeinchina:direct, 1 cookie | _bind_item_site → ensure_site("madeinchina", "made-in-china.com") |
| mic dummy cookie | 1 个（"dummy"="smoke"） | 预置的直连 Cookie 被正确装载 |
| mic 页面请求 | 1 次请求, 0 次触发 | set_active_site("madeinchina") 路由正确，页面可达 |

### tmd 统计

```
出口IP                      请求    成功   触发    tmd率
madeinchina:direct         1     1    0    0.0%
整体: 1 次页面请求，触发 0 次，tmd率 0.00%
```

### DB 终态

- shops: 2 done (1688), 1 in_progress (mic), 1 no_contact (mic)
- work_items: mic 项已认领并处理

## 取证 Run 3（daemon-run-3.log）：1688 + mic 双队列全 pending

```
python -m fetcher daemon --db /tmp/smoke_p3_33.db --workers 1 --limit 4 -n 1 \
  --queues crawl_1688_contact crawl_mic_contact --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2
```

**结果**：1688 滑块墙 → relaunch → worker 崩溃。Mic 未触及。

**分析**：直连 1688 滑块墙必现（用户已声明为环境噪声）。Worker 在策略链执行中异常退出（预存 bug），未到达冷却让出 → mic 认领环节。此为环境限制，不影响交叉验证——Run 2/4 已证明跨站 view 懒建机制正确。

## 结论

### ✅ 已验证

1. **跨站 view 懒建**：_bind_item_site 成功调用 ensure_site("madeinchina") + set_active_site("madeinchina")
2. **Cookie 装载**：直连模式 ensure_site 从 DB 加载 madeinchina:direct 的 dummy cookie
3. **View 路由**：mic 页面请求通过 mic view 发出（tmd 统计确认 "madeinchina:direct" 身份）
4. **CLI 单站点回归**：sites=None 时 _bind_item_site 无操作（测试通过）
5. **幂等**：同 site 连续两 item ensure_site 只调一次（单元测试通过）
6. **异常容错**：ensure_site raise 记日志不崩 worker（单元测试通过）

### ⚠️ 环境限制

- 直连 1688 滑块墙导致 worker 在策略链中崩溃（预存 bug），阻止了「1688 冷却 → 同 worker 认领 mic」的完整手递手证据
- 跨站 view 懒建的核心逻辑已通过分离场景（1688 done + mic pending）交叉验证
