# wa-check 重试与风控冷却 — 设计规格

日期：2026-08-05

## 背景与目标

### 背景

- 任务 68（`wa_check`，账号 xiaohao-1）在 2026-08-05 运行期间，批次 11（05:09–05:24）爆发 **40 次「查询失败: Connection Closed」**：前 14 个号码正常返回「未注册」，随后 socket 被杀、剩余 36 个号码连错；批次 12 部分号码继续出错，之后约 30 分钟自动恢复。
- 用户最初怀疑是虚拟网卡网络波动，但错误**高度聚集在单一 11 分钟窗口**（非随机散布），且发生在休息 14 分钟后刚恢复的批次，符合 WhatsApp 对单设备批量 `us` 查询的**临时限流（throttle）**特征。
- 出错号码当前被正确保持 `wa_registered=NULL`（未查，`_apply_results` 跳过 `registered: null`），下次任务自动补查，**数据无丢失**。

### 目标

1. **单号瞬断能廉价自愈**：协议层重连 socket 后重试该号码（覆盖网络抖动/临时掉线）。
2. **风控不硬顶**：连续失败达到阈值立即中止本批，避免对受限账号火上浇油。
3. **风控后长冷却**：高错误率批次后进入额外冷却再进下一批，补上「本批出错、下批 30 秒就硬刚」的缺口。
4. **不改变数据语义**：重试后仍失败的号码保持 `NULL`（未查），下轮自动补查。
5. **尊重架构铁律**：「原子只报告、不决策」——重试/冷却决策落在协议层（check.js 稳健性）与策略层（wa_tasks.py）。

## 范围

- **改动文件**
  - `fetcher/vendor/wa-check/check.js`（协议层）：单号重连重试 + 连续失败中止本批
  - `platform/server/app/wa_tasks.py`（策略层）：批级错误率冷却
  - `fetcher/fetcher/atoms/wa_check.py`：仅超时公式微调（+360s 重试预算，算术性质）
- **刻意不动**：前端、API `TaskParams`、原子决策逻辑、数据语义、任务参数面。

## 方案对比

| 方案 | 思路 | 缺点 | 结论 |
|---|---|---|---|
| A 全在 check.js | 单号重连重试 + 连续失败中止 | 缺批级冷却——风控后下批仍会立即硬刚（本次 batch 12 正是如此） | 否决 |
| B 全在 wa_tasks.py | 批内失败号码收集成重试批 | 单号瞬断也要重建子进程+新连接（~10s 开销），浪费；mid-batch socket 死亡仍让剩余号码全挂 | 否决 |
| **C 分层** | check.js 做单号快速重连（协议稳健性）；wa_tasks.py 做批级错误率冷却（策略决策） | 改两个文件 | **采用** |

**推荐理由**：各层做自己擅长的事——瞬断在协议层重连最廉价（复用现有 `connectWithRetry`），风控冷却在策略层降速才保号；完全尊重「原子只报告、不决策」约束；`wa_tasks.py` 从 `results` 已有 `registered: null` 条目可直接统计，无需原子透传状态。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│ wa_tasks.py（策略层）                                        │
│  · 批后统计错误率 ≥30% → 风控冷却 20~30 分钟                 │
│  · 复用分段等待+心跳，stop_event 可中断                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ atom.run(numbers=50, account=xiaohao-1)
┌──────────────────────────▼──────────────────────────────────┐
│ wa_check.py 原子（只报告，不决策）                            │
│  · 子进程调 check.js，超时公式 +360s 重试预算                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ WA_AUTH_DIR / WA_DELAY_* / WA_RESULTS
┌──────────────────────────▼──────────────────────────────────┐
│ check.js（协议层）                                            │
│  · 单号 onWhatsApp 失败 → 退避→重连→重试（≤2 次）             │
│  · 连续失败 ≥5 → 判定风控，中止本批，剩余号码记 error          │
│  · 重连抛 fatal（登出）→ 中止本批，交下批 FATAL 检测           │
└─────────────────────────────────────────────────────────────┘
```

## 组件 / 模块设计

### check.js（协议层）

新增常量（`process.env` 覆盖，与 `WA_DELAY_MIN/MAX` 同模式）：

```js
const MAX_RETRIES        = parseInt(process.env.WA_QUERY_RETRIES        || '2'); // 单号重试次数（+首次 = 最多 3 次尝试）
const THROTTLE_THRESHOLD = parseInt(process.env.WA_THROTTLE_THRESHOLD  || '5');  // 连续失败达到即判风控
const RETRY_BACKOFF_MS   = 3000;                                                  // 退避基值：第 1 次 3s、第 2 次 6s
```

主循环包装：

```
for 每个号码:
    if throttled:  push {registered:null, error:'批次已风控中止'}; continue
    for attempt = 0..MAX_RETRIES:
        try:
            res = sock.onWhatsApp(num)
            push 结果; consecutiveFails = 0; break
        catch e:
            consecutiveFails++
            if consecutiveFails >= THROTTLE_THRESHOLD:
                throttled = true
                push {registered:null, error:'Connection Closed×N 疑似风控，中止本批'}
                break
            if attempt < MAX_RETRIES:
                sleep(退避 3s/6s)
                sock = connectWithRetry(state, saveCreds, version, 3)  // 复用现有重连
            else:
                push {registered:null, error:e.message}                 // 重试耗尽，保持 NULL
                break
