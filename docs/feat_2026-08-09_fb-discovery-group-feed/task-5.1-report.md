# Step 5.1 端到端闭环冒烟 — 报告

**执行时间**: 2026-08-09 23:05 — 23:55
**执行者**: Claude (pi coding agent)
**状态**: **BLOCKED**（daemon 本地消费者在处理 fb_group FATAL 后停滞，证据完整但环节③④⑤未完成）

---

## 1. 环境确认

| 组件 | 状态 | 详情 |
|---|---|---|
| daemon | 运行中 | PID 30020，`--workers 1 --headed`，全量队列（含 discover_fb/crawl_fb_group） |
| backend | :8765 | 正常响应 |
| frontend | :3000 | 正常响应 |
| DDG | 可达但限流 | 5 词中 4 词 HTTP 202，1 词 200 |
| BRIGHTDATA_API_KEY | 未设置 | fb_group FATAL 预期路径 |
| WA_CHECK_ACCOUNTS | xiaohao-4,xiaohao-5 | WhatsApp 连接均返回 403 |

---

## 2. 基线（冒烟前）

| 表 | 计数 | 备注 |
|---|---|---|
| fb_posts | 299 total, 0 source='ddg', 0 source='fb_post' | |
| fb_groups | 0 | |
| fb_contacts | 164 | |
| discover_fb items | 7 stopped (Step 3.4 残留) | |
| crawl_fb_group items | 0 | |
| wa_check items | 2 claimed, 44 done, 206 failed, 56 pending | |

---

## 3. 执行过程

### 3.1 看板（验收5）

**API**: `GET /api/dispatcher/status`

discover_fb 队列在任务创建前已存在（Step 3.4 残留 7 stopped）。
crawl_fb_group 队列在 fb_group 任务 start 后出现。

最终状态：
```json
{
  "discover_fb": {"done": 1, "failed": 4, "pending": 1, "stopped": 7},
  "crawl_fb_group": {"failed": 2, "stopped": 3}
}
```

✅ 两条队列均在看板出现。

### 3.2 fb_discover 任务（验收1）

**任务 #94**: 默认矩阵 5 词 × 1 页

| 时间 | 事件 |
|---|---|
| 23:06:01 | 任务创建，status=pending |
| 23:06:03 | start → 5 items 入队 (25628-25632) |
| 23:28:53 | local0 认领 25628「外贸 whatsapp」→ DDG HTTP 202 |
| 23:29:26 | local1 认领 25629「跨境电商 whatsapp」→ DDG HTTP 202 |
| 23:34:05 | 25629 failed（202 backoff 退避后） |
| 23:34:08 | 25628 failed（202 backoff 退避后） |
| 23:34:05 | local1 认领 25630「china sourcing whatsapp」→ DDG HTTP 202 |
| 23:34:08 | local0 认领 25631「货代 微信」→ DDG HTTP 202 |
| 23:38:40 | 25630 failed（202 backoff 退避后） |
| 23:39:23 | 25631 failed（202 backoff 退避后） |
| 23:38:40 | local1 认领 25632「亚马逊卖家 微信」→ DDG HTTP 200 ✓ |
| 23:39:42 | 25632 done，fb_posts +1 (source='ddg')，fb_groups +10 |

**实测节奏**：
- 202 退避 item 耗时 ~4:30-5:00（202 backoff 180-240s + rhythm 60-80s）
- 成功 item 25632 耗时 ~1:02（2s HTTP + 60s rhythm）
- 总耗时 33 分钟（含 wa_check 清空前等待 23 分钟，实际 DDG 消费仅 10 分钟）

**DDG 退避统计**：4/5 词 HTTP 202，1/5 词 HTTP 200。

**产出**：
- fb_posts: 299→301（+2；1 条 source='ddg'，1 条 source='manual' 为其他进程插入）
- DDG 帖：id=389，url=`.../groups/998209149203973/permalink/1074140828277471/`，keyword=`site:facebook.com/groups 亚马逊卖家 微信`，source='ddg' ✓
- fb_groups: 0→10（全部 source='ddg'）

