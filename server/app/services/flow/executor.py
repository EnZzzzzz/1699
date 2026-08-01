# -*- coding: utf-8 -*-
"""
FlowExecutor：原子能力 + DAG 流水线的执行引擎（docs/flow-architecture.md §5）。

职责：
- 拓扑执行顶层 nodes（有 edges 按 Kahn 拓扑序，同级按数组序；无 edges 即数组序）
- 节点级状态上报：progress_json 增加 nodes 键（§5.4 / §7），node_key 规则
  顶层 = 节点 id；容器 body = `容器id/子id`；并行 worker 维度 = `容器id/子id#w0`
- 策略拦截器 run_with_policy（§5.2）：on_<outcome> 补救原子重试 +
  circuit_breaker 熔断（AbortTask）
- 容器节点：串行/并行统一走「引擎接管循环」（子节点状态上报 / 策略
  拦截器 / 熔断两条路径同样生效）；parallel > 1 起 N 个 worker 线程，
  共享配额锁算法移植自 server/app/workers/contact_fetch.py L149-184
  （ForEachShopAtom 的串行实现保留，仅供脱离引擎独立使用）
- 资源兜底：run() finally 释放 pool_client / 关闭浏览器（吞异常）
- 协作式停止：节点边界检查 stop_requested，容器 worker 共享 stop_event

测试隔离：db_factory 可注入假 ShopDB（默认真 ShopDB）；浏览器只在 DAG
resources 声明 "browser" 时启动，且经 pool_client.channel_proxy 取代理。
"""
from __future__ import annotations

import copy
import heapq
import random
import re
import threading
import time
from datetime import datetime

from loguru import logger

from . import registry
from .base import (
    AtomResult,
    Context,
    OUTCOME_BLOCKED,
    OUTCOME_EMPTY,
    OUTCOME_OK,
    OUTCOME_STOPPED,
)
from .dag import validate_or_raise
from ..crawl.shopdb import ShopDB
from ..pool_client import PoolClient

# 节点 params 顶层值的 run_inputs 引用语法："${name}"（v1 仅顶层值）
_PARAM_REF_RE = re.compile(r"^\$\{([A-Za-z_]\w*)\}$")


class AbortTask(Exception):
    """熔断中止：circuit_breaker 达到阈值时抛出，终止整个任务。"""


class ExecutorContext(Context):
    """引擎上下文（docs/flow-architecture.md §5.3 扩展）。

    - emit 自动注入 node_id / worker_id（引擎在 run_node 前绑定当前节点）
    - report_progress 除写自身 progress 外，同步进 node_states[key].progress
      并触发一次 nodes 快照上报
    """

    def __init__(self, *, executor: "FlowExecutor | None" = None, **kw) -> None:
        super().__init__(**kw)
        self._executor = executor
        self._node_key: str | None = None   # node_states 键（含 #w{i} 后缀）
        self._node_id: str | None = None    # 事件 data 用的节点 id

    def emit(self, level: str, message: str, data: dict | None = None) -> None:
        payload = dict(data or {})
        if self._node_id is not None:
            payload.setdefault("node_id", self._node_id)
        if self.worker_id is not None:
            payload.setdefault("worker_id", self.worker_id)
        super().emit(level, message, payload)

    def report_progress(self, data: dict) -> None:
        super().report_progress(data)
        ex = self._executor
        if ex is not None and self._node_key is not None:
            ex._on_node_progress(self._node_key, data)


