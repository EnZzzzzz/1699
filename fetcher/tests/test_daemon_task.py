# -*- coding: utf-8 -*-
"""DaemonTaskProxy 单元测试：三段式 acquire_item / 终态钩子 / CrawlLoop 联跑。

真实临时 sqlite + 真实线程/条件变量，不 mock 被测对象本身；
浏览器/网络侧沿用 test_control_loop.py 的假基建模式（FakePage/
MockBrowserManager），inner task 用可编程的假实现。
"""

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fetcher import (
    Alibaba1688Plugin,
    IdentityStore,
    RunConfig,
    ShopDB,
    Session,
    WorkerContext,
)
from fetcher.control import CrawlLoop, Task
from fetcher.control import daemon_task
from fetcher.control.daemon_task import DaemonTaskProxy
from fetcher.core.types import ActionResult, Outcome
from fetcher.strategy.policy import Policy

QUEUE = "crawl_1688_contact"


def _shop(i):
    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
            "url": f"https://shop{i}.1688.com"}


# ---------- 假 inner task / 假浏览器基建 ----------

class FakeInnerTask(Task):
    """可编程假任务：fetch 恒成功，记录每 worker 的成功/放弃明细。

    acquire_item 不应被 proxy 透传调用（proxy 自己实现认领），
    被调到即失败，防「proxy 偷偷走 inner 认领路径」的假阳性。
    """

    name = "fake-inner"
    unit = "店铺"
    batch_unit = "店铺"

    def __init__(self):
        self.lock = threading.Lock()
        self.succeeded = []  # [(wid, domain)]
        self.given_up = []   # [(wid, domain, reason, kind)]

    def acquire_item(self, ctx):
        raise AssertionError("daemon 模式下不应调到 inner.acquire_item")

    def fetch(self, ctx, item):
        return ActionResult(Outcome.OK, "", {"v": 1})

    def on_success(self, ctx, item, result):
        with self.lock:
            self.succeeded.append((ctx.wid, item["domain"]))
        stats = ctx.state.get("task", {}).get("stats")
        if stats is not None:
            stats["done"] = stats.get("done", 0) + 1
        return 1

    def on_giveup(self, ctx, item, reason, kind):
        with self.lock:
            self.given_up.append((ctx.wid, item["domain"], reason, kind))
        return "标记跳过"

    def make_stats(self):
        return {"done": 0}


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
        self.url = "https://shop1.1688.com/page/contactinfo.htm"
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
    """launch 返回带假 page 的 Session（联跑用，不起真实浏览器）。"""

    def __init__(self, page):
        self.page = page

    def launch(self, seed_kit=None, stop=None):
        return Session(browser=FakeBrowser(), page=self.page,
                       identity="1688:1.1.1.1", seed_kit=seed_kit)

    def check_ip_fresh(self, session):
        return False, session.identity, ""

    def save_cookies(self, session):
        return 0


# ---------- 测试基类 ----------

class DaemonTaskTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "t.db"
        # 种子数据/断言用主连接；proxy 走 db_factory 注入（ctx.store=None 路径）
        self.db = ShopDB(self.db_path)
        self.inner = FakeInnerTask()
        self.proxy = DaemonTaskProxy(
            inner=self.inner, queue=QUEUE, site="1688",
            domain_suffix=".1688.com",
            db_factory=lambda: ShopDB(self.db_path))

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def make_ctx(self, wid=0, stop=None):
        """store=None 的轻量 ctx：proxy 经 db_factory 按线程自建连接。"""
        config = RunConfig(db_path=self.db_path, headless=True,
                           use_proxy=False)
        return WorkerContext(config=config, store=None,
                             stop=stop or threading.Event(),
                             log=lambda m: None, wid=wid)

    def query(self, sql, args=()):
        """断言另开连接（避免与 proxy 持有的连接相互干扰）。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def work_item(self, item_id):
        rows = self.query("SELECT * FROM work_items WHERE id=?", (item_id,))
        self.assertEqual(len(rows), 1)
        return rows[0]

    def shop_status(self, domain):
        return self.query("SELECT status FROM shops WHERE domain=?",
                          (domain,))[0]["status"]

    def set_wait_timeout(self, seconds):
        """缩短等货自醒超时（模块级 _WAIT_TIMEOUT 注入点）。"""
        orig = daemon_task._WAIT_TIMEOUT
        daemon_task._WAIT_TIMEOUT = seconds
        self.addCleanup(setattr, daemon_task, "_WAIT_TIMEOUT", orig)


# ---------- 用例 ----------

class AcquireItemTest(DaemonTaskTestBase):
    # 用例 1：有货直取——预置 pending work_items，acquire 返回 payload dict
    def test_acquire_claims_pending_work_item(self):
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)

        ctx = self.make_ctx(wid=3)
        item = self.proxy.acquire_item(ctx)

        self.assertIsNotNone(item)
        self.assertIn("id", item)
        # domain/name/url 三键必在（name/url 允许 None）
        for key in ("domain", "name", "url"):
            self.assertIn(key, item)
        self.assertEqual(item["domain"], "shop1.1688.com")  # 最老 pending 先领
        self.assertEqual(item["name"], "店铺1")
        self.assertEqual(item["url"], "https://shop1.1688.com")
        # 库内：claimed + claimed_by=w{wid}
        row = self.work_item(item["id"])
        self.assertEqual(row["status"], "claimed")
        self.assertEqual(row["claimed_by"], "w3")
        self.assertIsNotNone(row["claimed_at"])
        # work_item id 记在本 worker 的 ctx.state 上
        self.assertEqual(ctx.state["daemon_work_item_id"], item["id"])

    # 用例 2：空队列自动补货——shops 有 pending、work_items 为空
    def test_acquire_auto_topup_when_queue_empty(self):
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.assertEqual(self.query("SELECT COUNT(*) AS c FROM work_items")[0]["c"], 0)

        item = self.proxy.acquire_item(self.make_ctx())

        self.assertIsNotNone(item)
        self.assertEqual(item["domain"], "shop1.1688.com")
        # 补货把两家 pending 店铺都入了队并标 in_progress
        self.assertEqual(self.shop_status("shop1.1688.com"), "in_progress")
        self.assertEqual(self.shop_status("shop2.1688.com"), "in_progress")
        rows = self.query("SELECT status FROM work_items ORDER BY id")
        self.assertEqual([r["status"] for r in rows], ["claimed", "pending"])

    # 用例 3：stop 退出——队列空且无法补货，stop 置位后小超时内返回 None
    def test_acquire_returns_none_after_stop(self):
        self.set_wait_timeout(0.05)  # 注入小自醒超时，避免等满 30s
        stop = threading.Event()
        ctx = self.make_ctx(stop=stop)
        threading.Timer(0.3, stop.set).start()

        t0 = time.monotonic()
        item = self.proxy.acquire_item(ctx)
        elapsed = time.monotonic() - t0

        self.assertIsNone(item)
        # 确实阻塞等到了 stop（非「队列空立即返回 None」的快路径）
        self.assertGreaterEqual(elapsed, 0.25)
        # stop 后在注入的小超时量级内醒来返回，不会卡满 30s
        self.assertLess(elapsed, 5.0)


class CooldownFilterTest(DaemonTaskTestBase):
    # 用例 4：冷却中不 claim——注入带冷却的 ctx → acquire 阻塞（等超时
    # 唤醒路径），不 claim 不 topup
    def test_cooldown_blocks_claim(self):
        """冷却中 → acquire_item 不 claim 不 topup，等待冷却到期后才认领。"""
        self.db.upsert_shops([_shop(1), _shop(2)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 2)
        ctx = self.make_ctx(wid=0)
        # 设置 0.25s 冷却（短但可观测）
        ctx.cooldown_until["1688"] = time.time() + 0.25

        result_holder = []
        t = threading.Thread(target=lambda:
                             result_holder.append(self.proxy.acquire_item(ctx)),
                             daemon=True)
        t.start()

        # 0.1s 后冷却应仍有效：工作项未认领
        time.sleep(0.10)
        rows = self.query("SELECT status FROM work_items WHERE queue=?"
                          " ORDER BY id", (QUEUE,))
        self.assertEqual([r["status"] for r in rows], ["pending", "pending"])

        # 等待 acquire 完成（冷却到期后自动认领）
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "acquire_item 线程应在冷却到期后完成")
        self.assertEqual(len(result_holder), 1)
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0]["domain"], "shop1.1688.com")

    # 用例 5：冷却到期后恢复认领
    def test_cooldown_expired_allows_claim(self):
        """冷却已到期 → acquire_item 正常 claim（不阻塞）。"""
        self.db.upsert_shops([_shop(1)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 1)
        ctx = self.make_ctx(wid=0)
        # 冷却已过期（过去）
        ctx.cooldown_until["1688"] = time.time() - 1.0

        item = self.proxy.acquire_item(ctx)

        self.assertIsNotNone(item)
        self.assertEqual(item["domain"], "shop1.1688.com")

    # 用例 6：claim 成功后 active_site 正确写入
    def test_active_site_set_on_claim(self):
        """claim 成功后 ctx.state["active_site"] = self._site。"""
        self.db.upsert_shops([_shop(1)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 1)
        ctx = self.make_ctx(wid=0)

        self.assertNotIn("active_site", ctx.state)
        self.proxy.acquire_item(ctx)
        self.assertEqual(ctx.state.get("active_site"), "1688")


class TerminalHookTest(DaemonTaskTestBase):
    # 用例 4：终态钩子——on_success→done / on_giveup→failed，重复 finish 幂等
    def test_terminal_hooks_finish_work_item(self):
        self.db.upsert_shops([_shop(1), _shop(2), _shop(3)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", 3)
        ctx0, ctx1 = self.make_ctx(wid=0), self.make_ctx(wid=1)
        result = ActionResult(Outcome.OK, "", {"mobile": "13800138000"})

        # on_success：透传 inner 返回值，work_item 落 done
        item_a = self.proxy.acquire_item(ctx0)
        n = self.proxy.on_success(ctx0, item_a, result)
        self.assertEqual(n, 1)  # inner.on_success 的返回值透传
        self.assertEqual(self.inner.succeeded, [(0, "shop1.1688.com")])
        row_a = self.work_item(item_a["id"])
        self.assertEqual(row_a["status"], "done")
        self.assertIsNotNone(row_a["finished_at"])
        self.assertIsNone(row_a["result_json"])  # 成功不带 result
        self.assertNotIn("daemon_work_item_id", ctx0.state)  # pop 语义

        # on_giveup：透传短语，work_item 落 failed + reason/kind 落 result_json
        item_b = self.proxy.acquire_item(ctx1)
        phrase = self.proxy.on_giveup(ctx1, item_b, "风控滑块", "block")
        self.assertEqual(phrase, "标记跳过")  # inner.on_giveup 的返回值透传
        self.assertEqual(self.inner.given_up,
                         [(1, "shop2.1688.com", "风控滑块", "block")])
        row_b = self.work_item(item_b["id"])
        self.assertEqual(row_b["status"], "failed")
        self.assertIsNotNone(row_b["finished_at"])
        self.assertEqual(json.loads(row_b["result_json"]),
                         {"reason": "风控滑块", "kind": "block"})

        # 重复 finish 幂等：state 已 pop，第二次 on_giveup 不再落库
        # （用不同 reason 调用，验证 result_json 保持首次的值）
        self.proxy.on_giveup(ctx1, item_b, "另一个原因", "net")
        row_b2 = self.work_item(item_b["id"])
        self.assertEqual(row_b2["status"], "failed")
        self.assertEqual(json.loads(row_b2["result_json"]),
                         {"reason": "风控滑块", "kind": "block"})

        # 不误伤其他 item：ctx1 认领 item_c 后，ctx0（state 已空）的
        # stray on_success 不应动 item_c
        item_c = self.proxy.acquire_item(ctx1)
        self.proxy.on_success(ctx0, item_a, result)
        row_c = self.work_item(item_c["id"])
        self.assertEqual(row_c["status"], "claimed")
        self.assertEqual(row_c["claimed_by"], "w1")
        # item_a 也不被重复落库改状态
        self.assertEqual(self.work_item(item_a["id"])["status"], "done")


class CrawlLoopIntegrationTest(DaemonTaskTestBase):
    # 用例 5：CrawlLoop 联跑——proxy 包假 inner，两个 worker 线程共享一个
    # proxy 实例，跑完 N 项后 stop 置位，loop 正常退出且终态/统计正确
    def test_crawl_loop_two_workers_shared_proxy(self):
        self.set_wait_timeout(0.05)
        n_items = 6
        self.db.upsert_shops([_shop(i) for i in range(1, n_items + 1)])
        self.db.topup_contact_work_items(QUEUE, "1688", ".1688.com", n_items)

        config = RunConfig(db_path=self.db_path, headless=True,
                           use_proxy=False, batch_num=100, max_batches=0,
                           sample_min=0, sample_max=0, rest_every=0,
                           batch_rest=0.01, block_rest_min=0.01,
                           block_rest_max=0.02, ip_retry=1,
                           max_consecutive_fail=3, workers=2)
        stop = threading.Event()
        results, errors = {}, {}

        def run_worker(wid):
            try:
                store = IdentityStore(ShopDB(self.db_path))
                ctx = WorkerContext(
                    config=config, store=store,
                    browser_manager=MockBrowserManager(FakePage()),
                    site=Alibaba1688Plugin(), stop=stop,
                    log=lambda m: None, wid=wid)
                policy = Policy(table={}, strategies={},
                                max_consecutive_fail=3)
                results[wid] = CrawlLoop(ctx, self.proxy, policy=policy).run()
            except Exception as e:  # noqa: BLE001
                errors[wid] = e

        threads = [threading.Thread(target=run_worker, args=(wid,),
                                    name=f"worker-{wid}", daemon=True)
                   for wid in (0, 1)]
        for t in threads:
            t.start()

        # 监视：全部落 done 后置 stop，worker 从等货中醒来退出
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            done = self.query("SELECT COUNT(*) AS c FROM work_items"
                              " WHERE status='done'")[0]["c"]
            if done >= n_items:
                break
            time.sleep(0.02)
        stop.set()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, {})
        self.assertFalse(any(t.is_alive() for t in threads),
                         "worker 未在 stop 后退出")
        self.assertEqual(set(results), {0, 1})

        # 终态：N 项全 done，无残留 claimed/pending
        rows = self.query("SELECT status, COUNT(*) AS c FROM work_items"
                          " GROUP BY status")
        self.assertEqual({r["status"]: r["c"] for r in rows},
                         {"done": n_items})

        # 不串 item：两 worker 认领的 domain 合起来恰好是全集且无重复
        domains = [d for _wid, d in self.inner.succeeded]
        self.assertEqual(len(domains), n_items)
        self.assertEqual(sorted(domains),
                         [f"shop{i}.1688.com" for i in range(1, n_items + 1)])

        # stats：各 worker 的 done 计数与其成功明细一致，总和 = N
        per_wid = {wid: sum(1 for w, _d in self.inner.succeeded if w == wid)
                   for wid in (0, 1)}
        for wid in (0, 1):
            self.assertEqual(results[wid]["done"], per_wid[wid])
        self.assertEqual(sum(per_wid.values()), n_items)


if __name__ == "__main__":
    unittest.main()
