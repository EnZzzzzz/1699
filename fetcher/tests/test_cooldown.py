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
本身）；假基建模式参照 test_control_loop.py / test_daemon_task.py。
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
                       identity="1.1.1.1", seed_kit=seed_kit)

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

    def spy(seconds, reason, prefix=None):
        calls.append((seconds, reason, prefix))
        return orig(seconds, reason, prefix)

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
        """静默路径（prefix=None → ctx.wait）：写入 cooldown_until[reason]
        ≈ time.time()+seconds，正常等完返回 False。"""
        loop, ctx = self.make_loop()
        t0 = time.time()
        interrupted = loop._cooldown(0.05, "ut_silent")
        self.assertFalse(interrupted)
        # 唯一写入者语义：只写了这一个 reason，值 ≈ 调用时刻 + seconds
        self.assertEqual(set(ctx.cooldown_until), {"ut_silent"})
        self.assertAlmostEqual(ctx.cooldown_until["ut_silent"], t0 + 0.05,
                               delta=1.0)

    def test_countdown_path_stop_interrupt_returns_true_fast(self):
        """倒计时路径（prefix 传 → wait_countdown）：等待期间置 stop
        立即返回 True（远小于 seconds），cooldown_until 同样登记。"""
        loop, ctx = self.make_loop()
        threading.Timer(0.1, ctx.stop.set).start()
        t0 = time.monotonic()
        interrupted = loop._cooldown(30.0, "ut_countdown", prefix="倒计时")
        elapsed = time.monotonic() - t0
        self.assertTrue(interrupted)
        self.assertLess(elapsed, 5.0)  # 远小于 30s：确实被 stop 打断
        self.assertGreaterEqual(elapsed, 0.05)  # 非「立即返回」的快路径
        self.assertAlmostEqual(ctx.cooldown_until["ut_countdown"],
                               time.time() + 30.0, delta=1.0)


# ---------- 用例 2：_process_item 策略冷却集成 ----------

class StrategyCooldownIntegrationTest(CooldownTestBase):
    TABLE = {Scenario.RISK_SLIDER_PAGE: [("cool", 1), ("give_up", None)]}

    def test_strategy_cooldown_via_chokepoint_then_retry_success(self):
        """首次 fetch 自报 blocked → 策略输出 cooldown=0.3 → loop 经
        chokepoint 真实等待后重试 fetch → 成功收尾。"""
        strategy = CooldownStrategy(cooldown=0.3, solved=True)
        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1})])
        loop, ctx = self.make_loop(task, self.TABLE, {"cool": strategy})
        calls = spy_cooldown(loop)

        t0 = time.monotonic()
        loop.run()
        elapsed = time.monotonic() - t0

        # 重试发生且终态正确
        self.assertEqual(task.fetches, 2)
        self.assertEqual(task.succeeded, ["item1"])
        self.assertEqual(task.given_up, [])
        # 冷却经 chokepoint：spy 记录 reason=f"strategy:cool"、秒数原样透传
        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
        self.assertEqual(len(strat_calls), 1)
        seconds, _reason, prefix = strat_calls[0]
        self.assertAlmostEqual(seconds, 0.3, delta=1e-6)
        self.assertIsNone(prefix)  # 策略冷却走静默路径
        # 真实等待过（spy 调的是真实实现）
        self.assertGreaterEqual(elapsed, 0.25)
        # cooldown_until 已登记，值 ≈ 写入时刻 + seconds
        # （run 结束可能已过截止点，用宽容差而非「在未来」断言）
        self.assertAlmostEqual(ctx.cooldown_until["strategy:cool"],
                               time.time() + 0.3, delta=1.0)

    def test_strategy_cooldown_interrupted_by_stop_is_stop_terminal(self):
        """冷却中被 stop 中断 → _process_item return "stop" 终局：
        当前 item 不放弃、后续 item 不再认领，loop 快速退出。"""
        strategy = CooldownStrategy(cooldown=30.0)
        task = ScriptedTask([("blocked", "滑块拦截"), ("ok", {"v": 1}),
                             ("ok", {"v": 2})], items=("item1", "item2"))
        stop = threading.Event()
        config = make_config(self.tmp)
        ctx = make_ctx(config, self.mgr, stop=stop)
        policy = Policy(table=self.TABLE, strategies={"cool": strategy},
                        max_consecutive_fail=config.max_consecutive_fail)
        loop = CrawlLoop(ctx, task, policy=policy)
        calls = spy_cooldown(loop)

        threading.Timer(0.15, stop.set).start()
        t0 = time.monotonic()
        loop.run()
        elapsed = time.monotonic() - t0

        # 被 stop 打断而非等满 30s
        self.assertLess(elapsed, 5.0)
        self.assertTrue(stop.is_set())
        # "stop" 终局：item1 未成功也未放弃，item2 未被认领（fetch 只 1 次）
        self.assertEqual(task.fetches, 1)
        self.assertEqual(task.succeeded, [])
        self.assertEqual(task.given_up, [])
        strat_calls = [c for c in calls if c[1] == "strategy:cool"]
        self.assertEqual(len(strat_calls), 1)
        self.assertAlmostEqual(strat_calls[0][0], 30.0, delta=1e-6)


# ---------- 用例 3：4 处等待点触发 ----------

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

        # cooldown_until 三类 reason 均登记（唯一写入者语义）
        for reason in ("batch_rest", "sample_interval", "periodic_rest"):
            self.assertIn(reason, ctx.cooldown_until)

    def test_launch_backoff_via_chokepoint(self):
        """启动退避：首次 launch 失败 → _cooldown(backoff, "launch_backoff",
        prefix="启动退避")，backoff=min(30*attempt,120)=30s；stop 中断后
        按 UserInterrupted 路径快速退出（不等满 30s）。"""
        self.mgr = MockBrowserManager(self.page, fail_launch=True)
        stop = threading.Event()
        config = make_config(self.tmp, ip_retry=2)
        ctx = make_ctx(config, self.mgr, stop=stop)
        policy = Policy(table={}, strategies={},
                        max_consecutive_fail=config.max_consecutive_fail)
        loop = CrawlLoop(ctx, ScriptedTask(), policy=policy)
        calls = spy_cooldown(loop)

        threading.Timer(0.15, stop.set).start()
        t0 = time.monotonic()
        loop.run()
        elapsed = time.monotonic() - t0

        self.assertEqual(self.mgr.launch_count, 1)  # 第 1 次失败即进退避
        bo_calls = [c for c in calls if c[1] == "launch_backoff"]
        self.assertEqual(len(bo_calls), 1)
        seconds, _reason, prefix = bo_calls[0]
        self.assertAlmostEqual(seconds, 30.0, delta=1e-6)  # min(30*1, 120)
        self.assertEqual(prefix, "启动退避")
        # 被 stop 中断（UserInterrupted），未等满 30s、未二次 launch
        self.assertLess(elapsed, 5.0)
        self.assertIn("launch_backoff", ctx.cooldown_until)


if __name__ == "__main__":
    unittest.main()