class FlowExecutor:
    """DAG 执行引擎。用法：FlowExecutor(dag, rt, task_id, run_inputs).run()。"""

    def __init__(self, dag: dict, rt, task_id: int,
                 run_inputs: dict | None = None, *,
                 db_factory=None) -> None:
        # 执行前校验（§4 约束：结构/原子存在性/参数/策略键/熔断/无环）
        self.dag = dag
        self.warnings = validate_or_raise(dag)
        for w in self.warnings:
            logger.warning("task {} DAG 校验提示: {}", task_id, w)
        self.rt = rt
        self.task_id = task_id
        self.run_inputs = dict(run_inputs or {})
        # ${name} 引用的解析表：run() 中并入 dag.run_inputs 声明的默认值
        self._input_vars = dict(self.run_inputs)
        # db 工厂：并行 worker 每线程一个 ShopDB（sqlite 连接不可跨线程）；
        # 单测注入假工厂隔离真实 SQLite
        self._db_factory = db_factory or ShopDB
        self._main_db_owned = False
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._t0: dict[str, float] = {}  # running 计时器（不进快照）
        # node_states: {node_key: {status/started_at/elapsed/progress/detail}}
        self.node_states: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 节点状态上报（§5.4）
    # ------------------------------------------------------------------

    def node_states_snapshot(self) -> dict:
        """node_states 深拷贝（供 rt.set_progress(nodes=...) 与测试断言）。"""
        with self._state_lock:
            return copy.deepcopy(self.node_states)

    def _init_node_state(self, key: str) -> None:
        with self._state_lock:
            self.node_states.setdefault(key, {
                "status": "pending", "started_at": None,
                "elapsed": None, "progress": {},
            })

    def _set_node_state(self, key: str, status: str, **fields) -> None:
        """状态迁移并上报。status: pending/running/ok/failed/stopped/aborted。"""
        with self._state_lock:
            st = self.node_states.setdefault(key, {
                "status": "pending", "started_at": None,
                "elapsed": None, "progress": {},
            })
            if status == "running":
                # 计时器放独立 dict，避免泄漏进 progress_json 快照
                self._t0[key] = time.monotonic()
                st["started_at"] = datetime.now().isoformat(timespec="seconds")
                st["elapsed"] = None
            elif status in ("ok", "failed", "stopped", "aborted"):
                t0 = self._t0.pop(key, None)
                if t0 is not None:
                    st["elapsed"] = round(time.monotonic() - t0, 3)
            st["status"] = status
            for k, v in fields.items():
                if v is not None:
                    st[k] = v
        self._push_nodes()

    def _on_node_progress(self, key: str, data: dict) -> None:
        """原子 report_progress → 写进 node_states[key].progress 并上报。"""
        with self._state_lock:
            st = self.node_states.setdefault(key, {
                "status": "running", "started_at": None,
                "elapsed": None, "progress": {},
            })
            st.setdefault("progress", {}).update(data)
        self._push_nodes()

    def _push_nodes(self) -> None:
        """刷新 progress_json 的 nodes 键（set_progress 是 merge 语义，
        任务级字段 collected/pending 等保留）。rt 缺失或写库失败不阻塞。"""
        rt = self.rt
        if rt is None:
            return
        try:
            rt.set_progress(nodes=self.node_states_snapshot())
        except Exception as e:  # noqa: BLE001 - 上报绝不阻塞主流程
            logger.warning("task {} 节点状态上报失败（忽略）: {}", self.task_id, e)

    # ------------------------------------------------------------------
    # 拓扑排序（Kahn；同级按数组序，无 edges 退化为数组序）
    # ------------------------------------------------------------------

    @staticmethod
    def _topo_order(nodes: list[dict], edges: list) -> list[dict]:
        ids = [n["id"] for n in nodes]
        pos = {nid: i for i, nid in enumerate(ids)}
        by_id = {n["id"]: n for n in nodes}
        indeg = {nid: 0 for nid in ids}
        adj: dict[str, list[str]] = {nid: [] for nid in ids}
        for e in edges:
            u, v = e[0], e[1]
            adj[u].append(v)
            indeg[v] += 1
        heap = [(pos[nid], nid) for nid in ids if indeg[nid] == 0]
        heapq.heapify(heap)
        order: list[dict] = []
        while heap:
            _, u = heapq.heappop(heap)
            order.append(by_id[u])
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    heapq.heappush(heap, (pos[v], v))
        # validate_or_raise 已保证无环且端点存在，order 必含全部节点
        return order

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """执行 DAG。返回 {"ok": True} / {"ok": True, "stopped": True} /
        {"ok": False, "error": str}。"""
        registry.load_all()
        nodes = self.dag.get("nodes") or []
        order = self._topo_order(nodes, self.dag.get("edges") or [])

        # run_inputs：模板声明的默认值 + 实参覆盖，进 ctx.vars 黑板；
        # 同时作为 ${name} 参数引用的解析表
        vars0 = {}
        for k, spec in (self.dag.get("run_inputs") or {}).items():
            if isinstance(spec, dict) and "default" in spec:
                vars0[k] = spec["default"]
        vars0.update(self.run_inputs)
        self._input_vars = vars0

        ctx = ExecutorContext(executor=self, task_id=self.task_id, rt=self.rt,
                              vars=vars0, stop_event=self._stop_event)
        # 主上下文 db：顶层/串行容器 body 原子（launch_browser / claim_shops
        # 等）经 ctx.resources["db"] 取用；并行 worker 另有每线程实例
        self._main_db_owned = False
        if "db" not in ctx.resources:
            ctx.resources["db"] = self._db_factory()
            self._main_db_owned = True
        # 通道池客户端：DAG 声明 channel 资源时创建（每任务一个实例，对齐
        # run_contact_fetch；worker 线程共享），acquire/swap 原子经
        # ctx.resources["pool_client"] 取用；finally release 兜底
        if "channel" in (self.dag.get("resources") or []) \
                and "pool_client" not in ctx.resources:
            ctx.resources["pool_client"] = PoolClient(self.task_id)
        for n in order:
            self._init_node_state(n["id"])
        self._push_nodes()

        logger.info("task {} FlowExecutor 启动，共 {} 个顶层节点（并行容器由"
                    "引擎接管 worker 线程）", self.task_id, len(order))
        try:
            for node in order:
                if ctx.stop_requested():
                    logger.info("task {} 收到停止请求，剩余节点保持 pending",
                                self.task_id)
                    return {"ok": True, "stopped": True}
                result = self.run_node(node, ctx, node["id"])
                if result.outcome == OUTCOME_STOPPED:
                    return {"ok": True, "stopped": True}
                if result.outcome not in (OUTCOME_OK, OUTCOME_EMPTY):
                    # 策略用尽后的失败结果：节点 failed，任务失败。
                    # empty 不算失败（对齐 contact_fetch "没有待处理店铺"
                    # 正常结束的语义），任务继续。
                    return {"ok": False,
                            "error": f"节点 {node['id']} 失败："
                                     f"{result.detail or result.outcome}"}
            return {"ok": True}
        except AbortTask as e:
            # 熔断：当前节点已在 run_node 标记 aborted
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 - 原子未捕获异常兜底
            logger.exception("task {} FlowExecutor 异常: {}", self.task_id, e)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            self._release_main_resources(ctx)

    def _release_main_resources(self, ctx: ExecutorContext) -> None:
        """资源兜底：通道回池 + 关浏览器（吞异常，对齐 §2 资源生命周期）。"""
        res = ctx.resources
        pool_client = res.get("pool_client")
        if pool_client is not None:
            try:
                pool_client.release()
                logger.info("task {} 通道已释放回池", self.task_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("task {} 通道释放失败（忽略）: {}", self.task_id, e)
        browser = res.get("browser")
        if browser is not None:
            # 关闭前先回写 Cookie（对齐 contact_fetch.py L417-421 worker
            # finally：page.context 可取才回写，异常仅告警不阻断）
            page = res.get("page")
            bctx = getattr(page, "context", None) if page is not None else None
            db = res.get("db")
            if bctx is not None and db is not None:
                try:
                    from ..crawl import browser as browser_mod  # 延迟导入
                    browser_mod.save_cookies(
                        db, res.get("identity") or "direct", bctx)
                except Exception as e:  # noqa: BLE001
                    logger.warning("task {} 退出前 Cookie 回写失败（忽略）: {}",
                                   self.task_id, e)
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        db = res.get("db")
        if self._main_db_owned and db is not None and hasattr(db, "close"):
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 节点执行
    # ------------------------------------------------------------------

    @staticmethod
    def _bind_node(ctx: ExecutorContext, key: str, node_id: str) -> None:
        """run_node 前绑定当前节点（emit/report_progress 路由依据）。"""
        ctx._node_key = key
        ctx._node_id = node_id

    def _resolve_params(self, params: dict | None, node_id: str,
                        ctx: ExecutorContext) -> tuple[dict | None, str | None]:
        """节点 params 顶层值的 ${name} 引用解析（值 = run_inputs 默认值 +
        实参，见 run() 的 _input_vars）。引用未声明/未提供的 name → error
        事件 + 返回 (None, 错误描述)，调用方把节点标记 failed。"""
        out = {}
        for k, v in (params or {}).items():
            m = _PARAM_REF_RE.match(v) if isinstance(v, str) else None
            if m is None:
                out[k] = v
                continue
            name = m.group(1)
            if name not in self._input_vars:
                detail = (f"节点 {node_id} 参数 {k} 引用的 run_inputs 变量 "
                          f"'${{{name}}}' 未声明或未提供实参（且无默认值）")
                ctx.emit("error", detail, {"param": k, "ref": name})
                logger.warning("task {} {}", self.task_id, detail)
                return None, detail
            out[k] = self._input_vars[name]
        return out, None

    def run_node(self, node: dict, ctx: ExecutorContext, key: str) -> AtomResult:
        """执行单个节点（含状态迁移与事件上报），返回 AtomResult。

        容器节点（atom.is_container 且带 body）走 _run_container；
        普通节点走策略拦截器 run_with_policy。AbortTask / 未捕获异常
        标记 aborted / failed 后继续上抛。
        """
        atom = registry.get(node["atom"])
        is_container = bool(getattr(atom, "is_container", False)) \
            and node.get("body") is not None
        self._bind_node(ctx, key, node["id"])
        self._set_node_state(key, "running")
        logger.info("task {} 节点 {} ({}) 开始", self.task_id, key, node["atom"])
        params, ref_err = self._resolve_params(node.get("params"),
                                               node["id"], ctx)
        if ref_err is not None:
            self._set_node_state(key, "failed", detail=ref_err)
            return AtomResult(outcome="param_error", detail=ref_err)
        node = {**node, "params": params}
        try:
            if is_container:
                result = self._run_container(node, ctx, key, atom)
            else:
                result = self.run_with_policy(node, ctx)
        except AbortTask as e:
            self._set_node_state(key, "aborted", detail=str(e))
            raise
        except Exception as e:  # noqa: BLE001
            self._set_node_state(key, "failed",
                                 detail=f"{type(e).__name__}: {e}")
            raise
        if result.outcome in (OUTCOME_OK, OUTCOME_EMPTY):
            # empty = 成功执行但无有效数据（如认领枯竭），节点记 ok
            self._set_node_state(key, "ok", detail=result.detail or None)
            logger.info("task {} 节点 {} 完成{}", self.task_id, key,
                        f"（{result.outcome}）" if not result.ok else "")
        elif result.outcome == OUTCOME_STOPPED:
            self._set_node_state(key, "stopped", detail=result.detail or None)
        else:
            self._set_node_state(key, "failed",
                                 detail=result.detail or result.outcome)
            logger.warning("task {} 节点 {} 失败: {} ({})", self.task_id, key,
                           result.detail, result.outcome)
        return result

    # ------------------------------------------------------------------
    # 策略拦截器（§5.2）
    # ------------------------------------------------------------------

    def run_with_policy(self, node: dict, ctx: ExecutorContext) -> AtomResult:
        """包一层重试/熔断策略执行原子。

        - outcome == "ok"：仅当节点**自身携带 circuit_breaker 配置**时
          清零 consecutive_fail 并返回（对齐 contact_fetch.py L231-235：
          只有抓取成功才清零；无 cb 的无关节点——如 claim/pause——
          不碰该计数，否则 fetch 的 blocked 累计会被下一迭代 claim ok
          冲掉，熔断永不触发）
        - outcome == "stopped"：直接向上透传
        - outcome == "blocked"：consecutive_fail += 1（累计语义对齐
          contact_fetch.py L283-294）；达到
          circuit_breaker.consecutive_fail 阈值抛 AbortTask
          （action 仅支持 abort_task，dag.py 校验保证）
        - 有 on_<outcome> 策略且该 outcome 尝试次数 < retry：执行补救
          原子 policy["do"] 后 continue
        - 策略用尽：把 result 交还调用方（节点标记 failed）
        """
        atom = registry.get(node["atom"])
        params = node.get("params") or {}
        attempts: dict[str, int] = {}
        cb = node.get("circuit_breaker")
        while True:
            result = atom.run(ctx, params)
            outcome = result.outcome
            if outcome == OUTCOME_OK:
                if cb and ctx.consecutive_fail:
                    ctx.consecutive_fail = 0
                return result
            if outcome == OUTCOME_STOPPED:
                return result
            if outcome == OUTCOME_BLOCKED:
                ctx.consecutive_fail += 1
            if cb:
                threshold = int(cb.get("consecutive_fail") or 0)
                if threshold and ctx.consecutive_fail >= threshold:
                    msg = (f"节点 {node.get('id')} 连续失败 "
                           f"{ctx.consecutive_fail} 次，触发熔断，"
                           "中止整个任务")
                    ctx.emit("error", msg,
                             {"consecutive_fail": ctx.consecutive_fail})
                    logger.error("task {} {}", self.task_id, msg)
                    raise AbortTask(msg)
            policy = node.get(f"on_{outcome}")
            retry = int((policy or {}).get("retry") or 0)
            if policy is not None and attempts.get(outcome, 0) < retry:
                attempts[outcome] = attempts.get(outcome, 0) + 1
                do_name = policy.get("do")
                ctx.emit("warning",
                         f"节点 {node.get('id')} 结果 {outcome}"
                         f"（{result.detail}），执行补救原子 {do_name}"
                         f"（第 {attempts[outcome]}/{retry} 次）",
                         {"outcome": outcome, "retry": attempts[outcome],
                          "do": do_name})
                # _attempt 注入补救原子参数（1 起）：供其计算退避时长
                # （如直连模式 swap_ip 的 min(60*attempt, 300)）
                do_params = dict(policy.get("params") or {})
                do_params.setdefault("_attempt", attempts[outcome])
                registry.get(do_name).run(ctx, do_params)
                continue
            return result

    # ------------------------------------------------------------------
    # 容器节点
    # ------------------------------------------------------------------

    def _run_container(self, node: dict, ctx: ExecutorContext, key: str,
                       atom) -> AtomResult:
        """容器分发：串行/并行统一走「引擎接管循环」（_container_loop），
        子节点状态上报 / 策略拦截器 / 熔断在两条路径同样生效。

        - parallel <= 1：当前线程内联执行（父 ctx，node_key 不带 #w 后缀，
          对齐设计文档 §7；浏览器/db 沿用顶层节点已 acquire 的资源）
        - parallel > 1：N 个 worker 线程（独立子 ctx，node_key 带 #w{i}）
        ForEachShopAtom 的串行实现保留，仅供脱离引擎独立使用。
        """
        params = dict(node.get("params") or {})
        params["body"] = list(node.get("body") or [])
        parallel = params.get("parallel")
        parallel = 1 if parallel is None else int(parallel)
        if parallel <= 1:
            logger.info("task {} 容器 {} 串行执行（引擎接管循环，单上下文）",
                        self.task_id, key)
            return self._run_container_serial(node, ctx, key, params)
        logger.info("task {} 容器 {} 引擎接管：parallel={} 起 worker 线程",
                    self.task_id, key, parallel)
        return self._run_container_parallel(node, ctx, key, params, parallel)

    @staticmethod
    def _quota_params(params: dict) -> tuple[int, float, int, int]:
        num = max(1, int(params.get("num") or 10))
        batch_rest = float(params.get("batch_rest") or 900)
        max_batches = int(params.get("max_batches") or 0)
        limit = int(params.get("limit") or 0)
        return num, batch_rest, max_batches, limit

    def _run_container_serial(self, node: dict, ctx: ExecutorContext,
                              key: str, params: dict) -> AtomResult:
        """串行容器：父 ctx 内联跑接管循环（node_key = `容器id/子id`，
        不带 #w 后缀，对齐 §7）。资源沿用顶层节点已 acquire 的
        channel/browser/db，不新建 worker 上下文。"""
        quota = {"done": 0, "batch": 1, "rest_until": 0.0, "fetched": 0}
        stats = {"ok": 0, "empty": 0, "failed": 0}
        lock = threading.Lock()
        limit = self._quota_params(params)[3]
        # 容器进入时初始化任务级 progress（对齐 contact_fetch.py L491-492）
        self._report_task_progress(ctx, 0, limit)
        # run_node 会把 ctx 绑定到子节点键，循环结束（含异常）后恢复容器绑定
        prev_key, prev_id = ctx._node_key, ctx._node_id
        try:
            self._container_loop(node, ctx, key, params, params["body"],
                                 quota, stats, lock, "")
        finally:
            self._bind_node(ctx, prev_key, prev_id)
        data = {"batches": quota["batch"], "fetched": quota["fetched"],
                **stats}
        if ctx.stop_requested():
            return AtomResult(outcome=OUTCOME_STOPPED,
                              detail="任务被停止", data=data)
        return AtomResult(
            detail=f"循环结束：ok={stats['ok']} empty={stats['empty']} "
                   f"failed={stats['failed']}", data=data)

    def _container_loop(self, node: dict, wctx: ExecutorContext, key: str,
                        params: dict, body: list[dict], quota: dict,
                        stats: dict, lock: threading.Lock,
                        key_suffix: str) -> None:
        """容器循环体（串行内联 / 并行 worker 共用）：配额门 → 依次经策略
        拦截器执行 body 子节点（node_key = `容器id/子id` + key_suffix）→
        按迭代结果累计配额。AbortTask / 未捕获异常上抛给调用方处置。"""
        num, batch_rest, max_batches, limit = self._quota_params(params)
        tag = f"{key}{key_suffix}"
        while not wctx.stop_requested():
            # ---- 批次配额（contact_fetch.py L151-184 移植）----
            if not self._quota_acquire(wctx, quota, lock, num, batch_rest,
                                       max_batches, limit, wctx.worker_id):
                break
            # ---- 依次经策略拦截器执行 body 子节点 ----
            interrupted: AtomResult | None = None
            for child in body:
                if wctx.stop_requested():
                    break
                ckey = f"{key}/{child['id']}{key_suffix}"
                res = self.run_node(child, wctx, ckey)
                if res.outcome != OUTCOME_OK:
                    interrupted = res
                    break
            if wctx.stop_requested():
                break
            if interrupted is None:
                with lock:
                    stats["ok"] += 1
                    quota["fetched"] += 1
                    fetched = quota["fetched"]
                self._track_processed(wctx, fetched, limit)
            elif interrupted.outcome == OUTCOME_STOPPED:
                break
            elif interrupted.outcome == OUTCOME_EMPTY:
                if not wctx.vars.get("shops"):
                    # 认领枯竭（对齐 contact_fetch.py L186-189）
                    logger.info("task {} {} 认领枯竭，退出循环",
                                self.task_id, tag)
                    break
                with lock:
                    stats["empty"] += 1
                    quota["fetched"] += 1
                    fetched = quota["fetched"]
                self._track_processed(wctx, fetched, limit)
            else:
                with lock:
                    stats["failed"] += 1
            self._on_node_progress(key, self._quota_progress(quota, stats,
                                                             lock))

    # ------------------------------------------------------------------
    # 任务级 progress（对齐 contact_fetch.py L358-365 / L491-492 口径）
    # ------------------------------------------------------------------

    def _track_processed(self, wctx: ExecutorContext, fetched: int,
                         limit: int) -> None:
        """一次成功处理（ok / empty，与 quota["fetched"] 口径一致）后：
        rt.track(1) 驱动 per_minute 滑窗 + set_progress 任务级字段。"""
        rt = self.rt
        if rt is None:
            return
        track = getattr(rt, "track", None)
        if callable(track):
            try:
                track(1)
            except Exception as e:  # noqa: BLE001
                logger.warning("task {} rt.track 失败（忽略）: {}",
                               self.task_id, e)
        self._report_task_progress(wctx, fetched, limit)

    def _report_task_progress(self, wctx: ExecutorContext, fetched: int,
                              limit: int) -> None:
        """set_progress(collected/total/pending/per_minute)。

        pending 用当前上下文 db 的 count_pending（串行 = 主 ctx db；
        并行 = 该 worker 自己的 db 连接——ShopDB 的 sqlite3 连接不可
        跨线程，主 db 不能从 worker 线程调用）；db/rt 缺失或调用失败
        均不阻断主流程。
        """
        rt = self.rt
        if rt is None:
            return
        fields: dict = {"collected": fetched, "total": limit or None}
        db = wctx.resources.get("db")
        count_pending = getattr(db, "count_pending", None)
        if callable(count_pending):
            try:
                fields["pending"] = count_pending()
            except Exception as e:  # noqa: BLE001
                logger.warning("task {} count_pending 失败（忽略）: {}",
                               self.task_id, e)
        per_minute = getattr(rt, "per_minute", None)
        if callable(per_minute):
            try:
                fields["per_minute"] = per_minute()
            except Exception:  # noqa: BLE001
                pass
        try:
            rt.set_progress(**fields)
        except Exception as e:  # noqa: BLE001
            logger.warning("task {} 任务级进度上报失败（忽略）: {}",
                           self.task_id, e)

    def _run_container_parallel(self, node: dict, parent_ctx: ExecutorContext,
                                key: str, params: dict,
                                parallel: int) -> AtomResult:
        """并行容器：N 个 worker 线程各自循环 body 子图，共享配额锁。

        配额状态/锁语义移植 contact_fetch.py L149-184；任一 worker 抛
        AbortTask 或异常 → stop_event.set()，等所有线程 join(timeout=90)
        后抛出首个错误。
        """
        body = params["body"]
        num, batch_rest, max_batches, limit = self._quota_params(params)
        # state 字段对齐 contact_fetch.py L487 批次配额状态
        quota = {"done": 0, "batch": 1, "rest_until": 0.0, "fetched": 0}
        stats = {"ok": 0, "empty": 0, "failed": 0}
        lock = threading.Lock()
        errors: list[BaseException] = []
        # 容器进入时初始化任务级 progress（对齐 contact_fetch.py L491-492；
        # 主 ctx db 在主线程调用，worker 线程内用各自 db）
        self._report_task_progress(parent_ctx, 0, limit)
        threads = []
        for i in range(parallel):
            t = threading.Thread(
                target=self._parallel_worker,
                args=(node, parent_ctx, key, params, body, i,
                      quota, stats, lock, errors),
                daemon=True, name=f"flow-{key}-w{i}")
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
        alive = [t.name for t in threads if t.is_alive()]
        if alive:
            logger.warning("task {} 容器 {} join 超时仍有 worker 未退出: {}",
                           self.task_id, key, alive)
        if errors:
            raise errors[0]
        data = {"batches": quota["batch"], "fetched": quota["fetched"],
                "parallel": parallel, **stats}
        if parent_ctx.stop_requested():
            return AtomResult(outcome=OUTCOME_STOPPED,
                              detail="任务被停止", data=data)
        return AtomResult(
            detail=f"并行循环结束：ok={stats['ok']} empty={stats['empty']} "
                   f"failed={stats['failed']}", data=data)

    def _parallel_worker(self, node: dict, parent_ctx: ExecutorContext,
                         key: str, params: dict, body: list[dict],
                         worker_id: int, quota: dict, stats: dict,
                         lock: threading.Lock,
                         errors: list[BaseException]) -> None:
        """单个 worker：独立 resources（pool_client 共享、db 每线程新建、
        浏览器键初始空）与 vars，共享 rt / stop_event / task_id / 配额锁。"""
        tag = f"{key}#w{worker_id}"
        wvars = dict(parent_ctx.vars)
        wvars.pop("shops", None)  # 认领结果每迭代由 claim 重写，不继承
        wctx = ExecutorContext(
            executor=self, task_id=self.task_id, rt=self.rt,
            resources={
                "pool_client": parent_ctx.resources.get("pool_client"),
                "db": self._db_factory(),
                "channel": None, "browser": None, "page": None,
                "identity": None, "req_proxies": None,
            },
            vars=wvars, worker_id=worker_id, stop_event=self._stop_event)
        self._bind_node(wctx, key, node.get("id"))
        try:
            if "browser" in (self.dag.get("resources") or []):
                self._launch_worker_browser(node, parent_ctx, wctx,
                                            params, worker_id)
            self._container_loop(node, wctx, key, params, body, quota,
                                 stats, lock, f"#w{worker_id}")
        except AbortTask as e:
            logger.error("task {} {} 熔断: {}", self.task_id, tag, e)
            errors.append(e)
            self._stop_event.set()
        except Exception as e:  # noqa: BLE001
            logger.exception("task {} {} worker 异常退出: {}",
                             self.task_id, tag, e)
            wctx.emit("error", f"worker{worker_id} 异常退出：{e}")
            errors.append(e)
            self._stop_event.set()
        finally:
            self._release_worker_resources(wctx)

    @staticmethod
    def _quota_progress(quota: dict, stats: dict,
                        lock: threading.Lock) -> dict:
        with lock:
            return {"batch": quota["batch"], "done": quota["done"],
                    "fetched": quota["fetched"], **stats}

    def _quota_acquire(self, ctx: ExecutorContext, quota: dict,
                       lock: threading.Lock, num: int, batch_rest: float,
                       max_batches: int, limit: int,
                       worker_id: int | None) -> bool:
        """共享配额门（contact_fetch.py L151-184）：limit 判停 / 批内 num /
        max_batches 判停 / 批间 batch_rest ±10% 休息 + warning 事件 /
        休息结束 done 清零 batch 递增。返回 False = 该上下文结束循环。
        worker_id 为 None 表示串行容器（日志不带 w 前缀）。"""
        wtag = f"w{worker_id} " if worker_id is not None else ""
        while True:
            with lock:
                if limit and quota["fetched"] >= limit:
                    wait_for = -1.0
                elif quota["done"] < num:
                    quota["done"] += 1
                    wait_for = 0.0
                elif max_batches and quota["batch"] >= max_batches:
                    wait_for = -1.0
                else:
                    now = time.time()
                    if quota["rest_until"] <= now:
                        quota["rest_until"] = now + random.uniform(
                            batch_rest * 0.9, batch_rest * 1.1)
                    wait_for = quota["rest_until"] - now
                batch, seconds = quota["batch"], round(wait_for)
            if wait_for == 0.0:
                return True
            if wait_for < 0:
                return False
            logger.info("task {} {}第 {} 批采满，休息 {:.1f} 分钟（防风控）",
                        self.task_id, wtag, batch, wait_for / 60)
            ctx.emit("warning",
                     f"第 {batch} 批已采满 {num} 个，批间休息 "
                     f"{wait_for / 60:.1f} 分钟（防风控）",
                     {"batch": batch, "seconds": seconds})
            if ctx.wait(wait_for) or ctx.stop_requested():
                return False
            with lock:
                if quota["done"] >= num:
                    quota["done"] = 0
                    quota["batch"] += 1

    # ------------------------------------------------------------------
    # worker 浏览器生命周期（contact_fetch.py L140-147 启动 / L416-427 清理）
    # ------------------------------------------------------------------

    def _launch_worker_browser(self, node: dict, parent_ctx: ExecutorContext,
                               wctx: ExecutorContext, params: dict,
                               worker_id: int) -> None:
        """DAG resources 声明 browser 时，为 worker 独立 launch：
        通道取父 ctx.vars["channels"][i % len]，代理经
        pool_client.channel_proxy；headed 取容器 params（默认 False）。"""
        from ..crawl import browser as browser_mod  # 延迟导入，隔离重依赖

        pool_client = parent_ctx.resources.get("pool_client")
        channels = parent_ctx.vars.get("channels") or []
        channel = channels[worker_id % len(channels)] if channels else None
        server, auth = (None, None)
        if channel is not None and pool_client is not None:
            server, auth = pool_client.channel_proxy(channel)
        headed = bool(params.get("headed", False))
        browser, page, identity, req_proxies, _ = browser_mod.launch_browser(
            wctx.resources["db"], headless=not headed,
            proxy_server=server, proxy_auth=auth)
        wctx.resources.update({
            "channel": channel, "browser": browser, "page": page,
            "identity": identity, "req_proxies": req_proxies,
        })
        logger.info("task {} {} worker{} 浏览器就绪 (identity={})",
                    self.task_id, node.get("id"), worker_id, identity)
        wctx.emit("info",
                  f"worker{worker_id} 浏览器就绪（出口 IP: {identity}）",
                  {"identity": identity})

    @staticmethod
    def _release_worker_resources(wctx: ExecutorContext) -> None:
        """worker 收尾（contact_fetch.py L416-427）：save_cookies →
        browser.close → db.close，全部吞异常。"""
        from ..crawl import browser as browser_mod  # 延迟导入

        res = wctx.resources
        db = res.get("db")
        page = res.get("page")
        browser = res.get("browser")
        identity = res.get("identity") or "direct"
        bctx = getattr(page, "context", None) if page is not None else None
        if bctx is not None and db is not None:
            try:
                browser_mod.save_cookies(db, identity, bctx)
            except Exception:  # noqa: BLE001
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        if db is not None and hasattr(db, "close"):
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass
