# -*- coding: utf-8 -*-
"""
P1 FlowExecutor 单元测试（stdlib unittest，全 Fake 隔离：
无真实浏览器/网络/Redis/SQLite）。

假原子以 test_exec_ 前缀注册（registry 全局，避免与 atoms/ 及其他测试
文件的 test_* 原子冲突）；每个用例 setUp 重置假原子的类级状态。

覆盖：
① 线性 DAG 执行顺序与 node_states 迁移 / 事件 node_id 注入
② 策略重试（blocked ×2 → swap do-原子 ×2 → 第 3 次 ok）
③ 策略用尽 result 透传、节点 failed、任务 ok=False
④ circuit_breaker 达阈值抛 AbortTask、节点 aborted、任务 ok=False
⑤ 容器 parallel=2 引擎接管：共享队列认领枯竭、#w0/#w1 节点键、共享 limit
⑥ stop_event 协作式停止、剩余节点 pending、返回 stopped
⑦ edges 乱序时 Kahn 拓扑序正确
附：串行容器委托（body 注入 params）、run() finally 资源兜底、DAG 校验失败
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from app.services.flow.base import Atom, AtomResult
from app.services.flow.dag import DagValidationError
from app.services.flow.executor import AbortTask, ExecutorContext, FlowExecutor
from app.services.flow.registry import register


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------

class FakeRT:
    """假 TaskRuntime：记录 set_progress 调用与 emit 事件。"""

    def __init__(self):
        self.progress_calls = []   # list[dict] set_progress kwargs
        self.events = []           # list[dict] {level, message, data}
        self.fake_stop = False
        self.track_calls = 0
        self._lock = threading.Lock()

    def set_progress(self, **fields):
        with self._lock:
            self.progress_calls.append(fields)

    def emit(self, level, message, data=None):
        with self._lock:
            self.events.append({"level": level, "message": message,
                                "data": data or {}})

    def stop_requested(self):
        return self.fake_stop

    def track(self, n=1):
        with self._lock:
            self.track_calls += n

    def per_minute(self):
        return 2.5


class FakeDB:
    """假 ShopDB（db_factory 注入；记录 close）。"""
    instances = []
    pending_n = 0       # count_pending 返回值（类级，便于测试设置）

    def __init__(self):
        self.closed = False
        FakeDB.instances.append(self)

    def close(self):
        self.closed = True

    def count_pending(self):
        return type(self).pending_n


class FakePoolClient:
    instances = []

    def __init__(self, task_id=None, api_base=None):
        self.task_id = task_id
        self.released = 0
        FakePoolClient.instances.append(self)

    def release(self):
        self.released += 1
        return 0


class FakeBrowser:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


# ---- 假原子（test_exec_ 前缀）----

@register
class _RecAtom(Atom):
    """记录执行顺序（ctx._node_id 由引擎绑定）并发一条事件。"""
    name = "test_exec_rec"
    title = "测试·记录"
    calls = []
    pool_seen = []

    def run(self, ctx, params):
        nid = getattr(ctx, "_node_id", None)
        type(self).calls.append(nid)
        type(self).pool_seen.append(ctx.resources.get("pool_client"))
        ctx.emit("info", f"rec {nid}")
        ctx.report_progress({"step": nid})
        return AtomResult(outcome="ok")


@register
class _RefAtom(Atom):
    """记录收到的 params（验证 ${name} 引用解析后的实值与类型）。"""
    name = "test_exec_ref"
    title = "测试·引用参数"
    received = []
    flags = []
    param_spec = {"type": "object",
                  "properties": {"value": {"type": "integer", "default": 0},
                                 "flag": {"type": "boolean", "default": True}},
                  "required": []}

    def run(self, ctx, params):
        type(self).received.append(params.get("value"))
        type(self).flags.append(params.get("flag"))
        return AtomResult(outcome="ok")


@register
class _FlakyAtom(Atom):
    """前 blocked_times 次返回 blocked，之后 ok。"""
    name = "test_exec_flaky"
    title = "测试·前 N 次风控"
    calls = 0
    blocked_times = 2

    def run(self, ctx, params):
        type(self).calls += 1
        if type(self).calls <= type(self).blocked_times:
            return AtomResult(outcome="blocked", detail="模拟风控")
        return AtomResult(outcome="ok")


@register
class _BlockedAtom(Atom):
    """恒 blocked。"""
    name = "test_exec_blocked"
    title = "测试·恒风控"
    calls = 0

    def run(self, ctx, params):
        type(self).calls += 1
        return AtomResult(outcome="blocked", detail="模拟风控")


@register
class _SeqAtom(Atom):
    """按类级 outcomes 队列依次返回 outcome（用尽后恒 ok）。"""
    name = "test_exec_seq"
    title = "测试·结果序列"
    outcomes = []
    calls = 0

    def run(self, ctx, params):
        cls = type(self)
        cls.calls += 1
        outcome = cls.outcomes.pop(0) if cls.outcomes else "ok"
        return AtomResult(outcome=outcome, detail=f"seq {outcome}")


@register
class _SwapAtom(Atom):
    """补救原子（记录调用次数与收到的 params）。"""
    name = "test_exec_swap"
    title = "测试·换 IP"
    calls = 0
    params_seen = []

    def run(self, ctx, params):
        type(self).calls += 1
        type(self).params_seen.append(dict(params or {}))
        return AtomResult(outcome="ok")


@register
class _ClaimAtom(Atom):
    """从共享队列认领（可选 barrier 强制两 worker 都进入后再放行）。"""
    name = "test_exec_claim"
    title = "测试·认领"
    queue = []
    lock = threading.Lock()
    barrier = None          # threading.Barrier(2) 时启用
    barrier_passed = set()  # 已通过 barrier 的 worker_id

    def run(self, ctx, params):
        cls = type(self)
        wid = ctx.worker_id
        if cls.barrier is not None and wid not in cls.barrier_passed:
            cls.barrier_passed.add(wid)
            cls.barrier.wait(timeout=5)
        # 微小停顿让另一 worker 获得调度（共享队列认领的公平性）
        time.sleep(0.02)
        with cls.lock:
            shop = cls.queue.pop(0) if cls.queue else None
        if shop is None:
            ctx.vars["shops"] = []
            return AtomResult(outcome="empty", detail="队列枯竭")
        ctx.vars["shops"] = [shop]
        return AtomResult(outcome="ok")


@register
class _WorkAtom(Atom):
    """消费 ctx.vars["shops"]，记录 (worker_id, shops)。"""
    name = "test_exec_work"
    title = "测试·干活"
    calls = []
    lock = threading.Lock()

    def run(self, ctx, params):
        time.sleep(0.02)  # 让出调度，避免单 worker 独占队列
        with type(self).lock:
            type(self).calls.append(
                (ctx.worker_id, list(ctx.vars.get("shops") or [])))
        ctx.emit("info", f"work w{ctx.worker_id}")
        return AtomResult(outcome="ok")


@register
class _ContainerAtom(Atom):
    """容器标记原子：parallel>1 时引擎接管（run 不被调用）；
    parallel<=1 时验证串行委托（记录收到的 params）。"""
    name = "test_exec_container"
    title = "测试·容器"
    is_container = True
    delegated = []
    param_spec = {
        "type": "object",
        "properties": {
            "num": {"type": "integer", "default": 10},
            "batch_rest": {"type": "number", "default": 900},
            "max_batches": {"type": "integer", "default": 0},
            "limit": {"type": "integer", "default": 0},
            "parallel": {"type": "integer", "default": 1},
            "headed": {"type": "boolean", "default": False},
            "body": {"type": "array", "default": []},
        },
        "required": [],
    }

    def run(self, ctx, params):
        type(self).delegated.append(dict(params))
        return AtomResult(outcome="ok", detail="串行委托执行")


@register
class _StopAtom(Atom):
    """把 rt 置为停止（模拟外部停止请求）。"""
    name = "test_exec_stop"
    title = "测试·触发停止"

    def run(self, ctx, params):
        ctx.rt.fake_stop = True
        return AtomResult(outcome="ok")


@register
class _SetupResAtom(Atom):
    """往主 ctx.resources 挂假资源（验证 run() finally 兜底释放）。"""
    name = "test_exec_setup_res"
    title = "测试·挂资源"
    pool = None
    browser = None
    page = None
    identity = None

    def run(self, ctx, params):
        cls = type(self)
        if cls.pool is not None:
            ctx.resources["pool_client"] = cls.pool
        if cls.browser is not None:
            ctx.resources["browser"] = cls.browser
        if cls.page is not None:
            ctx.resources["page"] = cls.page
        if cls.identity is not None:
            ctx.resources["identity"] = cls.identity
        return AtomResult(outcome="ok")


class _FakePage:
    """假 playwright Page：仅带 context 属性（cookie 回写路径用）。"""

    def __init__(self):
        self.context = object()


@register
class _BoomAtom(Atom):
    """抛未捕获异常。"""
    name = "test_exec_boom"
    title = "测试·异常"

    def run(self, ctx, params):
        raise RuntimeError("模拟原子崩溃")


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def _dag(nodes, edges=None, resources=None, run_inputs=None):
    dag = {"version": 1, "nodes": nodes}
    if edges:
        dag["edges"] = edges
    if resources:
        dag["resources"] = resources
    if run_inputs:
        dag["run_inputs"] = run_inputs
    return dag


def _run(dag, rt=None, **kw):
    rt = rt or FakeRT()
    kw.setdefault("db_factory", FakeDB)  # 默认隔离真实 SQLite
    ex = FlowExecutor(dag, rt, task_id=999, **kw)
    return ex, ex.run(), rt


class _Base(unittest.TestCase):
    def setUp(self):
        _RecAtom.calls = []
        _RecAtom.pool_seen = []
        _RefAtom.received = []
        _RefAtom.flags = []
        _FlakyAtom.calls = 0
        _FlakyAtom.blocked_times = 2
        _BlockedAtom.calls = 0
        _SeqAtom.outcomes = []
        _SeqAtom.calls = 0
        _SwapAtom.calls = 0
        _SwapAtom.params_seen = []
        _ClaimAtom.queue = []
        _ClaimAtom.barrier = None
        _ClaimAtom.barrier_passed = set()
        _WorkAtom.calls = []
        _ContainerAtom.delegated = []
        _SetupResAtom.pool = None
        _SetupResAtom.browser = None
        _SetupResAtom.page = None
        _SetupResAtom.identity = None
        FakeDB.instances = []
        FakeDB.pending_n = 0
        FakePoolClient.instances = []


# ----------------------------------------------------------------------
# ① 线性 DAG：顺序 / node_states 迁移 / 事件注入
# ----------------------------------------------------------------------

class TestLinearDag(_Base):
    def test_order_and_states(self):
        dag = _dag([{"id": "a", "atom": "test_exec_rec"},
                    {"id": "b", "atom": "test_exec_rec"},
                    {"id": "c", "atom": "test_exec_rec"}])
        ex, res, rt = _run(dag)
        self.assertEqual(res, {"ok": True})
        # 数组序执行
        self.assertEqual(_RecAtom.calls, ["a", "b", "c"])
        # node_states 迁移到 ok，且带 started_at/elapsed/progress
        states = ex.node_states_snapshot()
        for nid in ("a", "b", "c"):
            st = states[nid]
            self.assertEqual(st["status"], "ok")
            self.assertIsNotNone(st["started_at"])
            self.assertIsNotNone(st["elapsed"])
            self.assertEqual(st["progress"], {"step": nid})
        # set_progress 每次都带 nodes 键（merge 语义保留任务级字段）
        self.assertTrue(rt.progress_calls)
        for call in rt.progress_calls:
            self.assertIn("nodes", call)
        # 事件 data 自动注入 node_id（顶层无 worker_id）
        self.assertEqual([e["data"]["node_id"] for e in rt.events],
                         ["a", "b", "c"])
        self.assertNotIn("worker_id", rt.events[0]["data"])


# ----------------------------------------------------------------------
# ②③④ 策略拦截器
# ----------------------------------------------------------------------

class TestPolicy(_Base):
    def test_retry_then_ok(self):
        """blocked ×2 → swap ×2 → 第 3 次 ok，节点 ok。"""
        _FlakyAtom.blocked_times = 2
        dag = _dag([{"id": "n1", "atom": "test_exec_flaky",
                     "on_blocked": {"do": "test_exec_swap", "retry": 2}}])
        ex, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_FlakyAtom.calls, 3)
        self.assertEqual(_SwapAtom.calls, 2)
        self.assertEqual(ex.node_states_snapshot()["n1"]["status"], "ok")

    def test_policy_exhausted(self):
        """策略用尽：result 透传（detail 进 error），节点 failed。"""
        dag = _dag([{"id": "n1", "atom": "test_exec_blocked",
                     "on_blocked": {"do": "test_exec_swap", "retry": 1}}])
        ex, res, _ = _run(dag)
        self.assertFalse(res["ok"])
        self.assertIn("n1", res["error"])
        self.assertIn("模拟风控", res["error"])  # result.detail 透传
        self.assertEqual(_BlockedAtom.calls, 2)  # 1 次 + 重试 1 次
        self.assertEqual(_SwapAtom.calls, 1)
        self.assertEqual(ex.node_states_snapshot()["n1"]["status"], "failed")

    def test_circuit_breaker_aborts(self):
        """consecutive_fail 达阈值 → AbortTask，节点 aborted，ok=False。"""
        dag = _dag([{"id": "n1", "atom": "test_exec_blocked",
                     "on_blocked": {"do": "test_exec_swap", "retry": 5},
                     "circuit_breaker": {"consecutive_fail": 2,
                                         "action": "abort_task"}}])
        ex, res, _ = _run(dag)
        self.assertFalse(res["ok"])
        self.assertIn("熔断", res["error"])
        self.assertEqual(_BlockedAtom.calls, 2)  # cf 1→2 触发，不再重试
        self.assertEqual(_SwapAtom.calls, 1)
        self.assertEqual(ex.node_states_snapshot()["n1"]["status"], "aborted")

    def test_atom_exception_marks_failed(self):
        dag = _dag([{"id": "n1", "atom": "test_exec_boom"}])
        ex, res, _ = _run(dag)
        self.assertFalse(res["ok"])
        self.assertIn("模拟原子崩溃", res["error"])
        self.assertEqual(ex.node_states_snapshot()["n1"]["status"], "failed")


# ----------------------------------------------------------------------
# ⑤ 并行容器引擎接管
# ----------------------------------------------------------------------

def _parallel_dag(limit, num=10, queue_n=3, batch_rest=0.05):
    return _dag([{
        "id": "loop", "atom": "test_exec_container",
        "params": {"num": num, "batch_rest": batch_rest,
                   "max_batches": 0, "limit": limit, "parallel": 2},
        "body": [{"id": "claim", "atom": "test_exec_claim"},
                 {"id": "work", "atom": "test_exec_work"}],
    }])


class TestParallelContainer(_Base):
    def test_two_workers_shared_queue(self):
        """3 条数据认领枯竭：两 worker 都执行过、#w0/#w1 节点键齐全。"""
        _ClaimAtom.queue = [{"id": i} for i in range(3)]
        _ClaimAtom.barrier = threading.Barrier(2)  # 保证两 worker 都进入
        ex, res, rt = _run(_parallel_dag(limit=0), db_factory=FakeDB)
        self.assertEqual(res, {"ok": True})
        # 两个 worker 都执行过 work，合计 3 次（共享队列）
        self.assertEqual(len(_WorkAtom.calls), 3)
        self.assertEqual({c[0] for c in _WorkAtom.calls}, {0, 1})
        # node_states 含 worker 维度键
        states = ex.node_states_snapshot()
        for key in ("loop/claim#w0", "loop/work#w0",
                    "loop/claim#w1", "loop/work#w1"):
            self.assertIn(key, states)
        # 容器节点 ok，进度含共享配额汇总
        self.assertEqual(states["loop"]["status"], "ok")
        self.assertEqual(states["loop"]["progress"].get("fetched"), 3)
        # 事件带 worker_id
        wid_events = [e["data"].get("worker_id") for e in rt.events
                      if "worker_id" in e["data"]]
        self.assertTrue(wid_events)
        # 每 worker 一个 db + 主 ctx 一个 db，且 finally close
        # （contact_fetch L416-427 对齐）
        self.assertEqual(len(FakeDB.instances), 3)
        self.assertTrue(all(db.closed for db in FakeDB.instances))
        # 并行路径的任务级 progress：collected 最终 3、track 3 次
        tcalls = [c for c in rt.progress_calls if "collected" in c]
        self.assertTrue(tcalls)
        self.assertEqual(tcalls[-1]["collected"], 3)
        self.assertEqual(rt.track_calls, 3)

    def test_shared_limit(self):
        """limit=2 + num=2：批内配额共享，两个并发 worker 合计只处理 2 个。"""
        _ClaimAtom.queue = [{"id": i} for i in range(10)]
        ex, res, _ = _run(_parallel_dag(limit=2, num=2, batch_rest=0.05),
                          db_factory=FakeDB)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(len(_WorkAtom.calls), 2)

    def test_serial_container_takeover(self):
        """parallel=1：同样走引擎接管循环（原子的串行 run 不再被调用），
        node_states 含 `容器id/子id` 键（不带 #w 后缀）且状态正确迁移。"""
        _ClaimAtom.queue = [{"id": i} for i in range(3)]
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "work", "atom": "test_exec_work"}],
        }])
        ex, res, _ = _run(dag, db_factory=FakeDB)
        self.assertEqual(res, {"ok": True})
        # 原子的串行实现不再被委托调用
        self.assertEqual(_ContainerAtom.delegated, [])
        # body 子节点全部执行（worker_id 为 None：顶层语义）
        self.assertEqual(len(_WorkAtom.calls), 3)
        self.assertEqual({c[0] for c in _WorkAtom.calls}, {None})
        # node_states 含不带 #w 后缀的子节点键，状态迁移到 ok
        states = ex.node_states_snapshot()
        for key in ("loop/claim", "loop/work"):
            self.assertIn(key, states)
            self.assertEqual(states[key]["status"], "ok")
            self.assertIsNotNone(states[key]["started_at"])
            self.assertIsNotNone(states[key]["elapsed"])
        self.assertNotIn("loop/claim#w0", states)
        self.assertNotIn("loop/work#w0", states)
        self.assertEqual(states["loop"]["status"], "ok")
        self.assertEqual(states["loop"]["progress"].get("fetched"), 3)
        # 主 ctx 的 db 经工厂创建且收尾关闭
        self.assertEqual(len(FakeDB.instances), 1)
        self.assertTrue(FakeDB.instances[0].closed)

    def test_serial_container_policy_applies(self):
        """串行容器 body 内策略拦截器生效：blocked → do 原子被调用 → ok。"""
        _ClaimAtom.queue = [{"id": 1}]
        _FlakyAtom.blocked_times = 1
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "fetch", "atom": "test_exec_flaky",
                      "on_blocked": {"do": "test_exec_swap", "retry": 2}}],
        }])
        ex, res, _ = _run(dag, db_factory=FakeDB)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_FlakyAtom.calls, 2)   # blocked 1 次后重试成功
        self.assertEqual(_SwapAtom.calls, 1)
        states = ex.node_states_snapshot()
        self.assertEqual(states["loop/fetch"]["status"], "ok")

    def test_serial_container_circuit_breaker(self):
        """串行容器 body 内熔断生效：AbortTask → 容器 aborted、ok=False。"""
        _ClaimAtom.queue = [{"id": i} for i in range(10)]
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "fetch", "atom": "test_exec_blocked",
                      "circuit_breaker": {"consecutive_fail": 1,
                                          "action": "abort_task"}}],
        }])
        ex, res, _ = _run(dag, db_factory=FakeDB)
        self.assertFalse(res["ok"])
        self.assertIn("熔断", res["error"])
        states = ex.node_states_snapshot()
        self.assertEqual(states["loop/fetch"]["status"], "aborted")
        self.assertEqual(states["loop"]["status"], "aborted")

    def test_worker_abort_propagates(self):
        """body 内熔断：AbortTask 上抛，容器节点 aborted，ok=False。"""
        _ClaimAtom.queue = [{"id": i} for i in range(10)]
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 2},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "work", "atom": "test_exec_blocked",
                      "circuit_breaker": {"consecutive_fail": 1,
                                          "action": "abort_task"}}],
        }])
        ex, res, _ = _run(dag, db_factory=FakeDB)
        self.assertFalse(res["ok"])
        self.assertIn("熔断", res["error"])
        self.assertEqual(ex.node_states_snapshot()["loop"]["status"], "aborted")


# ----------------------------------------------------------------------
# ⑥ 协作式停止
# ----------------------------------------------------------------------

class TestStop(_Base):
    def test_stop_before_next_node(self):
        dag = _dag([{"id": "s", "atom": "test_exec_stop"},
                    {"id": "b", "atom": "test_exec_rec"}])
        ex, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True, "stopped": True})
        states = ex.node_states_snapshot()
        self.assertEqual(states["s"]["status"], "ok")
        self.assertEqual(states["b"]["status"], "pending")  # 剩余保持 pending
        self.assertEqual(_RecAtom.calls, [])  # 未执行


# ----------------------------------------------------------------------
# ⑦ 拓扑序
# ----------------------------------------------------------------------

class TestTopoOrder(_Base):
    def test_edges_shuffled(self):
        """数组序 [c, a, b] + edges a→b→c：执行序 a, b, c。"""
        dag = _dag([{"id": "c", "atom": "test_exec_rec"},
                    {"id": "a", "atom": "test_exec_rec"},
                    {"id": "b", "atom": "test_exec_rec"}],
                   edges=[["a", "b"], ["b", "c"]])
        _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_RecAtom.calls, ["a", "b", "c"])


# ----------------------------------------------------------------------
# 附加：资源兜底 / DAG 校验
# ----------------------------------------------------------------------

class TestMisc(_Base):
    def test_finally_releases_resources(self):
        _SetupResAtom.pool = FakePoolClient()
        _SetupResAtom.browser = FakeBrowser()
        dag = _dag([{"id": "s", "atom": "test_exec_setup_res"}])
        _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_SetupResAtom.pool.released, 1)
        self.assertTrue(_SetupResAtom.browser.closed)

    def test_finally_releases_on_failure(self):
        _SetupResAtom.pool = FakePoolClient()
        _SetupResAtom.browser = FakeBrowser()
        dag = _dag([{"id": "s", "atom": "test_exec_setup_res"},
                    {"id": "x", "atom": "test_exec_boom"}])
        _, res, _ = _run(dag)
        self.assertFalse(res["ok"])
        self.assertEqual(_SetupResAtom.pool.released, 1)
        self.assertTrue(_SetupResAtom.browser.closed)

    def test_invalid_dag_raises(self):
        dag = _dag([{"id": "x", "atom": "test_exec_no_such_atom"}])
        with self.assertRaises(DagValidationError):
            FlowExecutor(dag, FakeRT(), task_id=1)

    def test_abort_task_is_exception(self):
        self.assertTrue(issubclass(AbortTask, Exception))
        self.assertTrue(issubclass(ExecutorContext,
                                   __import__("app.services.flow.base",
                                              fromlist=["Context"]).Context))


# ----------------------------------------------------------------------
# 资源注入 / ${name} 参数引用 / Cookie 回写（P2 灰度缺陷修复）
# ----------------------------------------------------------------------

class TestResourcesAndRefs(_Base):
    def test_pool_client_injected_and_released(self):
        """resources:["channel"] → run() 创建 PoolClient 注入主 ctx，
        finally release 被调用（PoolClient 打桩，无真实 Redis/HTTP）。"""
        dag = _dag([{"id": "a", "atom": "test_exec_rec"}],
                   resources=["channel"])
        with mock.patch("app.services.flow.executor.PoolClient",
                        FakePoolClient):
            _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(len(FakePoolClient.instances), 1)
        pool = FakePoolClient.instances[0]
        self.assertEqual(pool.task_id, 999)       # 每任务一个实例
        self.assertIs(_RecAtom.pool_seen[0], pool)  # 节点执行时已注入
        self.assertEqual(pool.released, 1)          # finally 兜底释放

    def test_no_channel_resource_no_pool(self):
        """未声明 channel 资源时不创建 PoolClient。"""
        dag = _dag([{"id": "a", "atom": "test_exec_rec"}])
        with mock.patch("app.services.flow.executor.PoolClient",
                        FakePoolClient):
            _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(FakePoolClient.instances, [])
        self.assertIsNone(_RecAtom.pool_seen[0])

    def test_run_input_ref_injects_container_limit(self):
        """params.limit = "${limit}"：引用解析后注入配额门，按注入值停止；
        普通节点的引用值同样解析为实参值。"""
        _ClaimAtom.queue = [{"id": i} for i in range(10)]
        dag = _dag(
            [{"id": "probe", "atom": "test_exec_ref",
              "params": {"value": "${limit}"}},
             {"id": "loop", "atom": "test_exec_container",
              "params": {"num": 10, "batch_rest": 0.05,
                         "limit": "${limit}", "parallel": 1},
              "body": [{"id": "claim", "atom": "test_exec_claim"},
                       {"id": "work", "atom": "test_exec_work"}]}],
            run_inputs={"limit": {"type": "int", "default": 0}})
        ex, res, _ = _run(dag, run_inputs={"limit": 2})
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_RefAtom.received, [2])   # 普通节点引用解析
        self.assertEqual(len(_WorkAtom.calls), 2)  # 配额门按注入 limit 停止
        self.assertEqual(
            ex.node_states_snapshot()["loop"]["progress"].get("fetched"), 2)

    def test_unresolved_ref_marks_node_failed(self):
        """引用已声明但无默认值且未提供实参 → error 事件 + 节点 failed。"""
        dag = _dag([{"id": "r", "atom": "test_exec_ref",
                     "params": {"value": "${x}"}}],
                   run_inputs={"x": {"type": "int"}})  # 无 default
        ex, res, rt = _run(dag)  # 未提供实参
        self.assertFalse(res["ok"])
        self.assertIn("${x}", res["error"])
        states = ex.node_states_snapshot()
        self.assertEqual(states["r"]["status"], "failed")
        self.assertIn("${x}", states["r"]["detail"])
        err_events = [e for e in rt.events if e["level"] == "error"]
        self.assertTrue(err_events)
        self.assertEqual(err_events[0]["data"]["ref"], "x")
        self.assertEqual(err_events[0]["data"]["node_id"], "r")
        self.assertEqual(_RefAtom.received, [])  # 原子未被执行

    def test_cookies_saved_before_browser_close(self):
        """finally：browser 关闭前经 page.context 回写 Cookie（异常吞掉）。"""
        page = _FakePage()
        _SetupResAtom.browser = FakeBrowser()
        _SetupResAtom.page = page
        _SetupResAtom.identity = "9.9.9.9"
        dag = _dag([{"id": "s", "atom": "test_exec_setup_res"}])
        with mock.patch("app.services.crawl.browser.save_cookies") as save:
            _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        save.assert_called_once()
        args = save.call_args.args
        self.assertIs(args[0], FakeDB.instances[0])  # 主 ctx 的 db
        self.assertEqual(args[1], "9.9.9.9")         # identity
        self.assertIs(args[2], page.context)
        self.assertTrue(_SetupResAtom.browser.closed)  # 回写后仍关闭

    def test_cookie_save_failure_swallowed(self):
        """Cookie 回写抛异常不阻断收尾（browser 仍关闭、任务仍 ok）。"""
        _SetupResAtom.browser = FakeBrowser()
        _SetupResAtom.page = _FakePage()
        dag = _dag([{"id": "s", "atom": "test_exec_setup_res"}])
        with mock.patch("app.services.crawl.browser.save_cookies",
                        side_effect=RuntimeError("db locked")):
            _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertTrue(_SetupResAtom.browser.closed)

    def test_bool_ref_resolves_to_boolean(self):
        """"${proxy}" 实参 False：节点拿到的是布尔 False 而非字符串。"""
        dag = _dag([{"id": "r", "atom": "test_exec_ref",
                     "params": {"flag": "${proxy}"}}],
                   run_inputs={"proxy": {"type": "bool", "default": True}})
        _, res, _ = _run(dag, run_inputs={"proxy": False})
        self.assertEqual(res, {"ok": True})
        self.assertEqual(len(_RefAtom.flags), 1)
        self.assertIs(_RefAtom.flags[0], False)  # 布尔 False，不是 "false"
        # 缺省值路径：不提供实参时用 default True
        _RefAtom.flags = []
        _, res2, _ = _run(dag)
        self.assertEqual(res2, {"ok": True})
        self.assertIs(_RefAtom.flags[0], True)

    def test_policy_injects_attempt(self):
        """策略拦截器把 attempts[outcome] 以 _attempt 键注入补救原子参数。"""
        _FlakyAtom.blocked_times = 2
        dag = _dag([{"id": "n1", "atom": "test_exec_flaky",
                     "on_blocked": {"do": "test_exec_swap", "retry": 2}}])
        _, res, _ = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual([p.get("_attempt") for p in _SwapAtom.params_seen],
                         [1, 2])


