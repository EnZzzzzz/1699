=== git log ===
df1a925 refactor(fetcher): Step 2.2 loop 冷却 chokepoint——4 处等待点与策略冷却收敛至 _cooldown

=== diff --stat ===
 .../task-2.2-brief.md                              |  46 +++++++
 .../task-2.2-report.md                             | 136 +++++++++++++++++++++
 fetcher/fetcher/control/loop.py                    |  38 ++++--
 fetcher/fetcher/strategy/strategies.py             |   3 -
 4 files changed, 210 insertions(+), 13 deletions(-)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.2-brief.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.2-brief.md
new file mode 100644
index 0000000..a6894ca
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.2-brief.md
@@ -0,0 +1,46 @@
+# Step 2.2 brief — loop chokepoint + 4 处等待点收敛
+
+> 来源：PLAN.md Phase 2 Step 2.2 + SPEC §3.3。本文本是你的需求唯一来源。
+
+## 内容
+
+改 `fetcher/fetcher/control/loop.py`（只动这一个文件）：
+
+### 1. 新增 `_cooldown(seconds, reason)` chokepoint
+
+SPEC §3.3 的契约：唯一等待执行点。职责：
+- 写 `self.ctx.cooldown_until[reason] = time.time() + seconds`（WorkerContext 的该字段已在 Step 1.2 落地）；
+- 执行可中断等待，返回 True=被 stop 中断；
+- **保留现状两种等待展示路径**：长等待（批次休息/周期长休/启动退避，现状走 `wait_countdown` 带秒级倒计时状态行）与短等待（样本间隔，现状走 `ctx.wait` 无倒计时）的展示差异逐字保留——chokepoint 内部按调用方传的展示方式分支（参数或两个内部路径，你读现状后定，report 说明）。`wait_countdown`（board.py:134-148）保留不动，由 chokepoint 内部调用。
+
+### 2. 4 处既有等待点改经 chokepoint（时长公式逐字保留）
+
+| 位置（现状行号，以你读到的为准） | reason | 时长公式（逐字保留） | 展示路径 |
+|---|---|---|---|
+| :129-137 批次休息 | `"batch_rest"` | `random.uniform(cfg.batch_rest*0.9, cfg.batch_rest*1.1)` | 倒计时 |
+| :195-200 样本间隔 | `"sample_interval"` | `uniform(cfg.sample_min + wid*1.5, cfg.sample_max + wid*2.5)` | 静默（ctx.wait 口径） |
+| :203-213 周期长休 | `"periodic_rest"` | `uniform(cfg.rest_min, cfg.rest_max)` | 倒计时 |
+| :243-249 启动退避 | `"launch_backoff"` | `min(30*attempt, 120)` | 倒计时 |
+
+注意各点的现状细节（中断后的处理、日志文案、状态行内容）逐字保留——diff 对照时除了「等待调用换成 chokepoint + 时长计算可能挪成小函数」外不应有其他行为差异。
+
+### 3. `_process_item` 消费 `step.cooldown`
+
+策略执行后（现状 :386-394 一带）：`step.cooldown` 非空时调 `self._cooldown(step.cooldown, f"strategy:{name}")`；被中断则按现状 stop 路径退出（与现状策略内 `ctx.wait` 被中断返回 SKIPPED→「用户中断」的终局一致——读码确认现状中断后 loop 的走向，对齐它）。策略自己的 log/detail 输出（Step 2.1 已保留）照旧经现状 :393-394 的日志行打出。
+
+### 4. 顺手清理（review 已记的 deferred minor，可选）
+
+`BlockRestStrategy.__init__` 的 `self._params = params` 残留（run() 不读）可删——若删，属于 strategies.py 的一行改动，允许，report 说明。
+
+## 验收
+
+- [ ] loop.py 内 `ctx.wait`/`wait_countdown` 只出现在 `_cooldown` 一处（grep 证据）
+- [ ] 4 处等待的时长公式与迁移前逐字一致（report 附 diff 对照说明）
+- [ ] `_process_item` 正确消费 step.cooldown，中断语义与现状终局一致
+- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归（若有断言旧等待路径的既有测试失败，按旧契约处理：更新并逐条说明）
+
+## 约束
+
+- 只动 `control/loop.py`（+ 可选的 strategies.py 一行清理 + 必要测试更新）。
+- 不碰 board.py、engine.py、daemon_task.py、policy.py、atoms/。
+- 本 Step 不做运行冒烟（Phase 3 做）。
diff --git a/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.2-report.md b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.2-report.md
new file mode 100644
index 0000000..3f92b93
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-cooldown-p1/task-2.2-report.md
@@ -0,0 +1,136 @@
+# Step 2.2 report — loop chokepoint + 4 处等待点收敛
+
+> 需求来源：task-2.2-brief.md（PLAN Phase 2 Step 2.2 + SPEC §3.3）。
+> 本 Step 把 Step 2.1 留下的中间态（策略只输出 cooldown、无人执行）接上：
+> loop 新增 `_cooldown` chokepoint，4 处既有等待点与策略冷却全部改经它。
+
+## 1. 实现内容
+
+### 1.1 `_cooldown(seconds, reason, prefix=None)` chokepoint（loop.py:108-122）
+
+```python
+def _cooldown(self, seconds: float, reason: str,
+              prefix: str | None = None) -> bool:
+    self.ctx.cooldown_until[reason] = time.time() + seconds
+    if prefix is None:
+        return self.ctx.wait(seconds)
+    return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
+                          seconds, prefix,
+                          set_status=self.ctx.set_status)
+```
+
+- 先写 `cooldown_until[reason] = time.time() + seconds`（`cooldown_until`
+  唯一写入者，P1 只写不读，P3 调度器查询接口），再执行可中断等待；
+  返回 True=被 stop 中断（`ctx.wait`=`stop.wait(timeout)`、
+  `wait_countdown` 循环 `stop.wait(min(1,remain))`，语义未动）。
+
+**展示分支的设计选择**：用 `prefix: str | None` 单参数区分两条现状路径——
+`prefix=None` 走 `ctx.wait` 静默等待（样本间隔的现状口径）；`prefix` 非空走
+`wait_countdown`（board.py:134-148，保留未动），秒级倒计时状态行，前缀即
+现状的 `state_prefix` 文案（"批次休息"/"长休息"/"启动退避"）。选参数分支而
+非两个内部方法，是因为两条路径只差最后一行调用，拆成两个方法反而要在
+4+1 个调用点各记一套方法名；`prefix` 本身还顺带携带了倒计时文案，调用点
+一行自足。
+
+### 1.2 4 处等待点公式逐字对照
+
+| 位置 | reason | 迁移前时长公式 | 迁移后时长公式 | 展示 |
+|---|---|---|---|---|
+| 批次休息（原 :129-137） | `"batch_rest"` | `random.uniform(cfg.batch_rest * 0.9, cfg.batch_rest * 1.1)` | 同左，逐字未动 | 倒计时 `prefix="批次休息"` |
+| 样本间隔（原 :195-200） | `"sample_interval"` | `lo = cfg.sample_min + wid*1.5`；`hi = cfg.sample_max + wid*2.5`；`random.uniform(lo, hi)` | 同左，lo/hi 中间变量逐字未动 | 静默（`prefix=None`，原 `ctx.wait` 口径） |
+| 周期长休（原 :203-213） | `"periodic_rest"` | `random.uniform(cfg.rest_min, cfg.rest_max)` | 同左，逐字未动 | 倒计时 `prefix="长休息"` |
+| 启动退避（原 :243-249） | `"launch_backoff"` | `min(30 * attempt, 120)` | 同左，逐字未动 | 倒计时 `prefix="启动退避"` |
+
+各点现状细节逐字保留：
+- 批次休息：前置 `⏸ 第 N 批已采满…强制休息 X 分钟` 日志行、休息后
+  `batch_no += 1 / done_in_batch = 0 / ▶ 休息结束` 日志与
+  `set_status(batch=…, state="采集中")` 均未动；中断 `return self.stats` 未动。
+- 样本间隔：`set_status(state=f"{unit}间隔 {t:.1f}s")` 未动；中断
+  `return self.stats` 未动。
+- 周期长休：触发条件（`rest_every>0 and n_rest>0 and n_rest%rest_every==0
+  and not stopped()`）与 `☕ 已连续抓取…` 日志行未动；中断 return 未动。
+- 启动退避：`[!] 启动浏览器第 N/M 次失败…` 日志行未动；中断
+  `raise UserInterrupted("用户中断") from e` 未动。
+
+diff 对照结论：除「等待调用换成 `self._cooldown(...)`」外无其他行为差异；
+时长计算未挪小函数（原式本就在调用点一行内，保持原地）。
+
+### 1.3 `_process_item` 消费 `step.cooldown`（loop.py:404-413）
+
+策略执行后、照旧先打 `✓ 策略 {name} 完成: {step.detail}` 日志行（solved 时），
+然后：
+
+```python
+if step.cooldown and self._cooldown(
+        step.cooldown, f"strategy:{decision.strategy}"):
+    return "stop", 0
+```
+
+策略冷却走 `prefix=None` 静默路径——与迁移前一致（旧 Sleep/BackoffSleep/
+BlockRest 经 Sleep 原子 `ctx.wait(t)`，无倒计时状态行，SPEC §4 假设 2 已
+读码确认原子等待形式就是 `ctx.wait(t)`）。
+
+**中断语义对齐说明**（读码确认的现状终局）：迁移前策略内 `ctx.wait` 被中断
+时，stop 事件已被外部置位，策略返回 `StepResult(False, "用户中断")` →
+`_process_item` 不打完成日志 → `while not ctx.stopped()` 循环条件退出 →
+落到尾部 `return "stop", 0` → `run()` 中 `kind in ("abort","stop")` →
+`return self.stats`。新路径：`_cooldown` 返回 True 仅当同一 stop 事件被
+置位（同一 `ctx.wait`/`wait_countdown` 原语），直接 `return "stop", 0`，
+终局逐字一致——同一返回值、同一 run() 出口、同样不记 giveup/abort。
+差异仅在少绕一圈 while 条件判断，无可观察行为差。
+
+### 1.4 顺手清理（brief §4 可选项，已做）
+
+删 `BlockRestStrategy.__init__`（strategies.py 原 :91-93）：迁移后 run()
+只读 `ctx.config`，`self._params = params` 是死字段；全仓 grep 确认实例化
+点仅 `default_strategies()` 的 `BlockRestStrategy()` 无参调用，删整个空转
+`__init__` 而非留 `pass`（3 行改动，report 在此说明）。
+
+## 2. 既有测试更新
+
+**无**。全量 243 通过、零失败，没有任何既有测试断言 loop 的旧等待路径
+（`test_control_loop.py` 的 FakeStrategy 不产 cooldown，走原路径不触新
+分支；`test_cooldown_contract.py` 是 Step 1.2/2.1 的契约测试，不受 loop
+改动影响）。故无「按旧契约更新」的条目。
+
+## 3. grep 证据
+
+```
+$ grep -n "ctx.wait\|wait_countdown" fetcher/fetcher/control/loop.py
+29:from fetcher.control.board import wait_countdown
+113:        展示两路径逐字保留现状：prefix 非空走 wait_countdown（秒级倒计
+114:        时状态行，长等待用）；prefix=None 走 ctx.wait（静默，短等待用）。
+118:            return self.ctx.wait(seconds)
+119:        return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
+409:            # ctx.wait 中断 → 循环条件退出 → return "stop" 的终局一致）
+```
+
+实际调用仅 `_cooldown` 内 :118/:119 两处；其余为 import、docstring、注释。
+
+## 4. 测试结果
+
+- 聚焦：`pytest tests/test_control_loop.py tests/test_cooldown_contract.py
+  -x -q` → 24 passed。
+- 全量（commit 前）：`cd fetcher && python -m pytest tests -x -q` →
+  **243 passed, 2 subtests passed in 7.23s**，零回归。
+- 运行冒烟未做（brief 约束：Phase 3 做）。
+
+## 5. 改动文件
+
+- `fetcher/fetcher/control/loop.py`：+`import time`；新增 `_cooldown`
+  （:108-122）；4 处等待点改经 chokepoint；`_process_item` 消费
+  `step.cooldown`。
+- `fetcher/fetcher/strategy/strategies.py`：删 `BlockRestStrategy.__init__`
+  死字段（brief §4 允许的可选清理）。
+
+未碰 board.py / engine.py / daemon_task.py / policy.py / atoms/。
+
+## 6. 疑虑
+
+- 策略冷却的 reason 用 `f"strategy:{decision.strategy}"`（决策表里的策略
+  名，即 `strategy.name` 的注册键），与 SPEC §3.3 的
+  `f"strategy:{strategy.name}"` 等价（default_strategies 以 name 为键
+  注册，policy 按名解析）。
+- 中断时 `cooldown_until[reason]` 仍保留已登记的截止时间（先登记后等待的
+  契约如此）；P1 无人读，无影响，P3 调度器读到过期/中断残留值时按
+  `time.time()` 比较自然失效。
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index e898d57..a214e94 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -16,20 +16,21 @@ item 级重试循环 → 收尾清理），但风控状态机不再写死在控
     - SeedBurnTracker：首请求秒拦/登录墙记到种子头上，烧毁后
       session.seed_kit=None，后续重启按白板会话；
     - 网络层错误（NET_ERROR/BROWSER_DEAD/IP_ROTATED）不计入熔断；
     - 熔断按店计（每店首个风控类失败计 1），同一店的重试链不累计，
       防单个慢/卡店铺中止整个任务。
 """
 
 from __future__ import annotations
 
 import random
+import time
 
 from fetcher.atoms.browser_ops import RelaunchBrowser
 from fetcher.control.board import wait_countdown
 from fetcher.control.circuit import CircuitBreaker
 from fetcher.control.task import Task
 from fetcher.core.errors import UserInterrupted
 from fetcher.core.session import Session
 from fetcher.core.types import Outcome, Scenario
 from fetcher.detect.base import SceneInspector
 from fetcher.net.seeds import SeedBurnTracker
@@ -95,20 +96,37 @@ class CrawlLoop:
 
     # ---- 日志 / 状态行 ----
 
     @property
     def tag(self) -> str:
         return f"[w{self.ctx.wid}]"
 
     def log(self, msg: str):
         self.ctx.log(f"{self.tag} {msg}")
 
+    # ---- 冷却 chokepoint（SPEC §3.3：唯一等待执行点）----
+
+    def _cooldown(self, seconds: float, reason: str,
+                  prefix: str | None = None) -> bool:
+        """登记冷却截止时间 + 执行可中断等待。返回 True=被 stop 中断。
+
+        cooldown_until 的唯一写入者（P1 只写不读，P3 调度器查询接口）。
+        展示两路径逐字保留现状：prefix 非空走 wait_countdown（秒级倒计
+        时状态行，长等待用）；prefix=None 走 ctx.wait（静默，短等待用）。
+        """
+        self.ctx.cooldown_until[reason] = time.time() + seconds
+        if prefix is None:
+            return self.ctx.wait(seconds)
+        return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
+                              seconds, prefix,
+                              set_status=self.ctx.set_status)
+
     # ---- 主流程 ----
 
     def run(self) -> dict:
         """worker 完整生命周期；返回本 worker 的统计字典。"""
         cfg = self.ctx.config
         self.ctx.state["warm"] = True  # 新会话冷启动软着陆标记
         try:
             self.ctx.set_status(state="启动浏览器…", force=True)
             self._launch_with_retry()
             self.log(f"浏览器就绪，出口 IP={self.ctx.identity}"
@@ -124,23 +142,21 @@ class CrawlLoop:
                     if cfg.max_batches and self.batch_no >= cfg.max_batches:
                         self.log(f"第 {self.batch_no} 批采满，"
                                  f"已达批次上限（--max-batches），收工")
                         self.ctx.set_status(state="收工")
                         return self.stats
                     rest = random.uniform(cfg.batch_rest * 0.9,
                                           cfg.batch_rest * 1.1)
                     self.log(f"⏸ 第 {self.batch_no} 批已采满 "
                              f"{cfg.batch_num} 个{self.task.batch_unit}，"
                              f"强制休息 {rest / 60:.1f} 分钟（防风控）...")
-                    if wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
-                                      rest, "批次休息",
-                                      set_status=self.ctx.set_status):
+                    if self._cooldown(rest, "batch_rest", prefix="批次休息"):
                         return self.stats
                     self.batch_no += 1
                     self.done_in_batch = 0
                     self.log(f"▶ 休息结束，开始第 {self.batch_no} 批")
                     self.ctx.set_status(batch=self.batch_no, state="采集中")
 
                 # ---- 冷启动（acquire 前的任务，如先逛首页填类目池）----
                 if self.task.cold_start_before_acquire and self._take_warm():
                     self.ctx.set_status(state="冷启动软着陆…")
                     self.task.cold_start(self.ctx, None)
@@ -189,34 +205,32 @@ class CrawlLoop:
                 if cfg.limit and self.total_done >= cfg.limit:
                     self.log(f"已达本次采集上限（--limit {cfg.limit}），收工")
                     self.ctx.set_status(state="收工")
                     return self.stats
 
                 # ---- 样本间隔（按 worker 编号递增错峰，避免集群同频）----
                 lo = cfg.sample_min + self.ctx.wid * 1.5
                 hi = cfg.sample_max + self.ctx.wid * 2.5
                 t = random.uniform(lo, hi)
                 self.ctx.set_status(state=f"{self.task.unit}间隔 {t:.1f}s")
-                if self.ctx.wait(t):
+                if self._cooldown(t, "sample_interval"):
                     return self.stats
 
                 # ---- 周期性随机长休息（模拟真人连续浏览后的停顿）----
                 n_rest = self.task.rest_counter(self.stats)
                 if (cfg.rest_every > 0 and n_rest > 0
                         and n_rest % cfg.rest_every == 0
                         and not self.ctx.stopped()):
                     t = random.uniform(cfg.rest_min, cfg.rest_max)
                     self.log(f"☕ 已连续抓取 {n_rest} 个{self.task.unit}，"
                              f"随机长休息 {t / 60:.1f} 分钟 ...")
-                    if wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
-                                      t, "长休息",
-                                      set_status=self.ctx.set_status):
+                    if self._cooldown(t, "periodic_rest", prefix="长休息"):
                         return self.stats
         except UserInterrupted:
             pass
         except Exception as e:  # noqa: BLE001
             self.log(f"[X] worker 异常退出: {e}")
         finally:
             self._cleanup()
         return self.stats
 
     # ---- 启动 / 收尾 ----
@@ -236,23 +250,21 @@ class CrawlLoop:
                     seed_kit=self.seed_tracker.kit, stop=self.ctx.stop)
                 self.seed_tracker.kit = self.ctx.session.seed_kit
                 return
             except UserInterrupted:
                 raise
             except (Exception, SystemExit) as e:  # noqa: BLE001
                 last_err = e
                 backoff = min(30 * attempt, 120)
                 self.log(f"  [!] 启动浏览器第 {attempt}/{cfg.ip_retry} "
                          f"次失败: {e}，{backoff}s 后重试...")
-                if wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
-                                  backoff, "启动退避",
-                                  set_status=self.ctx.set_status):
+                if self._cooldown(backoff, "launch_backoff", prefix="启动退避"):
                     raise UserInterrupted("用户中断") from e
         raise RuntimeError(f"启动浏览器重试 {cfg.ip_retry} 次仍失败: {last_err}")
 
     def _cleanup(self):
         """退出前回写 Cookie、关浏览器（任何路径都走这里）。"""
         session = self.ctx.session
         if session is not None:
             session.close(store=self.ctx.store, log=self.ctx.log)
             self.ctx.session.browser = None
         self.ctx.set_status(state="已退出", force=True)
@@ -385,20 +397,26 @@ class CrawlLoop:
             # ---- 执行策略后重试同一任务项 ----
             strategy = self.policy.strategies[decision.strategy]
             ctx.state["attempt"] = decision.attempt
             ctx.set_status(state=f"处置: {decision.strategy}"
                                  f"（{decision.attempt} 次）")
             self.log(f"⚠ {reason} → 策略 {decision.strategy}"
                      f"（第 {decision.attempt} 次）")
             step = strategy.run(ctx)
             if step.solved:
                 self.log(f"✓ 策略 {decision.strategy} 完成: {step.detail}")
+            # 策略冷却经 chokepoint 执行（Step 2.1 起策略只算时长不自
+            # 等）；被 stop 中断按现状 stop 路径退出（与旧策略内
+            # ctx.wait 中断 → 循环条件退出 → return "stop" 的终局一致）
+            if step.cooldown and self._cooldown(
+                    step.cooldown, f"strategy:{decision.strategy}"):
+                return "stop", 0
         return "stop", 0
 
     # ---- 簿记 ----
 
     def _bookkeep_request(self, scenario: Scenario):
         """tmd 计数：请求到了目标站才计（网络层错误不算）。"""
         if scenario in _NO_REQUEST_SCENARIOS or self.ctx.store is None:
             return
         identity = self.ctx.identity
         ctr = self.ip_req.setdefault(identity, {"n": 0, "since": 0})
diff --git a/fetcher/fetcher/strategy/strategies.py b/fetcher/fetcher/strategy/strategies.py
index a8ac059..7290fd7 100644
--- a/fetcher/fetcher/strategy/strategies.py
+++ b/fetcher/fetcher/strategy/strategies.py
@@ -81,23 +81,20 @@ class BackoffSleepStrategy:
 
 class BlockRestStrategy:
     """风控原地休息：当前 IP 上长休息后再试（block_rest_min~max）。
 
     时长在 run 时从 ctx.config 取，保证任务级覆盖生效；分布与 Sleep
     同款（对数正态）。只算时长输出冷却，不自己等待（等待由控制层执行）。
     """
 
     name = "block_rest"
 
-    def __init__(self, **params):
-        self._params = params
-
     def run(self, ctx) -> StepResult:
         lo = float(ctx.config.block_rest_min)
         hi = float(ctx.config.block_rest_max)
         ctx.log(f"    ⚠ 风控休息：保持当前 IP {ctx.identity}，"
                 f"休息 {lo / 60:.0f}~{hi / 60:.0f} 分钟后重试")
         t = human_pause_duration(lo, hi)
         return StepResult(True, f"等待 {t:.1f}s", cooldown=t)
 
 
 class RefreshStrategy(_AtomStrategy):