```

收尾：`results.json` 增加 `throttled: true`（仅风控中止时写入，纯调试信息）。

### wa_tasks.py（策略层）

模块常量：

```python
THROTTLE_RATIO        = 0.3      # 批内错误率 ≥30% 判定疑似风控
THROTTLE_COOLDOWN_MIN = 1200.0   # 风控后额外冷却 20~30 分钟（随机）
THROTTLE_COOLDOWN_MAX = 1800.0
```

- 每批 OK 分支内统计 `err_cnt / len(results)`，≥ 阈值 → warning 事件 + `throttle_rest = True`
- 抽 `_rest_with_heartbeat(task_id, seconds, label, stop_event) -> bool` 复用现有「分段等待 + 心跳 + 可中断」；普通批间休息与风控冷却都走它
- 风控冷却在错误批之后**立即生效**（不等 `batch_num` 边界）
- 准确性小修：`checked += done`（实际有结果的数）而非 `checked += len(batch)`

### wa_check.py 原子（仅超时）

```python
# 重试预算：连续 5 个号码各重试 2 次（退避+重连）的最坏耗时，上浮余量。
# 因风控中止让额外时间有上限，故用固定 +360s，不随号码数放大。
timeout = (60 + len(numbers) * (delay_max + 5)) * 1.2 + 360
```

## 数据流

```
查询失败(Connection Closed)
  ├─ 单号偶发 → check.js 重连重试(≤2) → 成功出结果 / 失败记 error
  ├─ 连续 ≥5   → check.js 中止本批 → 剩余号码记 error + results.throttled=true
  └─ 重连 fatal → 中止本批 → 下批由原子 FATAL 检测接住
                        ↓
          atom 返回 results（含 registered:null 的错误条目）
                        ↓
wa_tasks.py：错误率 ≥30% → warning + 风控冷却 → 下一批
  同时 _apply_results 跳过 registered:null（保持 NULL=未查）
                        ↓
      下轮任务 _fetch_pending_rows（wa_checked_at IS NULL）自动补查
```

## 边界情况

| 场景 | 处理 |
|---|---|
| 单号偶发失败（失败计数不连续） | 重试 2 次后记 error → NULL，下轮补查，不误触中止 |
| 重连抛 fatal（真登出） | 置 throttled 中止本批，下批由原子 FATAL 检测接住 |
| 风控中止后剩余号码 | 全部记 error → NULL，下轮补查（配合批级冷却） |
| 原子超时 | 公式 +360s 预算，风控重试最坏情况（前 5 号×3 次尝试）有上限 |
| 静默空数组假阴性（不抛错） | **已知限制，不在本次范围**：重试抓不到无异常的空返回。证据表明风险低（批次 11 是错误风暴而非整批静默未注册）；批次 11 临界 14 号仍建议人工抽验 |

## 实施建议

### 实现步骤（按依赖顺序）

1. **check.js**：加常量 + 重试循环 + 连续失败中止 + `throttled` 字段
2. **wa_check.py**：超时公式 +360s
3. **wa_tasks.py**：抽 `_rest_with_heartbeat` + 错误率统计 + 风控冷却 + `checked` 计数修正
4. 手动冒烟：`node check.js --auth=xiaohao-1 <1 个号码>` 确认重试路径不破坏正常查询

### 测试策略

- **check.js 重试逻辑**：单测覆盖「连续失败中止」「重试成功后继续」「重试耗尽记 error」三态（mock `onWhatsApp`）
- **wa_tasks.py 冷却**：单测覆盖「错误率 ≥30% → warning + 冷却」「<30% → 不冷却」「心跳可被 stop_event 中断」
- **回归**：既有 14 个 server 测试 + `fetcher/tests/test_wa_check.py`

### 验收标准

1. 手动注入一次 Connection Closed，单号自动重连后出结果，不再留下 NULL
2. 连续失败 5 个 → 本批中止、剩余号码全部 error、`throttled: true`
3. 错误率 ≥30% 的批次后出现「⏸ 疑似风控，额外冷却」日志，且冷却期可被停止
4. 数据语义不变：重试后仍失败的号码 `wa_registered` 仍为 NULL