# ----------------------------------------------------------------------
# 熔断计数语义（对齐 contact_fetch：只有抓取成功才清零）
# ----------------------------------------------------------------------

class TestCircuitBreakerSemantics(_Base):
    def test_unrelated_ok_node_does_not_reset_counter(self):
        """body [claim → rec(ok, 无 cb) → fetch(cb=3, 恒 blocked)]：
        无关节点 ok 不清零，连续 3 次 blocked 触发 AbortTask。"""
        _ClaimAtom.queue = [{"id": i} for i in range(10)]
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "pause", "atom": "test_exec_rec"},
                     {"id": "fetch", "atom": "test_exec_blocked",
                      "circuit_breaker": {"consecutive_fail": 3,
                                          "action": "abort_task"}}],
        }])
        ex, res, _ = _run(dag)
        self.assertFalse(res["ok"])
        self.assertIn("熔断", res["error"])
        # 恰为阈值 3：若 rec 的 ok 清零计数，blocked 会远超 3 次仍不熔断
        self.assertEqual(_BlockedAtom.calls, 3)
        self.assertEqual(_RecAtom.calls.count("pause"), 3)
        states = ex.node_states_snapshot()
        self.assertEqual(states["loop/fetch"]["status"], "aborted")
        self.assertEqual(states["loop"]["status"], "aborted")

    def test_cb_node_own_ok_resets_counter(self):
        """带 cb 节点自身 ok 才清零：blocked→ok→blocked→ok 不熔断。"""
        _ClaimAtom.queue = [{"id": i} for i in range(4)]
        _SeqAtom.outcomes = ["blocked", "ok", "blocked", "ok"]
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "fetch", "atom": "test_exec_seq",
                      "circuit_breaker": {"consecutive_fail": 2,
                                          "action": "abort_task"}}],
        }])
        ex, res, _ = _run(dag)
        # 阈值 2：若 ok 不清零，第 3 次调用（第 2 个 blocked）就会熔断
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_SeqAtom.calls, 4)
        self.assertEqual(ex.node_states_snapshot()["loop"]["status"], "ok")


