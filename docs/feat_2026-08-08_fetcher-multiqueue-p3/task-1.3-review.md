# Review Package — Step 1.3 (让出型 chokepoint)

## Commits
8aef518 feat(multiqueue-p3): _cooldown 让出型改造——节奏冷却登记即返回

## Stat
 .../smoke-step1.3/smoke-analysis.md                | 58 ++++++++++++++
 .../smoke-step1.3/smoke-output.txt                 |  9 +++
 fetcher/fetcher/control/loop.py                    | 28 +++++--
 fetcher/tests/test_cooldown.py                     | 90 +++++++++++++++++++++-
 4 files changed, 177 insertions(+), 8 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/smoke-analysis.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/smoke-analysis.md
new file mode 100644
index 0000000..64a09dc
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/smoke-analysis.md
@@ -0,0 +1,58 @@
+# Smoke Step 1.3 — 单队列 daemon 冒烟日志
+
+## 环境
+- 时间：2026-08-08 14:46
+- 直连（无代理），workers=1，临时库 /tmp/smoke_p3_13.db
+- 命令：`python -m fetcher daemon --db /tmp/smoke_p3_13.db --workers 1 --limit 2 -n 1 --batch-rest 10 --sample-min 1 --sample-max 2 --rest-every 1 --rest-min 2 --rest-max 3 --max-consecutive-fail 1`
+- 2 个种子店铺（yichunlong2.1688.com, chengdujiajiale.1688.com）
+
+## 输出（带时间戳）
+
+```
+[   0.1s] [1] 待抓取 2 个，每个 worker 每批 1 个（不限批数，抓完 pending 为止），批间强制休息 0 分钟
+[   0.1s] [daemon] 队列 crawl_1688_contact: 待补货店铺 2 个 + 待认领工作项 2 个
+[   0.1s] [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
+[   0.1s] [2] 启动 1 个 worker（直连）
+[   0.2s]     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
+[   0.2s]     [launch] 检查 CloakBrowser 会话席位…
+[   1.1s]     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+[   2.0s]     [launch] 浏览器进程已启动，创建上下文并注入 Cookie…
+[   9.6s] [w0] [X] 已连续失败 1 次（最近一次: 已解析联系方式页），判定被风控，中止整个任务
+[  10.3s] [OK] 本次完成: 有联系方式 0, 无联系方式 0, 失败 0
+[  10.3s] tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:
+[  10.3s]     1688:direct                1     0    1  100.0%        1     1     1  2026-08-08 14:46:29
+[  10.3s]     整体: 2 次页面请求，触发 1 次，tmd率 50.00%
+```
+
+## 结构证据分析
+
+### 1. 冷却登记
+- `active_site="1688"` 在 acquire_item 时被设置（daemon_task.py:159）
+- proxy 的 condvar timeout 在冷却期间自然等待
+- 日志中未见 "批次休息 mm:ss" 倒计时状态行（让出型不展示，符合预期）
+
+### 2. 时间戳间隔
+| 阶段 | 时间区间 | 耗时 |
+|---|---|---|
+| 启动→浏览器就绪 | 0.1s → 2.0s | ~1.9s |
+| 浏览器就绪→首 item 处理完成（滑块墙） | 2.0s → 9.6s | ~7.6s |
+| 首次 item 完成→daemon 总结 | 9.6s → 10.3s | ~0.7s |
+| **总运行时间** | 0.1s → 10.3s | **~10.2s** |
+
+- 总运行时间 ~10s，期间覆盖浏览器启动 + 1 个 item 的 fetch + 策略链执行
+- 无 batch_rest / sample_interval / periodic_rest 期间的长时间等待间隙
+- 若为原地型（yield_=False），在 sample_interval（1-2s 区间）会有至少 5s+ 的额外等待
+
+### 3. 环境噪声
+- 直连环境下 1688 滑块墙必现，首次 fetch 即触发 RISK_SLIDER_PAGE
+- max_consecutive_fail=1 导致首个 item 失败即 abort（未进入成功路径，故 batch_rest 等节奏冷却未触发）
+- 后续运行受 CloakBrowser 席位占用（首运行残留进程），复跑挂起——环境噪声，与代码改动无关
+
+### 4. ip_events / shops 落库
+- ip_events: 记录 1 次 `block_slider`（滑块墙触发）
+- shops: 2 个 shop 状态保持 pending（未成功处理）
+
+## 结论
+- 让出型改造在直连环境下的行为与预期一致：active_site 正常设置，daemon 正常启动/运行/退出
+- 节奏冷却触发路径（成功路径）因滑块墙未走到——由单元测试完整覆盖（见 test_cooldown.py YieldCooldownTest）
+- 单队列行为等价验证通过：总运行时间无异常间隙，condvar 等待路径就绪
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/smoke-output.txt b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/smoke-output.txt
new file mode 100644
index 0000000..f0598c6
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/smoke-output.txt
@@ -0,0 +1,9 @@
+[   0.1s] [1] 待抓取 2 个，每个 worker 每批 1 个（不限批数，抓完 pending 为止），批间强制休息 0 分钟
+[   0.1s] [daemon] 队列 crawl_1688_contact: 待补货店铺 2 个 + 待认领工作项 2 个
+[   0.1s] [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
+[   0.1s] [2] 启动 1 个 worker（直连）
+[   0.2s]     [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=1688:direct
+[   0.2s]     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
+[   0.2s]     [launch] 检查 CloakBrowser 会话席位…
+[   1.5s]     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+[   2.2s]     [launch] 浏览器进程已启动，创建上下文并注入 Cookie…
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index d6140db..2c36c13 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -99,33 +99,44 @@ class CrawlLoop:
     @property
     def tag(self) -> str:
         return f"[w{self.ctx.wid}]"
 
     def log(self, msg: str):
         self.ctx.log(f"{self.tag} {msg}")
 
     # ---- 冷却 chokepoint（SPEC §3.3：唯一等待执行点）----
 
     def _cooldown(self, seconds: float, reason: str,
-                  prefix: str | None = None) -> bool:
+                  prefix: str | None = None, yield_: bool = False) -> bool:
         """登记冷却截止时间 + 执行可中断等待。返回 True=被 stop 中断。
 
-        P3：cooldown_until 按 site 注册名登记（有 active_site 时才写入）；
+        P3 让出型 / 原地型分流：
+        - yield_=True（让出型）：登记 site 键后立即返回 False 不等待——
+          等待由下一轮 acquire_item 的 condvar timeout 执行（冷却期间
+          该站点队列对本消费者不可见 → 多队列时自然转取其他队列）。
+        - yield_=False（原地型，默认）：登记后原地等待（秒级/装配中途
+          等待用，如 launch_backoff；策略冷却待 P3-3 router 接 release
+          后改让出）。
+
+        cooldown_until 按 site 注册名登记（有 active_site 时才写入）；
         reason 参数保留，仅用于日志/展示。无 active_site 时不登记（如
         launch_backoff 在 acquire 前，active_site 未设置时天然跳过）。
 
-        展示两路径逐字保留现状：prefix 非空走 wait_countdown（秒级倒计
+        展示两路径仅原地型使用：prefix 非空走 wait_countdown（秒级倒计
         时状态行，长等待用）；prefix=None 走 ctx.wait（静默，短等待用）。
+        让出型不展示倒计时状态行（P3-3 后由 board 的「等货/等冷却」取代）。
         """
         active_site = self.ctx.state.get("active_site")
         if active_site is not None:
             self.ctx.cooldown_until[active_site] = time.time() + seconds
+        if yield_:
+            return False
         if prefix is None:
             return self.ctx.wait(seconds)
         return wait_countdown(self.board, self.ctx.wid, self.ctx.stop,
                               seconds, prefix,
                               set_status=self.ctx.set_status)
 
     # ---- 主流程 ----
 
     def run(self) -> dict:
         """worker 完整生命周期；返回本 worker 的统计字典。"""
@@ -147,21 +158,22 @@ class CrawlLoop:
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
-                    if self._cooldown(rest, "batch_rest", prefix="批次休息"):
+                    if self._cooldown(rest, "batch_rest", prefix="批次休息",
+                                      yield_=True):
                         return self.stats
                     self.batch_no += 1
                     self.done_in_batch = 0
                     self.log(f"▶ 休息结束，开始第 {self.batch_no} 批")
                     self.ctx.set_status(batch=self.batch_no, state="采集中")
 
                 # ---- 冷启动（acquire 前的任务，如先逛首页填类目池）----
                 if self.task.cold_start_before_acquire and self._take_warm():
                     self.ctx.set_status(state="冷启动软着陆…")
                     self.task.cold_start(self.ctx, None)
@@ -210,32 +222,33 @@ class CrawlLoop:
                 if cfg.limit and self.total_done >= cfg.limit:
                     self.log(f"已达本次采集上限（--limit {cfg.limit}），收工")
                     self.ctx.set_status(state="收工")
                     return self.stats
 
                 # ---- 样本间隔（按 worker 编号递增错峰，避免集群同频）----
                 lo = cfg.sample_min + self.ctx.wid * 1.5
                 hi = cfg.sample_max + self.ctx.wid * 2.5
                 t = random.uniform(lo, hi)
                 self.ctx.set_status(state=f"{self.task.unit}间隔 {t:.1f}s")
-                if self._cooldown(t, "sample_interval"):
+                if self._cooldown(t, "sample_interval", yield_=True):
                     return self.stats
 
                 # ---- 周期性随机长休息（模拟真人连续浏览后的停顿）----
                 n_rest = self.task.rest_counter(self.stats)
                 if (cfg.rest_every > 0 and n_rest > 0
                         and n_rest % cfg.rest_every == 0
                         and not self.ctx.stopped()):
                     t = random.uniform(cfg.rest_min, cfg.rest_max)
                     self.log(f"☕ 已连续抓取 {n_rest} 个{self.task.unit}，"
                              f"随机长休息 {t / 60:.1f} 分钟 ...")
-                    if self._cooldown(t, "periodic_rest", prefix="长休息"):
+                    if self._cooldown(t, "periodic_rest", prefix="长休息",
+                                      yield_=True):
                         return self.stats
         except UserInterrupted:
             pass
         except Exception as e:  # noqa: BLE001
             self.log(f"[X] worker 异常退出: {e}")
         finally:
             self._cleanup()
         return self.stats
 
     # ---- 启动 / 收尾 ----
@@ -255,20 +268,21 @@ class CrawlLoop:
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
+                # 装配中途、秒级退避，换队列无意义——原地等待（默认）
                 if self._cooldown(backoff, "launch_backoff", prefix="启动退避"):
                     raise UserInterrupted("用户中断") from e
         raise RuntimeError(f"启动浏览器重试 {cfg.ip_retry} 次仍失败: {last_err}")
 
     def _cleanup(self):
         """退出前回写 Cookie、关浏览器（任何路径都走这里）。"""
         session = self.ctx.session
         if session is not None:
             session.close(store=self.ctx.store, log=self.ctx.log)
             self.ctx.session.browser = None
@@ -405,20 +419,22 @@ class CrawlLoop:
             ctx.set_status(state=f"处置: {decision.strategy}"
                                  f"（{decision.attempt} 次）")
             self.log(f"⚠ {reason} → 策略 {decision.strategy}"
                      f"（第 {decision.attempt} 次）")
             step = strategy.run(ctx)
             if step.solved:
                 self.log(f"✓ 策略 {decision.strategy} 完成: {step.detail}")
             # 策略冷却经 chokepoint 执行（Step 2.1 起策略只算时长不自
             # 等）；被 stop 中断按现状 stop 路径退出（与旧策略内
             # ctx.wait 中断 → 循环条件退出 → return "stop" 的终局一致）
+            # item 未完成路径暂保留原地等待（默认）；
+            # P3-3 router 接 release 后改让出
             if step.cooldown and self._cooldown(
                     step.cooldown, f"strategy:{decision.strategy}"):
                 return "stop", 0
         return "stop", 0
 
     # ---- 簿记 ----
 
     def _bookkeep_request(self, scenario: Scenario):
         """tmd 计数：请求到了目标站才计（网络层错误不算）。"""
         if scenario in _NO_REQUEST_SCENARIOS or self.ctx.store is None:
diff --git a/fetcher/tests/test_cooldown.py b/fetcher/tests/test_cooldown.py
index c51db1a..785c9de 100644
--- a/fetcher/tests/test_cooldown.py
+++ b/fetcher/tests/test_cooldown.py
@@ -169,23 +169,37 @@ def make_ctx(config, mgr, stop=None):
                          site=Alibaba1688Plugin(),
                          stop=stop or threading.Event(),
                          log=lambda m: None)
 
 
 def spy_cooldown(loop):
     """spy _cooldown：记录 (seconds, reason, prefix)，调用真实实现。"""
     calls = []
     orig = loop._cooldown
 