```
fb_posts source='ddg' 行：
  id=389 | url=...permalink/1074140828277471/ | keyword=site:facebook.com/groups 亚马逊卖家 微信 | group_id=998209149203973

fb_groups（10 行）：
  id=2  | .../groups/998209149203973 | 亚马逊 Chinese Seller \| 全法站...
  id=3  | .../groups/955358203951794 | 亚马逊卖家交流测评群
  id=4  | .../groups/597470626634414 | 亚马逊卖家交流测评群 拜耳集团
  id=5  | .../groups/3236460389869443 | 亚马逊 Chinese Seller >
  id=6  | .../groups/207077591913839 | 亚马逊 跨境电商中国卖家买家交流群
  id=7  | .../groups/1616659022817002 | 亚马逊中国卖家群
  id=8  | .../groups/854409570551431 | 亚马逊中国卖家群
  id=9  | .../groups/1218194852879615 | 跨境电商独立站交流群
  id=10 | .../groups/1397299455211398 | 亚马逊直评交流群
  id=11 | .../groups/1017305746353616 | 中国跨境电商私域、独立站交流平台
```

✅ fb_posts 出现 source='ddg' 的帖行，keyword 溯源正确。
✅ fb_groups 出现群行（SERP 群主页 + 帖派生群）。
✅ url UNIQUE 约束生效（无重复行）。
✅ 任务进度正确：done=1, failed=4, total=5。

### 3.3 fb_post 接续（验收3）

fb_discover 产生的 DDG 帖（id=389）被 daemon 的 crawl_fb_post 消费者自动接续：

```
work_item 25766 | queue=crawl_fb_post | url=...permalink/1074140828277471/
status=done | finished_at=2026-08-09 23:40:14
```

crawl_fb_post done 计数：305→306（+1，即该 DDG 帖）。

fb_contacts 无新增（该帖内容不含联系方式，预期行为）。

fb_groups 无帖派生群（该 DDG 帖的群已在发现阶段落入 fb_groups 表）。

✅ fb_post 接续链路验证通过：DDG 帖 → crawl_fb_post 自动消费 → done。
⚠️ 因无新增 pending fb_posts，无法创建独立 fb_post 批次任务验证 enqueue 路径。
  现有 crawl_fb_post 306 done + 26 failed 证明管道长期可用。

### 3.4 fb_group 任务（验收2，缺 key FATAL 路径）

**任务 #95**: provider=brightdata, posts_per_group=50, limit=5

| 时间 | 事件 |
|---|---|
| 23:46:47 | 任务创建 |
| 23:46:52 | start → 5 items (25768-25772)，fb_groups 5 行 → in_progress |
| 23:47:17 | local0 认领 25768 → FATAL「缺少 Bright Data API key」→ failed；群 #2 → failed |
| 23:48:00 | local1 认领 25769 → FATAL「缺少 Bright Data API key」→ failed；群 #3 → failed |
| 23:48:00+ | **本地消费者停滞**（详见 §4） |
| 23:55:54 | 任务 stop → 剩余 3 items 置 stopped |

**群状态机流转**：
```
群 #2: pending → in_progress → failed (result: 缺少 Bright Data API key)
群 #3: pending → in_progress → failed (result: 缺少 Bright Data API key)
群 #4-6: pending → in_progress → stopped (消费者停滞)
群 #7-11: pending（未被选中）
```

✅ FATAL→failed 真实路径验证通过（缺 BRIGHTDATA_API_KEY）。
✅ 群状态机 pending→in_progress→failed 流转正确。
✅ result_json 含缺 key detail。
⚠️ 仅 2/5 items 完成（消费者停滞导致剩余 3 items 无法处理）。
ℹ️ done 路径已由 Step 2.4 mock 覆盖，本 Step 不需验证。

### 3.5 wa_check 观察（验收4）

❌ **无法验证**：daemon 本地消费者在 fb_group FATAL 后停滞。wa_check 仍维持 131 pending + 505 stopped（冒烟前 bulk-stop 操作），无新消费。

观察记录：
- wa_check topup 机制活跃（从 cn_uncertain 桶持续补货，每周期 ≤4 items）
- topup 与 discover_fb/crawl_fb_group 共享本地消费者池产生竞争
- 消费者停滞期间无法观察新号入队

---

## 4. 关键问题：daemon 本地消费者停滞

