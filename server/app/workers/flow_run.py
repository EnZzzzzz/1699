# -*- coding: utf-8 -*-
"""flow 任务通用入口（docs/flow-architecture.md §5.1 执行模型顶层）。

run_flow(task_id) 把 FlowExecutor 接到真实任务链路：
  读 Task → 取 DAG（params_json._dag_snapshot 快照优先，缺省按 flow_id
  现查 flows 表）→ set_status("running") + 心跳 → FlowExecutor 执行 →
  结果映射终态（done / stopped / failed）→ finally rt.close()。

状态/事件/进度全部复用 TaskRuntime（节点级看板数据在 progress_json.nodes，
由引擎自行上报）。本入口不感知通道/浏览器资源——资源由 DAG 内的原子
（acquire_channel / launch_browser / for_each_shop 容器）经 ctx 管理，
引擎 run() finally 兜底释放。
"""
from __future__ import annotations

import json

from loguru import logger

from ..db import SessionLocal
from ..models import Flow, Task
from ..services.flow.dag import DagValidationError
from ..services.flow.executor import FlowExecutor
from ..services.task_runtime import TaskRuntime
from .celery_app import celery_app


def _resolve_dag(params: dict, flow_id: int | None):
    """返回 (dag, flow_name, error)。

    快照优先（防模板后改影响历史任务，§6）；快照缺失/非 dict 时按 flow_id
    现查 flows 表回退（模板被删则报错，无法执行）。
    """
    dag = params.get("_dag_snapshot")
    flow_name = None
    if flow_id is not None:
        with SessionLocal() as db:
            flow = db.get(Flow, flow_id)
        if flow is not None:
            flow_name = flow.name
            if not isinstance(dag, dict):
                dag = flow.dag
                logger.info("task flow_id={} 无 _dag_snapshot，回退现查模板 "
                            "dag_json", flow_id)
    if not isinstance(dag, dict):
        return None, flow_name, (
            "params_json 缺少 _dag_snapshot，且流水线模板 "
            f"{flow_id} 不存在，无法执行")
    return dag, flow_name, None


def run_flow_task(task_id: int, celery_id: str | None = None) -> dict:
    """执行 type=flow 任务。返回 {"ok": ...} 结果 dict（同 contact_fetch 惯例）。"""
    rt = TaskRuntime(task_id)
    try:
        with SessionLocal() as db:
            t = db.get(Task, task_id)
            if t is None:
                return {"ok": False, "error": f"task {task_id} 不存在"}
            params = json.loads(t.params_json or "{}")
            flow_id = t.flow_id
            if celery_id:
                t.celery_id = celery_id
                db.commit()

        dag, flow_name, err = _resolve_dag(params, flow_id)
        if err is not None:
            rt.set_status("failed", error=err)
            return {"ok": False, "error": err}

        rt.set_status("running", celery_id=celery_id)
        rt.start_heartbeat()
        n_nodes = len(dag.get("nodes") or [])
        label = flow_name or (f"flow#{flow_id}" if flow_id else "（无模板）")
        rt.emit("info", f"流水线任务启动：{label}（{n_nodes} 个顶层节点）",
                {"flow_id": flow_id, "flow_name": flow_name,
                 "nodes": n_nodes})
        logger.info("task {} 流水线任务启动：{}（{} 个顶层节点）",
                    task_id, label, n_nodes)

        try:
            executor = FlowExecutor(dag=dag, rt=rt, task_id=task_id,
                                    run_inputs=params.get("run_inputs"))
        except DagValidationError as e:
            err = f"DAG 校验失败：{e}"
            rt.emit("error", err, {"errors": e.errors})
            rt.set_status("failed", error=err)
            return {"ok": False, "error": err}

        result = executor.run()

        # ---- 终态映射 ----
        if result.get("stopped") or rt.stop_requested():
            rt.emit("warning", "流水线任务已停止")
            rt.set_status("stopped")
            return {"ok": True, "stopped": True}
        if result.get("ok"):
            rt.set_status("done")
            return {"ok": True}
        err = result.get("error") or "未知错误"
        rt.set_status("failed", error=err)
        return {"ok": False, "error": err}
    except Exception as e:  # noqa: BLE001 - 顶层兜底，任务绝不悬在 running
        logger.exception("task {} 流水线任务异常: {}", task_id, e)
        rt.set_status("failed", error=str(e))
        return {"ok": False, "error": str(e)}
    finally:
        rt.close()


@celery_app.task(name="crawl.flow_run", bind=True)
def flow_run_task_entry(self, task_id: int) -> dict:
    """celery 薄封装（对齐 contact_fetch_task 的 bind 模式）。"""
    return run_flow_task(task_id, celery_id=self.request.id)