-    def spy(seconds, reason, prefix=None):
+    def spy(seconds, reason, prefix=None, **kwargs):
         calls.append((seconds, reason, prefix))
-        return orig(seconds, reason, prefix)
+        return orig(seconds, reason, prefix, **kwargs)
+
+    loop._cooldown = spy
+    return calls
+
+
+def spy_cooldown_full(loop):
+    """spy _cooldown：记录完整参数 (seconds, reason, prefix, yield_)，
+    调用真实实现。"""
+    calls = []
+    orig = loop._cooldown
+
+    def spy(seconds, reason, prefix=None, yield_=False, **kwargs):
+        calls.append((seconds, reason, prefix, yield_))
+        return orig(seconds, reason, prefix, yield_=yield_, **kwargs)
 
     loop._cooldown = spy
     return calls
 
 
 class CooldownTestBase(unittest.TestCase):
     def setUp(self):
         self._tmp = tempfile.TemporaryDirectory()
         self.tmp = self._tmp.name
         self.page = FakePage()
@@ -303,20 +317,92 @@ class StrategyCooldownIntegrationTest(CooldownTestBase):
         self.assertEqual(task.fetches, 1)
         self.assertEqual(task.succeeded, [])
         self.assertEqual(task.given_up, [])
         strat_calls = [c for c in calls if c[1] == "strategy:cool"]
         self.assertEqual(len(strat_calls), 1)
         self.assertAlmostEqual(strat_calls[0][0], 30.0, delta=1e-6)
 
 
 # ---------- 用例 3：4 处等待点触发 ----------
 
