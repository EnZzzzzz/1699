# -*- coding: utf-8 -*-
"""QueueRouter 单元测试：跨队列认领 / 冷却过滤 / topup / condvar / 终态路由 /
budget_for 路由 / loop 双队列装配。

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
from fetcher.control.queue_router import (
    QueueRouter,
    QueueSpec,
    _WAIT_TIMEOUT,
    condvar_timeout_multi,
    eligible_queues,
)
from fetcher.core.types import ActionResult, Outcome
from fetcher.strategy.policy import Policy


# =====================================================================
# Step 1.2 纯函数测试（I1 恢复）
# =====================================================================

class QueueSpecTest(unittest.TestCase):
    """QueueSpec 数据类基本构造与字段访问。"""

    def test_construction_and_fields(self):
        qs = QueueSpec(queue="crawl_1688_contact", site="1688",
                       requires={"channel", "browser"})
        self.assertEqual(qs.queue, "crawl_1688_contact")
        self.assertEqual(qs.site, "1688")
        self.assertEqual(qs.requires, {"channel", "browser"})


class EligibleQueuesTest(unittest.TestCase):
    """eligible_queues 过滤逻辑：资源满足 + 冷却到期。"""

    def _registry(self):
        return [
            QueueSpec(queue="crawl_1688_contact", site="1688",
                      requires={"channel", "browser"}),
            QueueSpec(queue="crawl_madeinchina", site="madeinchina",
                      requires={"channel", "browser"}),
            QueueSpec(queue="crawl_1688_search", site="1688",
                      requires={"channel"}),
        ]

    def _ctx(self, resources=None, cooldown_until=None):
        return type("FakeCtx", (), {
            "resources": resources or {"channel", "browser"},
            "cooldown_until": cooldown_until or {},
        })()

    def test_all_eligible_with_no_cooldown(self):
        result = eligible_queues(self._registry(), self._ctx(), 100.0)
        self.assertEqual(result, ["crawl_1688_contact", "crawl_madeinchina",
                                  "crawl_1688_search"])

    def test_cooldown_filters_site_queues(self):
        ctx = self._ctx(cooldown_until={"1688": 200.0})
        result = eligible_queues(self._registry(), ctx, 100.0)
        self.assertEqual(result, ["crawl_madeinchina"])

    def test_resource_filtering(self):
        ctx = self._ctx(resources={"channel"})
        result = eligible_queues(self._registry(), ctx, 100.0)
        self.assertEqual(result, ["crawl_1688_search"])

    def test_expiry_recovery(self):
        ctx = self._ctx(cooldown_until={"1688": 100.0, "madeinchina": 200.0})
        result = eligible_queues(self._registry(), ctx, 100.0)
        self.assertEqual(result, ["crawl_1688_contact", "crawl_1688_search"])
        result2 = eligible_queues(self._registry(), ctx, 200.0)
        self.assertEqual(result2, ["crawl_1688_contact", "crawl_madeinchina",
                                   "crawl_1688_search"])

    def test_empty_registry(self):
        self.assertEqual(eligible_queues([], self._ctx(), 100.0), [])

    def test_empty_resources_still_matches_empty_requires(self):
        registry = [QueueSpec(queue="no_resources", site="x", requires=set())]
        ctx = self._ctx(resources=set())
        result = eligible_queues(registry, ctx, 100.0)
        self.assertEqual(result, ["no_resources"])


class CondvarTimeoutPureTest(unittest.TestCase):
    """condvar_timeout_multi 纯函数计算（含边界）。"""

    def test_not_in_cooldown_returns_cap(self):
        self.assertEqual(condvar_timeout_multi({}, ["a"], 100.0), 30.0)

    def test_in_cooldown_returns_min_of_remaining_and_cap(self):
        cooldown_until = {"a": 120.0}
        self.assertAlmostEqual(
            condvar_timeout_multi(cooldown_until, ["a"], 100.0), 20.0, delta=1e-9)
        self.assertAlmostEqual(
            condvar_timeout_multi(cooldown_until, ["a"], 60.0), 30.0, delta=1e-9)

    def test_custom_cap(self):
        cooldown_until = {"a": 110.0}
        self.assertAlmostEqual(
            condvar_timeout_multi(cooldown_until, ["a"], 100.0, cap=5.0), 5.0)

    def test_very_small_remaining_returns_positive(self):
        cooldown_until = {"a": 100.01}
        result = condvar_timeout_multi(cooldown_until, ["a"], 100.0)
        self.assertGreater(result, 0.0)
        self.assertAlmostEqual(result, 0.01, delta=1e-6)

    def test_exactly_at_deadline_returns_cap(self):
        cooldown_until = {"a": 100.0}
        self.assertEqual(condvar_timeout_multi(cooldown_until, ["a"], 100.0), 30.0)

    def test_multi_site_returns_minimum(self):
        """多队列取最小冷却剩余。"""
        cooldown_until = {"1688": 115.0, "madeinchina": 105.0}  # 15s vs 5s
        self.assertAlmostEqual(
            condvar_timeout_multi(cooldown_until, ["1688", "madeinchina"], 100.0),
            5.0, delta=1e-9)


# =====================================================================
# QueueRouter 集成测试


QUEUE_A = "crawl_1688_contact"
QUEUE_B = "crawl_mic_contact"


def _shop_1688(i):
    return {"domain": f"shop{i}.1688.com", "name": f"店铺{i}",
            "url": f"https://shop{i}.1688.com"}


def _shop_mic(i):
    return {"domain": f"shop{i}.cn.made-in-china.com",
            "name": f"MIC店铺{i}",
            "url": f"https://shop{i}.cn.made-in-china.com"}


# ---------- 假 inner task / 假浏览器基建 ----------

class FakeInnerTask(Task):
    """可编程假任务：fetch 恒成功，记录每 worker 的成功/放弃明细。

    acquire_item 不应被 router 透传调用（router 自己实现认领），
    被调到即失败。
    """

    name = "fake-inner"
    unit = "店铺"
    batch_unit = "店铺"

    def __init__(self, budget=None):
        super().__init__()
        self.lock = threading.Lock()
        self.succeeded = []   # [(wid, domain)]
        self.given_up = []    # [(wid, domain, reason, kind)]
        self.fetched = []     # [(wid, domain)]
        self._budget = budget

    @property
    def ip_request_budget(self):
        return self._budget

    def acquire_item(self, ctx):
        raise AssertionError("daemon 模式下不应调到 inner.acquire_item")

    def fetch(self, ctx, item):
        with self.lock:
            self.fetched.append((ctx.wid, item.get("domain", "?")))
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


# ---------- 双队列 helper ----------

def make_dual_registry(inner_a=None, inner_b=None):
    """构建双队列注册表（与 cli _build_registry 同结构）。"""
    if inner_a is None:
        inner_a = FakeInnerTask()
    if inner_b is None:
        inner_b = FakeInnerTask()
    return [
        QueueSpec(
            queue=QUEUE_A,
            site="1688",
            task=inner_a,
            topup=lambda db, limit: db.topup_contact_work_items(
                QUEUE_A, "1688", ".1688.com", limit),
            domain_suffix=".1688.com",
        ),
        QueueSpec(
            queue=QUEUE_B,
            site="madeinchina",
            task=inner_b,
            topup=lambda db, limit: db.topup_contact_work_items(
                QUEUE_B, "madeinchina", ".cn.made-in-china.com", limit),
            domain_suffix=".cn.made-in-china.com",
        ),
    ]


# ---------- 测试基类 ----------

class QueueRouterTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "t.db"
        self.db = ShopDB(self.db_path)
        self.inner_a = FakeInnerTask()
        self.inner_b = FakeInnerTask()
        registry = make_dual_registry(self.inner_a, self.inner_b)
        self.router = QueueRouter(
            registry, db_factory=lambda: ShopDB(self.db_path))

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def make_ctx(self, wid=0, stop=None):
        config = RunConfig(db_path=self.db_path, headless=True,
                           use_proxy=False)
        return WorkerContext(config=config, store=None,
                             stop=stop or threading.Event(),
                             log=lambda m: None, wid=wid)

    def query(self, sql, args=()):
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

    def set_wait_timeout(self, seconds):
        """缩短等货自醒超时（模块级 _WAIT_TIMEOUT 注入点）。"""
        import fetcher.control.queue_router as qr
        orig = qr._WAIT_TIMEOUT
        qr._WAIT_TIMEOUT = seconds
        self.addCleanup(setattr, qr, "_WAIT_TIMEOUT", orig)


# ---------- 用例 1：跨队列认领 ----------

class CrossQueueClaimTest(QueueRouterTestBase):
    def test_claim_across_queues_fifo(self):
        """两队列各有 pending item → claim_next_eligible 跨队列按 id FIFO。"""
        self.db.upsert_shops([_shop_1688(1), _shop_1688(2)])
        self.db.upsert_shops([_shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 2)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        # 队列 A 有 2 个, B 有 1 个，按 id FIFO: A1 < A2 < B1
        ctx = self.make_ctx(wid=0)
        item1 = self.router.acquire_item(ctx)
        self.assertEqual(item1["domain"], "shop1.1688.com")
        self.assertEqual(ctx.state["queue"], QUEUE_A)
        self.assertEqual(ctx.state["active_site"], "1688")

        ctx2 = self.make_ctx(wid=1)
        item2 = self.router.acquire_item(ctx2)
        self.assertEqual(item2["domain"], "shop2.1688.com")

        ctx3 = self.make_ctx(wid=2)
        item3 = self.router.acquire_item(ctx3)
        self.assertEqual(item3["domain"], "shop1.cn.made-in-china.com")
        self.assertEqual(ctx3.state["queue"], QUEUE_B)
        self.assertEqual(ctx3.state["active_site"], "madeinchina")

        # 无货
        ctx4 = self.make_ctx(wid=3)
        self.set_wait_timeout(0.05)
        stop = threading.Event()
        ctx4.stop = stop
        threading.Timer(0.2, stop.set).start()
        item4 = self.router.acquire_item(ctx4)
        self.assertIsNone(item4)

    def test_payload_dict_format(self):
        """claim 返回的 payload 是 dict，含 domain/name/url。"""
        self.db.upsert_shops([_shop_1688(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        item = self.router.acquire_item(self.make_ctx())
        self.assertIsInstance(item, dict)
        self.assertEqual(item["domain"], "shop1.1688.com")
        self.assertEqual(item["name"], "店铺1")
        self.assertEqual(item["url"], "https://shop1.1688.com")

    def test_state_keys_set_on_claim(self):
        """claim 成功后三个状态键正确写入。"""
        self.db.upsert_shops([_shop_1688(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        ctx = self.make_ctx()
        self.assertNotIn("daemon_work_item_id", ctx.state)
        self.assertNotIn("queue", ctx.state)
        self.assertNotIn("active_site", ctx.state)

        item = self.router.acquire_item(ctx)
        self.assertIsNotNone(ctx.state["daemon_work_item_id"])
        # payload 不含 id（id 只在 ctx.state 中），其他 keys 在
        self.assertEqual(ctx.state["queue"], QUEUE_A)
        self.assertEqual(ctx.state["active_site"], "1688")


# ---------- 用例 2：冷却过滤 ----------

class CooldownFilterTest(QueueRouterTestBase):
    def test_cooldown_filters_site_a_allows_b(self):
        """site A 冷却中 → 只认领 site B 队列。"""
        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)
        ctx = self.make_ctx()
        # 1688 冷却中（30s），madeinchina 未冷却
        ctx.cooldown_until["1688"] = time.time() + 30
        # madeinchina 未冷却

        item = self.router.acquire_item(ctx)
        self.assertIsNotNone(item)
        # 应该领到 B 队列（madeinchina），因为 A 冷却中不可见
        self.assertEqual(ctx.state["queue"], QUEUE_B)
        self.assertEqual(ctx.state["active_site"], "madeinchina")
        self.assertEqual(item["domain"], "shop1.cn.made-in-china.com")

    def test_cooldown_expired_allows_claim(self):
        """冷却到期后恢复认领。"""
        self.db.upsert_shops([_shop_1688(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        ctx = self.make_ctx()
        ctx.cooldown_until["1688"] = time.time() - 1.0  # 已过期

        item = self.router.acquire_item(ctx)
        self.assertIsNotNone(item)
        self.assertEqual(item["domain"], "shop1.1688.com")

    def test_cooldown_eventually_expires_and_claims(self):
        """冷却中等待到期后自动认领。"""
        self.db.upsert_shops([_shop_1688(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        ctx = self.make_ctx()
        ctx.cooldown_until["1688"] = time.time() + 0.25

        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                self.router.acquire_item(ctx)),
            daemon=True)
        t.start()

        # 0.1s 后冷却应仍有效
        time.sleep(0.10)
        rows = self.query("SELECT status FROM work_items WHERE queue=?",
                          (QUEUE_A,))
        self.assertEqual([r["status"] for r in rows], ["pending"])

        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0]["domain"], "shop1.1688.com")


# ---------- 用例 3：topup 只对到期队列 ----------

class TopupPerQueueTest(QueueRouterTestBase):
    def test_topup_only_for_expired_queue(self):
        """冷却中队列不补货；到期队列补货后 notify + 重试认领。"""
        # seed B 的 shops，不 seed A
        self.db.upsert_shops([_shop_mic(1), _shop_mic(2)])
        ctx = self.make_ctx()
        # 1688 冷却中，madeinchina 未冷却
        ctx.cooldown_until["1688"] = time.time() + 30

        # 初始无 work_items → acquire 走 topup 路径
        item = self.router.acquire_item(ctx)

        self.assertIsNotNone(item)
        # 应补货并认领 B 队列的
        self.assertEqual(ctx.state["queue"], QUEUE_B)
        self.assertEqual(item["domain"], "shop1.cn.made-in-china.com")

        # A 队列不应有 work_items（topup 被冷却阻挡）
        rows_a = self.query("SELECT COUNT(*) AS c FROM work_items"
                            " WHERE queue=?", (QUEUE_A,))
        self.assertEqual(rows_a[0]["c"], 0)


# ---------- 用例 4：condvar timeout ----------

class RouterCondvarTimeoutTest(QueueRouterTestBase):
    def test_timeout_with_cooldown(self):
        """冷却中 wait 剩余时间（取各 site 最小值）。"""
        # seed shops for madeinchina so when cooldown expires, claim succeeds
        self.db.upsert_shops([_shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)
        ctx = self.make_ctx()
        ctx.cooldown_until["1688"] = time.time() + 15
        ctx.cooldown_until["madeinchina"] = time.time() + 0.5  # 最小值 0.5s

        # 两站点都在冷却 → no eligible queues → condvar wait
        self.set_wait_timeout(30)  # 设大兜底，实际 0.5s 到期
        stop = threading.Event()
        ctx.stop = stop

        result_holder = []
        errors = []

        def run():
            try:
                result_holder.append(self.router.acquire_item(ctx))
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=run, daemon=True)
        t0 = time.monotonic()
        t.start()

        # madeinchina 冷却到期 → 醒来 → claim_next_eligible 命中
        t.join(timeout=10)
        stop.set()
        elapsed = time.monotonic() - t0

        self.assertEqual(errors, [])
        self.assertGreaterEqual(elapsed, 0.4)
        self.assertLess(elapsed, 8.0)
        self.assertEqual(len(result_holder), 1)
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0]["domain"], "shop1.cn.made-in-china.com")

    def test_timeout_no_cooldown_30s(self):
        """无冷却 → 30s 自醒兜底。"""
        ctx = self.make_ctx()
        self.set_wait_timeout(0.1)  # 注入小自醒超时加速测试
        stop = threading.Event()
        ctx.stop = stop

        result_holder = []
        t = threading.Thread(
            target=lambda: result_holder.append(
                self.router.acquire_item(ctx)),
            daemon=True)
        t0 = time.monotonic()
        t.start()

        # 等一小段时间后设 stop
        time.sleep(0.3)
        stop.set()
        t.join(timeout=2)
        elapsed = time.monotonic() - t0

        self.assertFalse(t.is_alive())
        # 在注入的 0.1s 量级醒来
        self.assertLess(elapsed, 2.0)
        self.assertIsNone(result_holder[0])

    def test_stop_exits_during_wait(self):
        """stop 置位后 acquire 返回 None。"""
        self.set_wait_timeout(0.05)
        stop = threading.Event()
        ctx = self.make_ctx(stop=stop)
        threading.Timer(0.3, stop.set).start()

        t0 = time.monotonic()
        item = self.router.acquire_item(ctx)
        elapsed = time.monotonic() - t0

        self.assertIsNone(item)
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertLess(elapsed, 5.0)


# ---------- 用例 5：on_success/on_giveup 路由 ----------

class TerminalHookRoutingTest(QueueRouterTestBase):
    def test_on_success_routes_correctly(self):
        """on_success 路由到 item 所属 queue 的 task + 落 done。"""
        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        ctx_a = self.make_ctx(wid=0)
        item_a = self.router.acquire_item(ctx_a)
        result = ActionResult(Outcome.OK, "", {"mobile": "138"})
        n = self.router.on_success(ctx_a, item_a, result)

        self.assertEqual(n, 1)
        self.assertEqual(self.inner_a.succeeded, [(0, "shop1.1688.com")])
        self.assertEqual(self.inner_b.succeeded, [])
        row = self.work_item(item_a["id"])
        self.assertEqual(row["status"], "done")
        self.assertNotIn("daemon_work_item_id", ctx_a.state)

        ctx_b = self.make_ctx(wid=1)
        item_b = self.router.acquire_item(ctx_b)
        n2 = self.router.on_success(ctx_b, item_b, result)

        self.assertEqual(n2, 1)
        self.assertEqual(self.inner_b.succeeded,
                         [(1, "shop1.cn.made-in-china.com")])
        self.assertEqual(len(self.inner_a.succeeded), 1)

    def test_on_giveup_routes_correctly(self):
        """on_giveup 路由到 item 所属 queue 的 task + 落 failed。"""
        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        ctx_a = self.make_ctx(wid=0)
        item_a = self.router.acquire_item(ctx_a)
        phrase = self.router.on_giveup(ctx_a, item_a, "风控", "block")

        self.assertEqual(phrase, "标记跳过")
        self.assertEqual(self.inner_a.given_up,
                         [(0, "shop1.1688.com", "风控", "block")])
        self.assertEqual(self.inner_b.given_up, [])
        row = self.work_item(item_a["id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(json.loads(row["result_json"]),
                         {"reason": "风控", "kind": "block"})

        ctx_b = self.make_ctx(wid=1)
        item_b = self.router.acquire_item(ctx_b)
        phrase2 = self.router.on_giveup(ctx_b, item_b, "网络错误", "net")

        self.assertEqual(phrase2, "标记跳过")
        self.assertEqual(self.inner_b.given_up,
                         [(1, "shop1.cn.made-in-china.com", "网络错误", "net")])
        self.assertEqual(len(self.inner_a.given_up), 1)

    def test_finish_idempotent(self):
        """重复 finish 幂等（state key 已 pop）。"""
        self.db.upsert_shops([_shop_1688(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        ctx = self.make_ctx()
        item = self.router.acquire_item(ctx)
        result = ActionResult(Outcome.OK, "", {})

        self.router.on_success(ctx, item, result)
        # 第二次 on_success（state key 已 pop）
        self.router.on_success(ctx, item, result)
        row = self.work_item(item["id"])
        self.assertEqual(row["status"], "done")

    def test_stray_finish_does_not_affect_other_item(self):
        """stray finish（不同 ctx，state key 已 pop）不动错 item。

        与 DaemonTaskProxy 原测试一致：用不同 ctx 对象模拟跨 worker 场景。
        ctx0 的 state key 在 finish 后已 pop，后续 stray on_success 是 no-op。
        """
        self.db.upsert_shops([_shop_1688(1), _shop_1688(2), _shop_1688(3)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 3)

        ctx0 = self.make_ctx(wid=0)
        ctx1 = self.make_ctx(wid=1)
        result = ActionResult(Outcome.OK, "", {})

        # ctx0 认领 item_a 并 finish
        item_a = self.router.acquire_item(ctx0)
        self.router.on_success(ctx0, item_a, result)
        self.assertEqual(self.work_item(item_a["id"])["status"], "done")

        # ctx1 认领 item_c（跳过 item_b 因为 ctx0 已完成 item_a）
        item_c = self.router.acquire_item(ctx1)

        # ctx0 的 stray on_success（state key 已 pop）不应动 item_c
        self.router.on_success(ctx0, item_a, result)
        row_c = self.work_item(item_c["id"])
        self.assertEqual(row_c["status"], "claimed")
        self.assertEqual(row_c["claimed_by"], "w1")

        # item_a 也不被重复落库
        self.assertEqual(self.work_item(item_a["id"])["status"], "done")


# ---------- 用例 6：budget_for 路由 ----------

class BudgetForTest(QueueRouterTestBase):
    def test_budget_for_routes_per_site(self):
        """不同 site 的 task 返回不同预算。"""
        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        # 设置不同预算
        self.inner_a._budget = 50
        self.inner_b._budget = 100

        ctx_a = self.make_ctx()
        self.router.acquire_item(ctx_a)  # A 队列
        self.assertEqual(self.router.budget_for(ctx_a), 50)

        ctx_b = self.make_ctx()
        self.router.acquire_item(ctx_b)  # B 队列
        self.assertEqual(self.router.budget_for(ctx_b), 100)

    def test_budget_for_no_queue_returns_none(self):
        """无 queue 在 state 时 budget_for 返回 None。"""
        ctx = self.make_ctx()
        self.assertIsNone(self.router.budget_for(ctx))

    def test_router_ip_request_budget_property_is_none(self):
        """QueueRouter.ip_request_budget 始终返回 None（必须 per-site）。"""
        self.assertIsNone(self.router.ip_request_budget)


# ---------- 用例 8：Task 基类 budget_for 兼容 ----------

class TaskBudgetForCompatTest(unittest.TestCase):
    def test_task_base_budget_for_returns_ip_request_budget(self):
        """Task 基类 budget_for 默认返回 ip_request_budget（CLI 零影响）。"""
        from fetcher.control.task import Task as BaseTask
        task = BaseTask()
        task.ip_request_budget = 42
        self.assertEqual(task.budget_for(None), 42)

        task2 = BaseTask()
        self.assertIsNone(task2.budget_for(None))


# ---------- 用例 7：loop 双队列装配 ----------

class LoopDualQueueTest(unittest.TestCase):
    """sites/policies 注入 → ctx.site/inspector/policy 切换正确；
    CLI 路径（sites=None）行为不变。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "t.db"
        self.db = ShopDB(self.db_path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_loop_binds_site_on_item_acquisition(self):
        """处理 site A item 时 ctx.site/inspector/policy 切换正确。"""
        from fetcher.sites import get_site
        site_1688 = get_site("1688")
        site_mic = get_site("madeinchina")

        self.db.upsert_shops([_shop_1688(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)

        inner = FakeInnerTask()
        registry = [
            QueueSpec(queue=QUEUE_A, site="1688", task=inner,
                      topup=lambda db, limit: db.topup_contact_work_items(
                          QUEUE_A, "1688", ".1688.com", limit),
                      domain_suffix=".1688.com"),
        ]
        router = QueueRouter(registry, db_factory=lambda: ShopDB(self.db_path))

        config = RunConfig(db_path=self.db_path, headless=True,
                           use_proxy=False, batch_num=1, max_batches=1,
                           sample_min=0, sample_max=0, rest_every=0,
                           max_consecutive_fail=3)
        stop = threading.Event()
        store = IdentityStore(ShopDB(self.db_path))
        ctx = WorkerContext(
            config=config, store=store,
            browser_manager=MockBrowserManager(FakePage()),
            site=None,  # daemon 模式初始无 site
            stop=stop, log=lambda m: None, wid=0)

        policy_1688 = Policy(max_consecutive_fail=3)
        sites = {"1688": site_1688, "madeinchina": site_mic}
        policies = {"1688": policy_1688}

        loop = CrawlLoop(ctx, router, policy=Policy(max_consecutive_fail=3),
                         sites=sites, policies=policies,
                         inspector=None)  # daemon 模式延迟建

        # 初始无 site / no inspector (daemon path)
        self.assertIsNone(loop._bound_site)

        # 手动模拟 acquire_item + _bind_item_site（不跑完整 loop.run）
        item = router.acquire_item(ctx)
        loop._bind_item_site()

        self.assertEqual(loop._bound_site, "1688")
        self.assertEqual(ctx.site, site_1688)
        self.assertIsNotNone(loop.inspector)
        self.assertEqual(loop.policy, policy_1688)

        stop.set()

    def test_cli_path_sites_none_unchanged(self):
        """CLI 路径（sites=None）_bind_item_site 无操作。"""
        from fetcher.sites import get_site

        config = RunConfig(db_path=self.db_path, headless=True,
                           use_proxy=False, batch_num=1, max_batches=1,
                           sample_min=0, sample_max=0, rest_every=0,
                           max_consecutive_fail=3)
        stop = threading.Event()
        store = IdentityStore(ShopDB(self.db_path))
        site = get_site("1688")
        ctx = WorkerContext(
            config=config, store=store,
            browser_manager=MockBrowserManager(FakePage()),
            site=site, stop=stop, log=lambda m: None, wid=0)

        task = FakeInnerTask()
        loop = CrawlLoop(ctx, task, policy=Policy(max_consecutive_fail=3))

        self.assertEqual(ctx.site, site)
        orig_inspector = loop.inspector
        orig_policy = loop.policy
        self.assertIsNotNone(loop._bound_site)

        # _bind_item_site 无操作
        orig_bound = loop._bound_site
        loop._bind_item_site()
        self.assertEqual(ctx.site, site)
        self.assertIs(loop.inspector, orig_inspector)
        self.assertIs(loop.policy, orig_policy)
        self.assertEqual(loop._bound_site, orig_bound)

        stop.set()


# ---------- 用例 9：CrawlLoop 联跑 ----------

class CrawlLoopIntegrationTest(QueueRouterTestBase):
    def test_crawl_loop_two_workers_shared_router(self):
        """单个 worker 线程跑 QueueRouter + CrawlLoop，跑完 N 项后 stop 退出。"""
        self.set_wait_timeout(0.1)
        n_items = 2  # 1 per queue, single worker
        self.db.upsert_shops([_shop_1688(1)])
        self.db.upsert_shops([_shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        config = RunConfig(db_path=self.db_path, headless=True,
                           use_proxy=False, batch_num=100, max_batches=1,
                           sample_min=0, sample_max=0, rest_every=0,
                           batch_rest=0.01, block_rest_min=0.01,
                           block_rest_max=0.02, ip_retry=1,
                           max_consecutive_fail=3, workers=1)
        stop = threading.Event()
        errors = {}

        from fetcher.sites import get_site
        sites = {"1688": get_site("1688"),
                 "madeinchina": get_site("madeinchina")}
        policies = {
            "1688": Policy(max_consecutive_fail=3),
            "madeinchina": Policy(max_consecutive_fail=3),
        }

        def run_worker():
            try:
                store = IdentityStore(ShopDB(self.db_path))
                ctx = WorkerContext(
                    config=config, store=store,
                    browser_manager=MockBrowserManager(FakePage()),
                    site=None, stop=stop, log=lambda m: None, wid=0)
                loop = CrawlLoop(ctx, self.router,
                                 policy=Policy(max_consecutive_fail=3),
                                 sites=sites, policies=policies)
                loop.run()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                errors[0] = e

        t = threading.Thread(target=run_worker, daemon=True)
        t.start()

        # 监视：全部落 done 后置 stop
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            done = self.query("SELECT COUNT(*) AS c FROM work_items"
                              " WHERE status='done'")[0]["c"]
            if done >= n_items:
                break
            time.sleep(0.02)
        stop.set()
        t.join(timeout=10)

        self.assertEqual(errors, {})
        self.assertFalse(t.is_alive())

        # 终态：N 项全 done
        rows = self.query("SELECT status, COUNT(*) AS c FROM work_items"
                          " GROUP BY status")
        self.assertEqual({r["status"]: r["c"] for r in rows},
                         {"done": n_items})

        # 两 inner 的成功明细不串
        domains_a = [d for _w, d in self.inner_a.succeeded]
        domains_b = [d for _w, d in self.inner_b.succeeded]
        self.assertEqual(sorted(domains_a + domains_b),
                         sorted(["shop1.1688.com", "shop1.cn.made-in-china.com"]))


# ---------- Router 属性测试 ----------

class RouterAttributesTest(QueueRouterTestBase):
    def test_unit_is_xiang(self):
        self.assertEqual(self.router.unit, "项")

    def test_batch_unit_empty(self):
        self.assertEqual(self.router.batch_unit, "")

    def test_cold_start_before_acquire_false(self):
        self.assertFalse(self.router.cold_start_before_acquire)

    def test_rest_counter(self):
        stats = {"done": 5, "other": 3}
        self.assertEqual(self.router.rest_counter(stats), 5)
        self.assertEqual(self.router.rest_counter({"done": 0}), 0)

    def test_ip_request_budget_is_none(self):
        self.assertIsNone(self.router.ip_request_budget)


# ---------- 执行侧路由测试 ----------

class ExecutionRoutingTest(QueueRouterTestBase):
    def test_fetch_routes_to_correct_task(self):
        """fetch 路由到 ctx.state["queue"] 对应的 task。"""
        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        ctx_a = self.make_ctx()
        item_a = self.router.acquire_item(ctx_a)
        result = self.router.fetch(ctx_a, item_a)
        self.assertEqual(self.inner_a.fetched, [(0, "shop1.1688.com")])
        self.assertEqual(self.inner_b.fetched, [])
        self.assertEqual(result.outcome, Outcome.OK)

        ctx_b = self.make_ctx(wid=1)
        item_b = self.router.acquire_item(ctx_b)
        result2 = self.router.fetch(ctx_b, item_b)
        self.assertEqual(self.inner_b.fetched,
                         [(1, "shop1.cn.made-in-china.com")])

    def test_validate_routes_correctly(self):
        """validate 路由正确。"""
        inner_a = FakeInnerTask()
        inner_a.validate = lambda ctx, item, result: True
        inner_b = FakeInnerTask()
        inner_b.validate = lambda ctx, item, result: False
        router = QueueRouter(make_dual_registry(inner_a, inner_b),
                             db_factory=lambda: ShopDB(self.db_path))

        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        ctx_a = self.make_ctx()
        item_a = router.acquire_item(ctx_a)
        self.assertTrue(router.validate(ctx_a, item_a, None))

        ctx_b = self.make_ctx()
        item_b = router.acquire_item(ctx_b)
        self.assertFalse(router.validate(ctx_b, item_b, None))

    def test_label_routes_correctly(self):
        """label 路由正确。"""
        inner_a = FakeInnerTask()
        inner_a.label = lambda item: f"A:{item['domain']}"
        inner_b = FakeInnerTask()
        inner_b.label = lambda item: f"B:{item['domain']}"
        router = QueueRouter(make_dual_registry(inner_a, inner_b),
                             db_factory=lambda: ShopDB(self.db_path))

        self.db.upsert_shops([_shop_1688(1), _shop_mic(1)])
        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
        self.db.topup_contact_work_items(QUEUE_B, "madeinchina",
                                         ".cn.made-in-china.com", 1)

        ctx_a = self.make_ctx()
        item_a = router.acquire_item(ctx_a)
        self.assertEqual(router.label(item_a), "A:shop1.1688.com")

        ctx_b = self.make_ctx()
        item_b = router.acquire_item(ctx_b)
        self.assertEqual(router.label(item_b), "B:shop1.cn.made-in-china.com")


if __name__ == "__main__":
    unittest.main()