### 现象
- 2026-08-09 23:48:00 后，daemon 本地消费者（local0/local1）完全停止处理 work_items
- daemon 日志最后 5 行（23:48:00 后无新输出）：
  ```
  [finish] item=25654 status=failed @2026-08-09 23:48:00
  [claim] queue=crawl_fb_group item=25769 site=None @2026-08-09 23:48:00
  [finish] item=25769 status=failed @2026-08-09 23:48:00
  ```
- consumer_status 心跳仍在更新（显示 queue=None, item=None, offline=false）
- browser consumer w0 正常（等待 site cooldown 到期）
- daemon PID 30020 处于 S（sleeping）状态

### 疑似原因

daemon 昨天启动时的日志中出现了相同错误模式：
```
[X] local 消费者异常退出: list index out of range
  File "local_loop.py", line 48, in run
    self.ctx.set_status(state="执行中…")
  File "engine.py", line 274, in <lambda>
    ctx.set_status = lambda **kw: board.set(wid + 10000, **kw)
  File "board.py", line 99, in set
    f = self.fields[wid]
IndexError: list index out of range
```

board.py 的 `fields` 列表可能未为 local 消费者的 wid 分配足够槽位（`wid + 10000` 越界）。

今天 23:48 的停滞与昨天错误的关联待定：今天日志中无新 traceback（日志文件自 23:48 未更新），
可能消费者已静默退出（心跳线程独立运行持续更新 consumer_status 造成"存活"假象）。

### 影响
- 3 个 fb_group items 滞留 pending（后置 stopped）
- 131 个 wa_check items 滞留 pending（topup 补货但无消费者消费）
- discover_fb / crawl_fb_group 队列不可用
- 浏览器 consumer w0 不受影响

---

## 5. 验收判定

| 验收标准 (SPEC §10) | 状态 | 证据 |
|---|---|---|
| **1. fb_discover 任务** → fb_posts source='ddg' + fb_groups，keyword 溯源，无重复 | ✅ 满足 | 1 ddg 帖 + 10 群；keyword 正确；url UNIQUE 生效 |
| **2. fb_group 任务** → FATAL→failed，群状态机流转 | ⚠️ 部分 | 2/5 验证 FATAL→failed + 状态机；3 items 因 daemon 停滞未完成 |
| **3. fb_post 接续** | ✅ 满足 | DDG 帖自动被 crawl_fb_post 消费（306→306）；独立批次未创（无 pending） |
| **4. wa_check 自动涵盖** | ❌ 未验证 | 消费者停滞，无法观察新号入队 |
| **5. dispatcher 看板两条队列** | ✅ 满足 | discover_fb (done=1,failed=4) + crawl_fb_group (failed=2,stopped=3) |

---

## 6. 实测数据汇总

| 指标 | 值 |
|---|---|
| fb_discover 总耗时 | ~33 min（含 23 min wa_check 清空等待，实际 DDG 10 min） |
| DDG 成功率 | 1/5 (20%) |
| DDG 202 退避 item 耗时 | ~4:30-5:00 min |
| DDG 成功 item 耗时 | ~1:02 min |
| 202 退避次数 | 4/5 |
| fb_posts 增量 | +2（1 ddg + 1 manual 其他进程） |
| fb_groups 增量 | +10 (all source='ddg') |
| fb_contacts 增量 | 0 |
| fb_group 处理耗时 (FATAL) | <1s/item |

---

## 7. 疑虑/观测

1. **DDG 限流严重**：5 词仅 1 词通过（20%），4 词 HTTP 202。spike 预期的「2 连查后封」在本环境
   表现为首两词即封——可能 DDG 当前处于限流期（协调者 22:00 前实测可达，但窗口已过期）。
2. **wa_check 与 fb 队列竞争**：wa_check topup 无限补货 + FIFO 认领导致 fb 队列饥饿。
   冒烟中需 bulk-stop wa_check 131 items 三次才能让 discover_fb 获得消费者。
3. **daemon 本地消费者脆弱性**：board.py fields 越界是已知问题（昨日启动即出现），
   今天 23:48 后停滞待进一步调查。
4. **fb_posts 0 pending**：fb_discover 单帖被 crawl_fb_post 即刻消费，导致无法创建有意义的
   独立 fb_post 批次任务。需多轮 discover 积累 pending 后再测。