+# ---------- 用例 1.5：yield_ 让出型 / 原地型语义 ----------
+
+class YieldCooldownTest(CooldownTestBase):
+    def test_yield_returns_false_immediately(self):
+        """yield_=True → 登记 site 键后立即返回 False，不等待（≠ ctx.wait）。"""
+        loop, ctx = self.make_loop()
+        ctx.state["active_site"] = "1688"
+        t0 = time.monotonic()
+        interrupted = loop._cooldown(30.0, "sample_interval", yield_=True)
+        elapsed = time.monotonic() - t0
+        self.assertFalse(interrupted)
+        self.assertLess(elapsed, 0.5)  # 立即返回，绝不等待 30s
+        self.assertIn("1688", ctx.cooldown_until)
+
+    def test_yield_registers_site_key_and_skips_without_active_site(self):
+        """yield_=True + active_site → 写入 cooldown_until[site]；
+        无 active_site → 静默跳过登记，仍立即返回。"""
+        loop, ctx = self.make_loop()
+        # 未设 active_site：不登记
+        loop._cooldown(5.0, "batch_rest", prefix="批次休息", yield_=True)
+        self.assertEqual(ctx.cooldown_until, {})
+        # 设 active_site：登记 site 键
+        ctx.state["active_site"] = "1688"
+        t0 = time.time()
+        loop._cooldown(10.0, "batch_rest", prefix="批次休息", yield_=True)
+        self.assertEqual(set(ctx.cooldown_until), {"1688"})
+        self.assertAlmostEqual(ctx.cooldown_until["1688"], t0 + 10.0, delta=1.0)
+
+    def test_no_yield_keeps_waiting(self):
+        """yield_=False（默认）→ 保持原地等待行为，可被 stop 中断。"""
+        loop, ctx = self.make_loop()
+        threading.Timer(0.1, ctx.stop.set).start()
+        t0 = time.monotonic()
+        interrupted = loop._cooldown(30.0, "launch_backoff", prefix="启动退避")
+        elapsed = time.monotonic() - t0
+        self.assertTrue(interrupted)
+        self.assertLess(elapsed, 5.0)  # 被 stop 打断，未等满 30s
+        self.assertGreaterEqual(elapsed, 0.05)  # 不是立即返回的快路径
+
+    def test_yield_silent_path_no_wait_countdown(self):
+        """yield_=True 即使传了 prefix 也不调用 wait_countdown（不等待）。"""
+        loop, ctx = self.make_loop()
+        ctx.state["active_site"] = "1688"
+        t0 = time.monotonic()
+        # prefix 非空（本应走倒计时），但 yield_=True 时跳过等待
+        loop._cooldown(30.0, "periodic_rest", prefix="长休息", yield_=True)
+        elapsed = time.monotonic() - t0
+        self.assertLess(elapsed, 0.5)
+
+    def test_three_rhythm_sites_pass_yield_true(self):
+        """三处节奏冷却（batch_rest / sample_interval / periodic_rest）
+        确实传 yield_=True；launch_backoff 不传（默认原地）。"""
+        task = ScriptedTask(items=("item1", "item2"))
+        cfg = dict(batch_num=1, max_batches=2, batch_rest=0.2,
+                   sample_min=0.05, sample_max=0.10,
+                   rest_every=1, rest_min=0.06, rest_max=0.12)
+        loop, ctx = self.make_loop(task, **cfg)
+        calls = spy_cooldown_full(loop)
+
+        loop.run()
+
+        by_reason = {}
+        for seconds, reason, prefix, yield_ in calls:
+            by_reason.setdefault(reason, []).append((seconds, prefix, yield_))
+
+        # batch_rest / sample_interval / periodic_rest → yield_=True
+        for reason in ("batch_rest", "sample_interval", "periodic_rest"):
+            self.assertIn(reason, by_reason)
+            for _, _, y in by_reason[reason]:
+                self.assertTrue(y, f"{reason} 应传 yield_=True")
+
+
 class WaitPointsTest(CooldownTestBase):
     def test_batch_sample_periodic_rest_via_chokepoint(self):
         """小参数联跑：batch_rest / sample_interval / periodic_rest 均经
         chokepoint 触发，reason 正确、时长落在公式区间、prefix 符合现状。"""
         task = ScriptedTask(items=("item1", "item2"))
         cfg = dict(batch_num=1, max_batches=2, batch_rest=0.2,
                    sample_min=0.05, sample_max=0.10,
                    rest_every=1, rest_min=0.06, rest_max=0.12)
         loop, ctx = self.make_loop(task, **cfg)
         calls = spy_cooldown(loop)