# ----------------------------------------------------------------------
# 任务级 progress（collected/total/pending/per_minute）
# ----------------------------------------------------------------------

class TestTaskLevelProgress(_Base):
    def test_serial_container_reports_progress(self):
        """串行容器：进入时初始化 + 每次 fetched 增加上报任务级字段。"""
        _ClaimAtom.queue = [{"id": i} for i in range(3)]
        FakeDB.pending_n = 7
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05, "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "work", "atom": "test_exec_work"}],
        }])
        _, res, rt = _run(dag)
        self.assertEqual(res, {"ok": True})
        calls = [c for c in rt.progress_calls if "collected" in c]
        self.assertEqual(len(calls), 4)  # 入口 1 次 + 3 次处理
        self.assertEqual(calls[0]["collected"], 0)      # 进入时初始化
        self.assertEqual(calls[-1]["collected"], 3)
        self.assertIsNone(calls[-1]["total"])           # limit=0 → None
        self.assertEqual(calls[-1]["pending"], 7)       # db.count_pending
        self.assertEqual(calls[-1]["per_minute"], 2.5)
        self.assertEqual(rt.track_calls, 3)             # 每次处理 track(1)

    def test_total_reflects_limit(self):
        """limit 注入时 total 字段跟着走。"""
        _ClaimAtom.queue = [{"id": i} for i in range(10)]
        dag = _dag([{
            "id": "loop", "atom": "test_exec_container",
            "params": {"num": 10, "batch_rest": 0.05,
                       "limit": "${limit}", "parallel": 1},
            "body": [{"id": "claim", "atom": "test_exec_claim"},
                     {"id": "work", "atom": "test_exec_work"}]}],
            run_inputs={"limit": {"type": "int", "default": 0}})
        _, res, rt = _run(dag, run_inputs={"limit": 2})
        self.assertEqual(res, {"ok": True})
        calls = [c for c in rt.progress_calls if "collected" in c]
        self.assertEqual(calls[0]["total"], 2)
        self.assertEqual(calls[-1]["collected"], 2)
        self.assertEqual(calls[-1]["total"], 2)

    def test_no_container_no_task_progress(self):
        """顶层无容器的 DAG：不产生任务级 progress 调用（行为不变）。"""
        dag = _dag([{"id": "a", "atom": "test_exec_rec"}])
        _, res, rt = _run(dag)
        self.assertEqual(res, {"ok": True})
        self.assertEqual([c for c in rt.progress_calls if "collected" in c],
                         [])
        self.assertEqual(rt.track_calls, 0)


if __name__ == "__main__":
    unittest.main()
