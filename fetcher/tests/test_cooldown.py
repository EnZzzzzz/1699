# -*- coding: utf-8 -*-
"""冷却 chokepoint（CrawlLoop._cooldown）loop 侧单测（P1 Step 2.3）。

三组用例：
1. chokepoint 单测：cooldown_until 写入（≈ time.time()+seconds）、
   正常路径返回 False、等待期间 stop 立即返回 True（远小于 seconds）；
   静默（prefix=None → ctx.wait）与倒计时（prefix 传 → wait_countdown）
   两条展示路径各覆盖一次。
2. _process_item 策略冷却集成：CrawlLoop 联跑——假 task 首次 fetch
   自报 blocked、假策略输出 StepResult(cooldown=t)，断言冷却经
   chokepoint 执行（spy 记录参数、调用真实实现）、随后重试成功；
   再覆盖「冷却中被 stop 中断 → return "stop" 终局」分支。
3. 4 处等待点（batch_rest / sample_interval / periodic_rest /
   launch_backoff）均经 chokepoint 触发，reason 正确且时长落在公式区间。

真实 threading.Event + 临时 sqlite + spy（不 mock 被测的 _cooldown
本身）；假基建模式参照 test_control_loop.py / test_queue_router.py。
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from fetcher import (
    Alibaba1688Plugin,
    IdentityStore,
    RunConfig,
    Scenario,
    Session,
    ShopDB,
    WorkerContext,
)
from fetcher.control import CrawlLoop, Task
from fetcher.core.types import ActionResult, Outcome
from fetcher.strategy.base import StepResult
from fetcher.strategy.policy import Policy


# ---------- mock 基础设施（模式同 test_control_loop.py） ----------

class FakeBrowser:
    def is_connected(self):
        return True

    def close(self):
        pass


class FakeContext:
    def __init__(self):
        self.browser = FakeBrowser()

    def cookies(self):
        return []


class FakePage:
    def __init__(self):
        self.url = "https://shop123.1688.com/page/contactinfo.htm"
        self._text = "正常页面文本，足够长，包含电话、手机、地址等字段标签，超过阈值。"
        self.frames = []
        self.context = FakeContext()

    def evaluate(self, js):
        return self._text

    def query_selector(self, sel):
        return None

    def is_closed(self):
        return False


class MockBrowserManager:
    """launch 返回带假 page 的 Session；fail_launch=True 时恒抛错。"""

    def __init__(self, page, fail_launch=False):
        self.page = page
        self.fail_launch = fail_launch
        self.launch_count = 0

    def launch(self, seed_kit=None, stop=None):
        self.launch_count += 1
        if self.fail_launch:
            raise RuntimeError("launch boom")
        return Session(browser=FakeBrowser(), page=self.page,
                       identity="1688:1.1.1.1", seed_kit=seed_kit)

    def check_ip_fresh(self, session):
        return False, session.identity, ""

    def save_cookies(self, session):
        return 0


class ScriptedTask(Task):
    """可编程任务：fetch 按 script 逐条出账（只用到 ok / blocked）。

    rest_counter 以 stats["done"] 为基准（供 periodic_rest 触发）。
    """

    name = "scripted"

    def __init__(self, script=(), items=("item1",)):
        self.script = list(script)
        self.items = list(items)
        self.fetches = 0
        self.succeeded = []
        self.given_up = []

    def acquire_item(self, ctx):
        return self.items.pop(0) if self.items else None

    def fetch(self, ctx, item):
        self.fetches += 1
        step = self.script.pop(0) if self.script else ("ok", {"v": 1})
        if step[0] == "ok":
            return ActionResult(Outcome.OK, "", step[1])
        if step[0] == "blocked":
            return ActionResult.blocked(step[1])
        raise ValueError(step[0])

    def on_success(self, ctx, item, result):
        self.succeeded.append(item)
        stats = ctx.state["task"]["stats"]
        stats["done"] = stats.get("done", 0) + 1
        return 1

    def on_giveup(self, ctx, item, reason, kind):
        self.given_up.append((item, kind))
        return "标记跳过"

    def make_stats(self):
        return {"done": 0}

    def rest_counter(self, stats):
        return stats.get("done", 0)


class CooldownStrategy:
    """假策略：只输出 cooldown（Step 2.1 起策略不自等）。"""

    def __init__(self, cooldown, solved=False):
        self.cooldown = cooldown
        self.solved = solved
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return StepResult(self.solved, f"cool#{self.calls}",
                          cooldown=self.cooldown)


def make_config(tmp, **kw):
    base = dict(headless=True, use_proxy=False, batch_num=1, max_batches=1,
                sample_min=0, sample_max=0, rest_every=0, batch_rest=0.01,
                block_rest_min=0.01, block_rest_max=0.02, ip_retry=1,
                max_consecutive_fail=3,
                db_path=str(Path(tmp) / "t.db"))
    base.update(kw)
    return RunConfig(**base)


def make_ctx(config, mgr, stop=None):
    store = IdentityStore(ShopDB(config.resolved_db_path()))
    return WorkerContext(config=config, store=store, browser_manager=mgr,
                         site=Alibaba1688Plugin(),
                         stop=stop or threading.Event(),
                         log=lambda m: None)


def spy_cooldown(loop):
    """spy _cooldown：记录 (seconds, reason, prefix)，调用真实实现。"""
    calls = []
    orig = loop._cooldown

    def spy(seconds, reason, prefix=None, **kwargs):
        calls.append((seconds, reason, prefix))
        return orig(seconds, reason, prefix, **kwargs)

    loop._cooldown = spy
    return calls


def spy_cooldown_full(loop):
    """spy _cooldown：记录完整参数 (seconds, reason, prefix, yield_)，
    调用真实实现。"""
    calls = []
    orig = loop._cooldown

    def spy(seconds, reason, prefix=None, yield_=False, **kwargs):
        calls.append((seconds, reason, prefix, yield_))
        return orig(seconds, reason, prefix, yield_=yield_, **kwargs)

    loop._cooldown = spy
    return calls


class CooldownTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.page = FakePage()
        self.mgr = MockBrowserManager(self.page)

    def tearDown(self):
        self._tmp.cleanup()

    def make_loop(self, task=None, table=None, strategies=None, **cfg_kw):
        config = make_config(self.tmp, **cfg_kw)
        ctx = make_ctx(config, self.mgr)
        policy = Policy(table=table or {}, strategies=strategies or {},
                        max_consecutive_fail=config.max_consecutive_fail)
        loop = CrawlLoop(ctx, task or ScriptedTask(), policy=policy)
        return loop, ctx


# ---------- 用例 1：chokepoint 单测 ----------

class CooldownChokepointTest(CooldownTestBase):
    def test_silent_path_writes_deadline_and_returns_false(self):
        """静默路径（prefix=None → ctx.wait）：无 active_site 时不登记冷却。
        P3 键语义：cooldown_until 按 site 注册名登记，只有 active_site 设置
        时才写入；本测试路径无 active_site，cooldown_until 保持空。"""
        loop, ctx = self.make_loop()
        interrupted = loop._cooldown(0.05, "ut_silent")
        self.assertFalse(interrupted)
        self.assertEqual(ctx.cooldown_until, {})

    def test_countdown_path_stop_interrupt_returns_true_fast(self):
        """倒计时路径（prefix 传 → wait_countdown）：等待期间置 stop
        立即返回 True（远小于 seconds）。无 active_site 时不登记冷却。"""
        loop, ctx = self.make_loop()
        threading.Timer(0.1, ctx.stop.set).start()
        t0 = time.monotonic()
        interrupted = loop._cooldown(30.0, "ut_countdown", prefix="倒计时")
        elapsed = time.monotonic() - t0
        self.assertTrue(interrupted)
        self.assertLess(elapsed, 5.0)  # 远小于 30s：确实被 stop 打断
        self.assertGreaterEqual(elapsed, 0.05)  # 非「立即返回」的快路径
        self.assertEqual(ctx.cooldown_until, {})

    def test_site_key_when_active_site_set(self):
        """设 active_site="1688" → 登记 cooldown_until["1688"] 而非 reason。"""
        loop, ctx = self.make_loop()
        ctx.state["active_site"] = "1688"
        t0 = time.time()
        loop._cooldown(10.0, "sample_interval")
        self.assertNotIn("sample_interval", ctx.cooldown_until)
        self.assertEqual(set(ctx.cooldown_until), {"1688"})
        self.assertAlmostEqual(ctx.cooldown_until["1688"], t0 + 10.0, delta=1.0)

    def test_no_registration_without_active_site(self):
        """未设 active_site → _cooldown 不登记任何键（仍执行等待）。"""
        loop, ctx = self.make_loop()
        loop._cooldown(0.1, "any_reason")
        self.assertEqual(ctx.cooldown_until, {})


# ---------- 用例 2：_process_item 策略冷却集成 ----------

class StrategyCooldownIntegrationTest(CooldownTestBase):
    TABLE = {Scenario.RISK_SLIDER_PAGE: [("cool", 1), ("give_up", None)]}

    def test_strategy_cooldown_via_chokepoint_then_retry_success(self):
        """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → P3 策略冷却
        统一让出 + release（yield_=True）：登记冷却后立即返回，item 释放
        回 pending 然后循环退出（单 item 无更多任务）。"""
        strategy = CooldownStrategy(cooldown=0.3, solved=True)
        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1})])
        loop, ctx = self.make_loop(task, self.TABLE, {"cool": strategy})
        calls = spy_cooldown_full(loop)

        t0 = time.monotonic()
        loop.run()
        elapsed = time.monotonic() - t0

        # P3：策略冷却 → release（不再 wait + retry）
        self.assertEqual(task.fetches, 1)
        self.assertEqual(task.succeeded, [])
        self.assertEqual(task.given_up, [])
        # 冷却经 chokepoint：spy 记录 reason=f"strategy:cool"、秒数原样透传
        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
        self.assertEqual(len(strat_calls), 1)
        seconds, _reason, prefix, yield_ = strat_calls[0]
        self.assertAlmostEqual(seconds, 0.3, delta=1e-6)
        self.assertIsNone(prefix)  # 策略冷却走静默路径
        self.assertTrue(yield_, "P3 策略冷却已改为 yield_=True（让出型）")
        # 让出型不等待（立即返回）
        self.assertLess(elapsed, 0.2)
        # 无 active_site，cooldown_until 保持空（P3 site 键语义）
        self.assertEqual(ctx.cooldown_until, {})

    def test_strategy_cooldown_interrupted_by_stop_is_stop_terminal(self):
        """P3 策略冷却让出 + release：stop 由下一轮 acquire 处理。
        设 active_site 后 cooldown 登记冷却，stop 置位后 while 循环退出。
        当前 item 不放弃、后续 item 不再认领，loop 快速退出。"""
        strategy = CooldownStrategy(cooldown=30.0)
        # 在 fetch 中设 stop：第一次 fetch 后 stop 置位，
        # release+continue 后 while 循环立即捕获
        class StopAfterFetch(ScriptedTask):
            def fetch(self, ctx, item):
                result = super().fetch(ctx, item)
                ctx.stop.set()
                return result
        task = StopAfterFetch([("blocked", "滑块拦截"), ("ok", {"v": 1}),
                               ("ok", {"v": 2})], items=("item1", "item2"))
        stop = threading.Event()
        config = make_config(self.tmp)
        ctx = make_ctx(config, self.mgr, stop=stop)
        ctx.state["active_site"] = "1688"
        policy = Policy(table=self.TABLE, strategies={"cool": strategy},
                        max_consecutive_fail=config.max_consecutive_fail)
        loop = CrawlLoop(ctx, task, policy=policy)
        calls = spy_cooldown_full(loop)

        t0 = time.monotonic()
        loop.run()
        elapsed = time.monotonic() - t0

        # stop 快速捕获（不等待 30s）
        self.assertLess(elapsed, 0.3)
        self.assertTrue(stop.is_set())
        # "stop" 终局：item1 未成功也未放弃，item2 未被认领（fetch 只 1 次）
        self.assertEqual(task.fetches, 1)
        self.assertEqual(task.succeeded, [])
        self.assertEqual(task.given_up, [])
        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
        self.assertEqual(len(strat_calls), 1)
        self.assertAlmostEqual(strat_calls[0][0], 30.0, delta=1e-6)
        self.assertTrue(strat_calls[0][3], "P3 策略冷却已改为 yield_=True（让出型）")


# ---------- 用例 3：4 处等待点触发 ----------

# ---------- 用例 1.5：yield_ 让出型 / 原地型语义 ----------

class YieldCooldownTest(CooldownTestBase):
    def test_yield_returns_false_immediately(self):
        """yield_=True → 登记 site 键后立即返回 False，不等待（≠ ctx.wait）。"""
        loop, ctx = self.make_loop()
        ctx.state["active_site"] = "1688"
        t0 = time.monotonic()
        interrupted = loop._cooldown(30.0, "sample_interval", yield_=True)
        elapsed = time.monotonic() - t0
        self.assertFalse(interrupted)
        self.assertLess(elapsed, 0.5)  # 立即返回，绝不等待 30s
        self.assertIn("1688", ctx.cooldown_until)

    def test_yield_registers_site_key_and_skips_without_active_site(self):
        """yield_=True + active_site → 写入 cooldown_until[site]；
        无 active_site → 静默跳过登记，仍立即返回。"""
        loop, ctx = self.make_loop()
        # 未设 active_site：不登记
        loop._cooldown(5.0, "batch_rest", prefix="批次休息", yield_=True)
        self.assertEqual(ctx.cooldown_until, {})
        # 设 active_site：登记 site 键
        ctx.state["active_site"] = "1688"
        t0 = time.time()
        loop._cooldown(10.0, "batch_rest", prefix="批次休息", yield_=True)
        self.assertEqual(set(ctx.cooldown_until), {"1688"})
        self.assertAlmostEqual(ctx.cooldown_until["1688"], t0 + 10.0, delta=1.0)

    def test_no_yield_keeps_waiting(self):
        """yield_=False（默认）→ 保持原地等待行为，可被 stop 中断。"""
        loop, ctx = self.make_loop()
        threading.Timer(0.1, ctx.stop.set).start()
        t0 = time.monotonic()
        interrupted = loop._cooldown(30.0, "launch_backoff", prefix="启动退避")
        elapsed = time.monotonic() - t0
        self.assertTrue(interrupted)
        self.assertLess(elapsed, 5.0)  # 被 stop 打断，未等满 30s
        self.assertGreaterEqual(elapsed, 0.05)  # 不是立即返回的快路径

    def test_yield_silent_path_no_wait_countdown(self):
        """yield_=True 即使传了 prefix 也不调用 wait_countdown（不等待）。"""
        loop, ctx = self.make_loop()
        ctx.state["active_site"] = "1688"
        t0 = time.monotonic()
        # prefix 非空（本应走倒计时），但 yield_=True 时跳过等待
        loop._cooldown(30.0, "periodic_rest", prefix="长休息", yield_=True)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5)

    def test_three_rhythm_sites_pass_yield_true(self):
        """三处节奏冷却（batch_rest / sample_interval / periodic_rest）
        确实传 yield_=True；launch_backoff 不传（默认原地）。"""
        task = ScriptedTask(items=("item1", "item2"))
        cfg = dict(batch_num=1, max_batches=2, batch_rest=0.2,
                   sample_min=0.05, sample_max=0.10,
                   rest_every=1, rest_min=0.06, rest_max=0.12)
        loop, ctx = self.make_loop(task, **cfg)
        calls = spy_cooldown_full(loop)

        loop.run()

        by_reason = {}
        for seconds, reason, prefix, yield_ in calls:
            by_reason.setdefault(reason, []).append((seconds, prefix, yield_))

        # batch_rest / sample_interval / periodic_rest → yield_=True
        for reason in ("batch_rest", "sample_interval", "periodic_rest"):
            self.assertIn(reason, by_reason)
            for _, _, y in by_reason[reason]:
                self.assertTrue(y, f"{reason} 应传 yield_=True")

        # launch_backoff 不应触发（mock 启动成功），若触发了必须为 yield_=False
        if "launch_backoff" in by_reason:
            for _, _, y in by_reason["launch_backoff"]:
                self.assertFalse(y, "launch_backoff 应保持 yield_=False（原地型）")
        # 策略冷却不应触发（纯成功路径），若触发了必须为 yield_=False
        strat_reasons = [r for r in by_reason if r.startswith("strategy:")]
        for r in strat_reasons:
            for _, _, y in by_reason[r]:
                self.assertFalse(y, f"{r} 应保持 yield_=False（原地型）")


# ---------- 用例 4：让出型 × QueueRouter 集成验证（F1） ----------

class YieldIntegrationWithProxyTest(unittest.TestCase):
    """F1 集成测试：QueueRouter + CrawlLoop 跑 2 个成功 item，
    验证让出型冷却登记 site 键 + condvar 等待发生在 acquire 而非 loop 内。

    假基建模式（FakePage / MockBrowserManager / fake fetch OK），
    不依赖真实浏览器或网络。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.page = FakePage()
        self.mgr = MockBrowserManager(self.page)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_proxy_ctx(self, sample_min, sample_max, items=2):
        """创建 QueueRouter + WorkerContext，seed 好 work_items。"""
        import json as _json
        from fetcher.control.queue_router import QueueRouter, QueueSpec

        config = make_config(self.tmp,
                             sample_min=sample_min, sample_max=sample_max,
                             batch_rest=0.01, batch_num=2, max_batches=1,
                             rest_every=0,  # 关闭长休息，简化验证
                             limit=0)
        ctx = make_ctx(config, self.mgr)

        # Seed work_items
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        db = ctx.store.db
        for i in range(1, items + 1):
            domain = f"shop{i}.1688.com"
            payload = {"domain": domain, "name": f"店{i}",
                       "url": f"https://{domain}/page/contactinfo.htm"}
            db.conn.execute(
                "INSERT INTO work_items (queue, site, payload_json,"
                " status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("crawl_1688_contact", "1688",
                 _json.dumps(payload), "pending", now))
            db.conn.commit()

        inner = ScriptedTask([("ok", {"v": i}) for i in range(1, items + 1)])
        registry = [QueueSpec(
            queue="crawl_1688_contact", site="1688", task=inner,
            topup=lambda db, limit: db.topup_contact_work_items(
                "crawl_1688_contact", "1688", ".1688.com", limit),
            domain_suffix=".1688.com")]
        router = QueueRouter(registry)
        return router, ctx

    def test_yield_cooldown_waits_in_acquire_not_loop(self):
        """2 个成功 item：item1 完成后让出型 sample_interval 登记 site 键，
        item2 的认领发生在冷却到期之后（时间戳间隔落在 sample 区间），
        且循环体内无 ctx.wait 调用（让出型不触发 loop 内等待）。"""
        proxy, ctx = self._make_proxy_ctx(sample_min=0.3, sample_max=0.5)
        policy = Policy(table={}, strategies={},
                        max_consecutive_fail=3)
        loop = CrawlLoop(ctx, proxy, policy=policy)

        # Spy ctx.wait / ctx.stop.wait（让出型不应触发）
        wait_calls = []
        orig_wait = ctx.wait

        def spy_wait(seconds):
            wait_calls.append(seconds)
            return orig_wait(seconds)

        ctx.wait = spy_wait

        # Spy _cooldown 记录让出型参数
        cooldown_spy = []
        orig_cooldown = loop._cooldown

        def spy_cd(seconds, reason, prefix=None, yield_=False):
            cooldown_spy.append((seconds, reason, prefix, yield_))
            return orig_cooldown(seconds, reason, prefix, yield_=yield_)

        loop._cooldown = spy_cd

        t0 = time.monotonic()
        stats = loop.run()
        elapsed = time.monotonic() - t0

        # 两个 item 都成功
        inner = proxy._registry["crawl_1688_contact"].task
        self.assertEqual(len(inner.succeeded), 2,
                         f"期望两个 item 成功，got {len(inner.succeeded)}")
        # succeeded 记录的是 work_item dict（含 domain/name/url）
        self.assertEqual(inner.succeeded[0]["domain"], "shop1.1688.com")
        self.assertEqual(inner.succeeded[1]["domain"], "shop2.1688.com")
        # stats.done 反映成功计数
        self.assertEqual(stats.get("done", 0), 2,
                         f"stats.done 应为 2，got {stats.get('done', 0)}")

        # 让出型调用：sample_interval（2 次，每个 item 一次）
        si_calls = [c for c in cooldown_spy if c[1] == "sample_interval"]
        self.assertGreaterEqual(len(si_calls), 2,
                                f"sample_interval 应至少 2 次，got {len(si_calls)}")
        for _seconds, _reason, _prefix, y in si_calls:
            self.assertTrue(y, "sample_interval 应传 yield_=True")
            self.assertGreaterEqual(_seconds, 0.3)
            self.assertLessEqual(_seconds, 0.5)

        # batch_rest 让出型
        br_calls = [c for c in cooldown_spy if c[1] == "batch_rest"]
        for _, _, _, y in br_calls:
            self.assertTrue(y, "batch_rest 应传 yield_=True")

        # site 键登记：active_site="1688" 应写入 cooldown_until
        self.assertIn("1688", ctx.cooldown_until,
                      "active_site='1688' 应在 sample_interval 时写入 cooldown_until")

        # 循环体内无 ctx.wait 调用（让出型冷却不触发 wait）
        si_values = {s for s, _, _, _ in si_calls}
        for w in wait_calls:
            self.assertNotIn(w, si_values,
                             f"ctx.wait({w}) 不应被让出型冷却触发")

        # 时间间隔：第 1 次 sample_interval 后会触发 condvar 等待，
        # 第 2 次 sample_interval 后直接 batch 收工（不再 acquire），
        # 故只有 1 次 condvar 等待计入总耗时
        self.assertGreaterEqual(elapsed, 0.25,
                                f"总耗时 {elapsed:.2f}s 应反映 condvar 等待"
                                f"（≥ 0.25s）")

        # 验证 DB 中的 work_items 已被标记为 done（loop 会关 DB，另开连接查）
        import sqlite3
        db_path = str(Path(self.tmp) / "t.db")
        conn = sqlite3.connect(db_path)
        done_count = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE status='done'").fetchone()[0]
        conn.close()
        self.assertEqual(done_count, 2,
                         f"2 个 work_items 应为 done，got {done_count}")


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

        stats = loop.run()

        self.assertEqual(task.succeeded, ["item1", "item2"])
        self.assertEqual(stats["done"], 2)

        by_reason = {}
        for seconds, reason, prefix in calls:
            by_reason.setdefault(reason, []).append((seconds, prefix))

        # 三处等待点全部经 chokepoint
        self.assertIn("batch_rest", by_reason)
        self.assertIn("sample_interval", by_reason)
        self.assertIn("periodic_rest", by_reason)

        # batch_rest：±10% 抖动区间，倒计时路径（prefix="批次休息"）
        self.assertEqual(len(by_reason["batch_rest"]), 1)  # max_batches=2 → 1 次
        seconds, prefix = by_reason["batch_rest"][0]
        self.assertGreaterEqual(seconds, 0.2 * 0.9)
        self.assertLessEqual(seconds, 0.2 * 1.1)
        self.assertEqual(prefix, "批次休息")

        # sample_interval：wid=0 → [sample_min, sample_max]，静默路径
        self.assertEqual(len(by_reason["sample_interval"]), 2)  # 每个 item 一次
        for seconds, prefix in by_reason["sample_interval"]:
            self.assertGreaterEqual(seconds, 0.05)
            self.assertLessEqual(seconds, 0.10)
            self.assertIsNone(prefix)

        # periodic_rest：rest_every=1 → 每个 item 一次，[rest_min, rest_max]
        self.assertEqual(len(by_reason["periodic_rest"]), 2)
        for seconds, prefix in by_reason["periodic_rest"]:
            self.assertGreaterEqual(seconds, 0.06)
            self.assertLessEqual(seconds, 0.12)
            self.assertEqual(prefix, "长休息")

        # 无 active_site → cooldown_until 保持空（P3 site 键语义）
        self.assertEqual(ctx.cooldown_until, {})
        # reason 仍传对（spy 证据）
        self.assertEqual(set(by_reason), {"batch_rest", "sample_interval",
                                           "periodic_rest"})
        for reason in ("batch_rest", "sample_interval", "periodic_rest"):
            self.assertIn(reason, by_reason)

    def test_launch_backoff_via_chokepoint(self):
        """启动退避：首次 launch 失败 → _cooldown(backoff, "launch_backoff",
        prefix="启动退避")，backoff=min(30*attempt,120)=30s；stop 中断后
        按 UserInterrupted 路径快速退出（不等满 30s）。
        同时验证 launch_backoff 保持 yield_=False（原地型）。"""
        self.mgr = MockBrowserManager(self.page, fail_launch=True)
        stop = threading.Event()
        config = make_config(self.tmp, ip_retry=2)
        ctx = make_ctx(config, self.mgr, stop=stop)
        policy = Policy(table={}, strategies={},
                        max_consecutive_fail=config.max_consecutive_fail)
        loop = CrawlLoop(ctx, ScriptedTask(), policy=policy)
        calls = spy_cooldown_full(loop)

        threading.Timer(0.15, stop.set).start()
        t0 = time.monotonic()
        loop.run()
        elapsed = time.monotonic() - t0

        self.assertEqual(self.mgr.launch_count, 1)  # 第 1 次失败即进退避
        bo_calls = [c for c in calls if c[1] == "launch_backoff"]
        self.assertEqual(len(bo_calls), 1)
        seconds, _reason, prefix, yield_ = bo_calls[0]
        self.assertAlmostEqual(seconds, 30.0, delta=1e-6)  # min(30*1, 120)
        self.assertEqual(prefix, "启动退避")
        self.assertFalse(yield_, "launch_backoff 应保持 yield_=False（原地型）")
        # 被 stop 中断（UserInterrupted），未等满 30s、未二次 launch
        self.assertLess(elapsed, 5.0)
        # 无 active_site（launch_backoff 在 acquire 前）→ 不登记
        self.assertEqual(ctx.cooldown_until, {})


if __name__ == "__main__":
    unittest.main()
