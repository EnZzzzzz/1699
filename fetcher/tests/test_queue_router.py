# -*- coding: utf-8 -*-
"""queue_router 单元测试：QueueSpec / eligible_queues / condvar_timeout。

本文件为 P3 Step 1.2 纯函数新增测试（新建文件）。
"""

import unittest

from fetcher.control.queue_router import QueueSpec, condvar_timeout, eligible_queues


# ---------- QueueSpec ----------

class QueueSpecTest(unittest.TestCase):
    """QueueSpec 数据类基本构造与字段访问。"""

    def test_construction_and_fields(self):
        qs = QueueSpec(queue="crawl_1688_contact", site="1688",
                       requires={"channel", "browser"})
        self.assertEqual(qs.queue, "crawl_1688_contact")
        self.assertEqual(qs.site, "1688")
        self.assertEqual(qs.requires, {"channel", "browser"})


# ---------- eligible_queues ----------

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

    # ---- 用例 1：冷却过滤 ----

    def test_all_eligible_with_no_cooldown(self):
        """无冷却时所有队列均可见。"""
        result = eligible_queues(self._registry(), self._ctx(), 100.0)
        self.assertEqual(result, ["crawl_1688_contact", "crawl_madeinchina",
                                  "crawl_1688_search"])

    def test_cooldown_filters_site_queues(self):
        """site A 冷却中 → 该 site 所有队列被滤；site B 到期 → 保留。"""
        ctx = self._ctx(cooldown_until={"1688": 200.0})
        # now=100 < 到期=200 → 1688 冷却中
        result = eligible_queues(self._registry(), ctx, 100.0)
        # 1688 两队列被滤，只剩 madeinchina
        self.assertEqual(result, ["crawl_madeinchina"])

    # ---- 用例 2：资源过滤 ----

    def test_resource_filtering(self):
        """requires 超 resources 的队列被滤。"""
        ctx = self._ctx(resources={"channel"})  # 缺 browser
        result = eligible_queues(self._registry(), ctx, 100.0)
        # crawl_1688_search 只需 channel → visible
        self.assertEqual(result, ["crawl_1688_search"])

    # ---- 用例 3：到期恢复 ----

    def test_expiry_recovery(self):
        """now 推进到冷却到期后 → 队列恢复可见。"""
        ctx = self._ctx(cooldown_until={"1688": 100.0, "madeinchina": 200.0})
        # now=100: 1688 到期（now>=100），madeinchina 仍在冷却（now<200）
        result = eligible_queues(self._registry(), ctx, 100.0)
        self.assertEqual(result, ["crawl_1688_contact", "crawl_1688_search"])

        # now=200: 全部到期
        result2 = eligible_queues(self._registry(), ctx, 200.0)
        self.assertEqual(result2, ["crawl_1688_contact", "crawl_madeinchina",
                                   "crawl_1688_search"])

    def test_empty_registry(self):
        """空注册表返回空列表。"""
        self.assertEqual(eligible_queues([], self._ctx(), 100.0), [])

    def test_empty_resources_still_matches_empty_requires(self):
        """空 resources 仍可匹配空 requires 的队列。"""
        registry = [QueueSpec(queue="no_resources", site="x",
                              requires=set())]
        ctx = self._ctx(resources=set())
        result = eligible_queues(registry, ctx, 100.0)
        self.assertEqual(result, ["no_resources"])


# ---------- condvar_timeout ----------

class CondvarTimeoutTest(unittest.TestCase):
    """condvar_timeout 计算。"""

    # ---- 用例 4：condvar_timeout 计算 ----

    def test_not_in_cooldown_returns_cap(self):
        """不在冷却中 → 返回 cap（默认 30.0）。"""
        self.assertEqual(condvar_timeout({}, "1688", 100.0), 30.0)
        self.assertEqual(condvar_timeout({"other": 200.0}, "1688", 100.0), 30.0)

    def test_in_cooldown_returns_min_of_remaining_and_cap(self):
        """冷却中 → min(到期 - now, cap)。"""
        cooldown_until = {"1688": 120.0}
        # 剩余 20s → min(20, 30)=20
        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 100.0),
                               20.0, delta=1e-9)
        # 剩余 60s → min(60, 30)=30
        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 60.0),
                               30.0, delta=1e-9)

    def test_custom_cap(self):
        """自定义 cap 生效。"""
        cooldown_until = {"1688": 110.0}  # 剩余 10s → min(10,5)=5
        self.assertAlmostEqual(condvar_timeout(cooldown_until, "1688", 100.0,
                                               cap=5.0), 5.0)

    def test_very_small_remaining_returns_positive(self):
        """剩余极小时返回剩余值（>0），不归零、不转负数。"""
        cooldown_until = {"1688": 100.01}  # 剩余 0.01s
        result = condvar_timeout(cooldown_until, "1688", 100.0)
        self.assertGreater(result, 0.0)
        self.assertAlmostEqual(result, 0.01, delta=1e-6)

    def test_exactly_at_deadline_returns_cap(self):
        """now == 到期 → 视为不在冷却，返回 cap。"""
        cooldown_until = {"1688": 100.0}
        self.assertEqual(condvar_timeout(cooldown_until, "1688", 100.0), 30.0)


if __name__ == "__main__":
    unittest.main()
