# -*- coding: utf-8 -*-
"""run_flow_task 单元测试（stdlib unittest）。

隔离手段（无真实 Celery worker / Redis / 真实库 .cache/1688.db）：
- tempfile sqlite + Base.metadata.create_all 建真 Task/Flow/TaskEvent 行；
- mock.patch 替换两处 SessionLocal（flow_run 读任务/模板、TaskRuntime
  写状态/进度/事件/停止轮询）；
- TaskRuntime 的 Redis 接缝打桩：heartbeat / clear_heartbeat / _publish；
- 假原子 test_fr_ 前缀注册（registry 全局，与其他测试文件不冲突）。

覆盖：快照执行成功→done；stop_requested→stopped；执行器 error→failed；
坏 DAG→failed 带校验信息；task 不存在→error；快照缺失回退 flows 表。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config as app_config
from app.db import Base
from app.models import Flow, Task, TaskEvent
from app.services import task_runtime as tr_mod
from app.services.flow.base import Atom, AtomResult
from app.services.flow.registry import register
from app.workers import flow_run


# ---- 假原子（test_fr_ 前缀）----

@register
class _FrOkAtom(Atom):
    name = "test_fr_ok"
    title = "测试·flow_run 恒成功"
    calls = []

    def run(self, ctx, params):
        type(self).calls.append(getattr(ctx, "_node_id", None))
        ctx.report_progress({"done": True})
        return AtomResult(outcome="ok")


@register
class _FrBlockedAtom(Atom):
    name = "test_fr_blocked"
    title = "测试·flow_run 恒风控"

    def run(self, ctx, params):
        return AtomResult(outcome="blocked", detail="模拟风控")


class _FakeShopDB:
    """executor 默认 db_factory 的打桩（隔离真实 .cache/1688.db）。"""
    def close(self):
        pass


GOOD_DAG = {
    "version": 1,
    "nodes": [{"id": "a", "atom": "test_fr_ok"},
              {"id": "b", "atom": "test_fr_ok"}],
}

BAD_DAG = {
    "version": 1,
    "nodes": [{"id": "x", "atom": "test_fr_no_such_atom"}],
}

FAIL_DAG = {
    "version": 1,
    "nodes": [{"id": "n1", "atom": "test_fr_blocked"}],
}


class FlowRunTestBase(unittest.TestCase):
    """每个用例一份独立 tempfile sqlite；DB/Redis 接缝全部打桩。"""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        self.addCleanup(os.unlink, self.db_path)
        engine = create_engine(f"sqlite:///{self.db_path}",
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.TestingSession = sessionmaker(bind=engine, autoflush=False,
                                           autocommit=False)
        _FrOkAtom.calls = []

        # ---- 打桩：SessionLocal ×2 + Redis 心跳/发布 ----
        self._stack = ExitStack()
        self.addCleanup(self._stack.close)
        for target in ("app.workers.flow_run.SessionLocal",
                       "app.services.task_runtime.SessionLocal"):
            self._stack.enter_context(mock.patch(target, self.TestingSession))
        self._stack.enter_context(
            mock.patch.object(tr_mod, "heartbeat", lambda *a, **k: None))
        self._stack.enter_context(
            mock.patch.object(tr_mod, "clear_heartbeat", lambda *a, **k: None))
        self._stack.enter_context(
            mock.patch.object(tr_mod.TaskRuntime, "_publish",
                              lambda self, payload: None))
        # executor 默认 db_factory=ShopDB 直连真实库，打桩隔离
        self._stack.enter_context(
            mock.patch("app.services.flow.executor.ShopDB", _FakeShopDB))

    # ---- helpers -----------------------------------------------------------
    def insert_task(self, params: dict, flow_id=None, stop=False) -> int:
        db = self.TestingSession()
        try:
            t = Task(type="flow", flow_id=flow_id,
                     params_json=json.dumps(params, ensure_ascii=False),
                     status="pending",
                     progress_json=json.dumps({"collected": 0},
                                              ensure_ascii=False),
                     stop_requested=1 if stop else 0,
                     created_at=app_config.now_str())
            db.add(t)
            db.commit()
            return t.id
        finally:
            db.close()

    def insert_flow(self, name="测试流水线", dag=None) -> int:
        db = self.TestingSession()
        try:
            f = Flow(name=name, dag_json=json.dumps(dag or GOOD_DAG,
                                                    ensure_ascii=False),
                     builtin=0, created_at=app_config.now_str(),
                     updated_at=app_config.now_str())
            db.add(f)
            db.commit()
            return f.id
        finally:
            db.close()

    def get_task(self, task_id) -> dict:
        db = self.TestingSession()
        try:
            return db.get(Task, task_id).to_dict()
        finally:
            db.close()

    def get_events(self, task_id) -> list[dict]:
        db = self.TestingSession()
        try:
            rows = (db.query(TaskEvent)
                    .filter(TaskEvent.task_id == task_id)
                    .order_by(TaskEvent.id).all())
            return [e.to_dict() for e in rows]
        finally:
            db.close()


class TestRunFlow(FlowRunTestBase):
    def test_snapshot_ok_done(self):
        """快照执行成功 → done；节点按序执行；启动事件带 flow 名称/节点数。"""
        fid = self.insert_flow(name="联系人提取·测试")
        tid = self.insert_task({"flow_id": fid, "run_inputs": {},
                                "_dag_snapshot": GOOD_DAG}, flow_id=fid)
        res = flow_run.run_flow_task(tid, celery_id="celery-123")
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_FrOkAtom.calls, ["a", "b"])
        t = self.get_task(tid)
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["celery_id"], "celery-123")
        self.assertIsNotNone(t["started_at"])
        self.assertIsNotNone(t["finished_at"])
        # 节点看板数据落在 progress.nodes
        nodes = t["progress"]["nodes"]
        self.assertEqual(nodes["a"]["status"], "ok")
        self.assertEqual(nodes["b"]["progress"], {"done": True})
        events = self.get_events(tid)
        start = next(e for e in events if "流水线任务启动" in e["message"])
        self.assertIn("联系人提取·测试", start["message"])
        self.assertEqual(start["data"]["nodes"], 2)
        self.assertTrue(any(e["level"] == "success" and "任务完成" in e["message"]
                            for e in events))

    def test_stop_requested_stopped(self):
        """stop_requested=1：执行器在节点边界停止 → stopped + warning 事件。"""
        tid = self.insert_task({"flow_id": None, "run_inputs": {},
                                "_dag_snapshot": GOOD_DAG}, stop=True)
        res = flow_run.run_flow_task(tid)
        self.assertEqual(res, {"ok": True, "stopped": True})
        self.assertEqual(_FrOkAtom.calls, [])  # 未进入任何节点
        t = self.get_task(tid)
        self.assertEqual(t["status"], "stopped")
        events = self.get_events(tid)
        self.assertTrue(any(e["level"] == "warning"
                            and "已停止" in e["message"] for e in events))

    def test_executor_error_failed(self):
        """执行器返回 {"ok": False} → failed，error 透传进 tasks.error。"""
        tid = self.insert_task({"flow_id": None, "run_inputs": {},
                                "_dag_snapshot": FAIL_DAG})
        res = flow_run.run_flow_task(tid)
        self.assertFalse(res["ok"])
        t = self.get_task(tid)
        self.assertEqual(t["status"], "failed")
        self.assertIn("n1", t["error"])
        self.assertIn("模拟风控", t["error"])

    def test_bad_dag_failed(self):
        """快照 DAG 校验失败 → failed，error 带校验信息。"""
        tid = self.insert_task({"flow_id": None, "run_inputs": {},
                                "_dag_snapshot": BAD_DAG})
        res = flow_run.run_flow_task(tid)
        self.assertFalse(res["ok"])
        self.assertIn("DAG 校验失败", res["error"])
        t = self.get_task(tid)
        self.assertEqual(t["status"], "failed")
        self.assertIn("未知原子", t["error"])
        events = self.get_events(tid)
        ev = next(e for e in events if e["level"] == "error"
                  and "DAG 校验失败" in e["message"])
        self.assertTrue(ev["data"]["errors"])

    def test_task_not_found(self):
        res = flow_run.run_flow_task(99999)
        self.assertFalse(res["ok"])
        self.assertIn("不存在", res["error"])

    def test_fallback_to_flow_table(self):
        """无 _dag_snapshot：按 flow_id 现查 flows 表执行（回退路径）。"""
        fid = self.insert_flow()
        tid = self.insert_task({"flow_id": fid, "run_inputs": {}}, flow_id=fid)
        res = flow_run.run_flow_task(tid)
        self.assertEqual(res, {"ok": True})
        self.assertEqual(_FrOkAtom.calls, ["a", "b"])
        self.assertEqual(self.get_task(tid)["status"], "done")

    def test_no_snapshot_no_flow_failed(self):
        """既无快照也无模板 → failed（不悬在 running）。"""
        tid = self.insert_task({"flow_id": 4242, "run_inputs": {}},
                               flow_id=4242)
        res = flow_run.run_flow_task(tid)
        self.assertFalse(res["ok"])
        t = self.get_task(tid)
        self.assertEqual(t["status"], "failed")
        self.assertIn("_dag_snapshot", t["error"])


if __name__ == "__main__":
    unittest.main()
