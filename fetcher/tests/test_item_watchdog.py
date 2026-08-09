# -*- coding: utf-8 -*-
"""工作项执行超时看门狗测试。

背景：worker 卡在单个 item（滑块自愈链/浏览器无响应）超过阈值时，
看门狗置 abort_item 中止信号 + 释放工作项回 pending；loop 感知中止后
跳过簿记、重建浏览器会话、取新任务（scheduler §5 租约回收的落地）。
"""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from fetcher import RunConfig, ShopDB, WorkerContext
from fetcher.control.engine import watchdog_tick
from fetcher.control.queue_router import QueueRouter
from fetcher.core.types import ActionResult, Outcome

import test_control_loop as tcl


# ---------- ctx.wait 对 abort_item 的中断语义 ----------

class TestWaitAbortItem(unittest.TestCase):
    def make_ctx(self):
        return WorkerContext(config=RunConfig(), log=lambda m: None)

    def test_abort_item_interrupts_wait(self):
        ctx = self.make_ctx()
        ctx.abort_item.set()
        t0 = time.monotonic()
        self.assertTrue(ctx.wait(10.0))
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_wait_full_duration_returns_false(self):
        ctx = self.make_ctx()
        t0 = time.monotonic()
        self.assertFalse(ctx.wait(0.2))
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_stop_still_interrupts_wait(self):
        """回归：原有 stop 中断语义不变。"""
        ctx = self.make_ctx()
        ctx.stop.set()
        self.assertTrue(ctx.wait(10.0))


# ---------- watchdog_tick（纯函数：扫描 worker ctx 列表） ----------

class _FakeTask:
    def __init__(self, raise_on_release=False):
        self.released = []
        self._raise = raise_on_release

    def timeout_release(self, ctx):
        if self._raise:
            raise RuntimeError("db locked")
        self.released.append(ctx)


class TestWatchdogTick(unittest.TestCase):
    def make_ctx(self, started_at=None):
        ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
        if started_at is not None:
            ctx.state["item_started_at"] = started_at
        return ctx

    def test_fresh_item_not_aborted(self):
        now = time.time()
        ctx = self.make_ctx(now - 10)
        task = _FakeTask()
        n = watchdog_tick([ctx], task, now, timeout=1800.0)
        self.assertEqual(n, 0)
        self.assertFalse(ctx.abort_item.is_set())
        self.assertEqual(task.released, [])

    def test_stale_item_aborted_and_released(self):
        now = time.time()
        ctx = self.make_ctx(now - 2000)
        task = _FakeTask()
        n = watchdog_tick([ctx], task, now, timeout=1800.0)
        self.assertEqual(n, 1)
        self.assertTrue(ctx.abort_item.is_set())
        self.assertEqual(task.released, [ctx])

    def test_already_aborting_skipped(self):
        """同一 item 不重复释放（abort 已置位说明上一轮已处理）。"""
        now = time.time()
        ctx = self.make_ctx(now - 2000)
        ctx.abort_item.set()
        task = _FakeTask()
        n = watchdog_tick([ctx], task, now, timeout=1800.0)
        self.assertEqual(n, 0)
        self.assertEqual(task.released, [])

    def test_idle_worker_skipped(self):
        now = time.time()
        ctx = self.make_ctx()  # 无 item_started_at
        task = _FakeTask()
        n = watchdog_tick([ctx], task, now, timeout=1800.0)
        self.assertEqual(n, 0)
        self.assertFalse(ctx.abort_item.is_set())

    def test_release_failure_swallowed(self):
        """释放失败（如 DB 锁）不炸看门狗线程，abort 信号仍已发出。"""
        now = time.time()
        ctx = self.make_ctx(now - 2000)
        task = _FakeTask(raise_on_release=True)
        n = watchdog_tick([ctx], task, now, timeout=1800.0)
        self.assertEqual(n, 1)
        self.assertTrue(ctx.abort_item.is_set())

    def test_task_without_timeout_release_still_aborts(self):
        """CLI 单任务（无 QueueRouter）只置中止信号，不做 DB 释放。"""
        now = time.time()
        ctx = self.make_ctx(now - 2000)

        class NoRelease:
            pass

        n = watchdog_tick([ctx], NoRelease(), now, timeout=1800.0)
        self.assertEqual(n, 1)
        self.assertTrue(ctx.abort_item.is_set())


# ---------- QueueRouter.timeout_release（真实 sqlite） ----------

class _FakeStatusStore:
    def __init__(self):
        self.upserts = []

    def upsert(self, consumer_id, kind, **kw):
        self.upserts.append((consumer_id, kind, kw))


class TestTimeoutRelease(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "t.db"
        self.db = ShopDB(self.db_path)
        self.store = _FakeStatusStore()
        self.router = QueueRouter(
            [], db_factory=lambda: ShopDB(self.db_path),
            status_store=self.store)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _insert_claimed(self):
        cur = self.db.conn.execute(
            "INSERT INTO work_items (queue, site, batch_id, payload_json,"
            " status, claimed_by, claimed_at, created_at)"
            " VALUES ('crawl_x', 'x', 1, '{}', 'claimed', 'w0',"
            " '2026-08-09 00:00:00', '2026-08-09 00:00:00')")
        self.db.conn.commit()
        return cur.lastrowid

    def make_ctx(self, item_id=None):
        ctx = WorkerContext(config=RunConfig(db_path=self.db_path),
                            log=lambda m: None, wid=0)
        if item_id is not None:
            ctx.state["daemon_work_item_id"] = item_id
        return ctx

    def test_release_claimed_item(self):
        item_id = self._insert_claimed()
        ctx = self.make_ctx(item_id)
        status = self.router.timeout_release(ctx)
        self.assertEqual(status, "pending")
        self.assertNotIn("daemon_work_item_id", ctx.state)
        row = self.db.conn.execute(
            "SELECT status, attempts FROM work_items WHERE id=?",
            (item_id,)).fetchone()
        self.assertEqual((row[0], row[1]), ("pending", 1))

    def test_status_store_current_cleared(self):
        item_id = self._insert_claimed()
        ctx = self.make_ctx(item_id)
        self.router.timeout_release(ctx)
        self.assertTrue(self.store.upserts)
        _, _, kw = self.store.upserts[-1]
        self.assertIsNone(kw.get("queue"))
        self.assertIsNone(kw.get("item_id"))

    def test_no_claimed_item_noop(self):
        ctx = self.make_ctx()
        self.assertEqual(self.router.timeout_release(ctx), "")
        self.assertEqual(self.store.upserts, [])


# ---------- CrawlLoop 中止处理（fetch 中超时 → 跳簿记重建会话取新任务） ----------

class AbortDuringFetchTask(tcl.Task):
    """首个 item 的 fetch 模拟看门狗中止信号（执行中被置 abort_item）。"""

    name = "abort_fetch"

    def __init__(self):
        self.items = ["i1", "i2"]
        self.succeeded = []

    def acquire_item(self, ctx):
        return self.items.pop(0) if self.items else None

    def fetch(self, ctx, item):
        if item == "i1":
            ctx.abort_item.set()   # 看门狗在 fetch 执行期间介入
        return ActionResult(Outcome.OK, "", {"v": item})

    def on_success(self, ctx, item, result):
        self.succeeded.append(item)
        return 1


class TestLoopTimeoutAbort(tcl.LoopTestBase):
    def test_aborted_item_skips_bookkeeping_and_recovers(self):
        task = AbortDuringFetchTask()
        loop, ctx, stats = self.run_loop(task, {}, {}, batch_num=10)
        # i1 被中止：不走 on_success；i2 正常处理
        self.assertEqual(task.succeeded, ["i2"])
        # 中止后浏览器会话重建（初始 1 次 + 中止重建 1 次）
        self.assertEqual(self.mgr.launch_count, 2)
        # 中止信号已清理、item 计时已清除
        self.assertFalse(ctx.abort_item.is_set())
        self.assertNotIn("item_started_at", ctx.state)

    def test_item_started_at_recorded_during_processing(self):
        """正常路径：item 处理期间计时键存在，处理完清除。"""
        seen = []

        class ProbeTask(AbortDuringFetchTask):
            def fetch(self, ctx, item):
                seen.append("item_started_at" in ctx.state)
                return ActionResult(Outcome.OK, "", {})

        task = ProbeTask()
        self.run_loop(task, {}, {}, batch_num=10)
        self.assertEqual(seen, [True, True])


# ---------- 配置 ----------

class TestItemTimeoutConfig(unittest.TestCase):
    def test_default_item_timeout(self):
        self.assertEqual(RunConfig().item_timeout, 1800.0)


if __name__ == "__main__":
    unittest.main()
