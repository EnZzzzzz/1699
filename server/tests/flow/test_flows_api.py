# -*- coding: utf-8 -*-
"""flows API / type=flow 任务创建 单元测试（docs/flow-architecture.md §7）。

隔离要求：严禁触碰真实库 .cache/1688.db。
- 测试内建独立 FastAPI app，只 include flows/tasks 路由（不 import app.main，
  避免 lifespan 副作用：DB 迁移、PoolManager、探测定时器）。
- app.dependency_overrides[get_db] 覆盖为 tempfile 路径的独立 sqlite
  （Base.metadata.create_all 建表）。
- celery 派发用 monkeypatch 隔离（send_task / inspect_workers）。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config as app_config
from app.api import flows as flows_api
from app.api import tasks as tasks_api
from app.api import workers as workers_api
from app.db import Base, get_db
from app.models import Flow, Task
from app.services.flow import builtin
from app.services.flow.dag import validate_dag
from app.workers import celery_app as celery_mod

GOOD_DAG = {
    "version": 1,
    "resources": ["channel", "browser"],
    "run_inputs": {
        "limit": {"type": "int", "default": 0, "label": "最多抓取"},
    },
    "nodes": [
        {"id": "wait", "atom": "sleep", "params": {"min": 0, "max": 0}},
        {"id": "acquire", "atom": "acquire_channel",
         "params": {"n": 1, "proxy": True}},
    ],
    "edges": [["wait", "acquire"]],
}

BAD_DAG = {
    "version": 1,
    "nodes": [{"id": "x", "atom": "no_such_atom"}],
}


class FlowsApiTestBase(unittest.TestCase):
    """独立 FastAPI app + 临时 sqlite，每个用例一份干净库。"""

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

        def override_get_db():
            db = self.TestingSession()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.include_router(flows_api.router)
        app.include_router(tasks_api.router)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    # ---- helpers -----------------------------------------------------------
    def create_flow(self, name="测试流水线", dag=None):
        resp = self.client.post("/api/flows",
                                json={"name": name, "dag": dag or GOOD_DAG})
        assert resp.status_code == 201, resp.text
        return resp.json()

    def seed_builtin(self):
        db = self.TestingSession()
        try:
            n = builtin.seed_builtin_flows(db)
        finally:
            db.close()
        return n

    def insert_task(self, flow_id=None):
        db = self.TestingSession()
        try:
            t = Task(type="flow", flow_id=flow_id,
                     params_json=json.dumps({}), status="pending",
                     created_at=app_config.now_str())
            db.add(t)
            db.commit()
            return t.id
        finally:
            db.close()


class ValidateEndpointTest(FlowsApiTestBase):
    def test_validate_good_dag(self):
        resp = self.client.post("/api/flows/validate", json={"dag": GOOD_DAG})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["errors"], [])
        self.assertIsInstance(body["warnings"], list)

    def test_validate_bad_dag(self):
        resp = self.client.post("/api/flows/validate", json={"dag": BAD_DAG})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["errors"])
        self.assertTrue(any("未知原子" in e for e in body["errors"]))

    # ---- ${name} 引用语法校验 ----

    def test_validate_declared_ref_ok(self):
        dag = {"version": 1,
               "run_inputs": {"limit": {"type": "int", "default": 0}},
               "nodes": [{"id": "s", "atom": "sleep",
                          "params": {"min": "${limit}", "max": 0}}]}
        body = self.client.post("/api/flows/validate",
                                json={"dag": dag}).json()
        self.assertEqual(body["errors"], [])
        self.assertTrue(body["ok"])

    def test_validate_undeclared_ref_error(self):
        dag = {"version": 1,
               "nodes": [{"id": "s", "atom": "sleep",
                          "params": {"min": "${bogus}", "max": 0}}]}
        body = self.client.post("/api/flows/validate",
                                json={"dag": dag}).json()
        self.assertFalse(body["ok"])
        self.assertTrue(any("未声明" in e and "bogus" in e
                            for e in body["errors"]))

    def test_validate_ref_type_mismatch_warning(self):
        """run_inputs 声明 str、param_spec 要 integer：不阻断，给 warning。"""
        dag = {"version": 1,
               "run_inputs": {"limit": {"type": "str", "default": "0"}},
               "nodes": [{"id": "s", "atom": "sleep",
                          "params": {"min": "${limit}", "max": 0}}]}
        body = self.client.post("/api/flows/validate",
                                json={"dag": dag}).json()
        self.assertEqual(body["errors"], [])
        self.assertTrue(any("不一致" in w for w in body["warnings"]))


class FlowCrudTest(FlowsApiTestBase):
    def test_create_invalid_dag_400(self):
        resp = self.client.post("/api/flows",
                                json={"name": "坏模板", "dag": BAD_DAG})
        self.assertEqual(resp.status_code, 400)
        detail = resp.json()["detail"]
        self.assertIn("errors", detail)
        self.assertIn("warnings", detail)
        self.assertTrue(detail["errors"])

    def test_create_valid_201_with_warnings(self):
        body = self.create_flow()
        self.assertIn("id", body)
        self.assertIn("warnings", body)
        self.assertEqual(body["dag"]["version"], 1)
        self.assertFalse(body["builtin"])

    def test_list_excludes_dag(self):
        self.create_flow()
        resp = self.client.get("/api/flows")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertEqual(len(items), 1)
        self.assertNotIn("dag", items[0])
        for key in ("id", "name", "description", "builtin", "updated_at"):
            self.assertIn(key, items[0])

    def test_get_detail_includes_dag(self):
        created = self.create_flow()
        resp = self.client.get(f"/api/flows/{created['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["dag"]["nodes"][0]["id"], "wait")

    def test_get_404(self):
        self.assertEqual(self.client.get("/api/flows/999").status_code, 404)

    def test_update_and_revalidate(self):
        created = self.create_flow()
        resp = self.client.put(f"/api/flows/{created['id']}",
                               json={"name": "改名", "dag": GOOD_DAG})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "改名")
        # dag 变更加校验：非法 dag 拒绝
        resp = self.client.put(f"/api/flows/{created['id']}",
                               json={"dag": BAD_DAG})
        self.assertEqual(resp.status_code, 400)

    def test_duplicate(self):
        created = self.create_flow(name="原模板")
        resp = self.client.post(f"/api/flows/{created['id']}/duplicate")
        self.assertEqual(resp.status_code, 201)
        dup = resp.json()
        self.assertEqual(dup["name"], "原模板（副本）")
        self.assertFalse(dup["builtin"])
        self.assertEqual(dup["dag"], GOOD_DAG)
        self.assertEqual(self.client.get("/api/flows").json().__len__(), 2)

    def test_delete_unreferenced(self):
        created = self.create_flow()
        resp = self.client.delete(f"/api/flows/{created['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get("/api/flows").json(), [])

    def test_delete_referenced_409(self):
        created = self.create_flow()
        self.insert_task(flow_id=created["id"])
        resp = self.client.delete(f"/api/flows/{created['id']}")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("1 个任务引用", resp.json()["detail"])
        # 模板仍在
        self.assertEqual(self.client.get("/api/flows").json().__len__(), 1)


class BuiltinFlowTest(FlowsApiTestBase):
    def test_seed_idempotent(self):
        self.assertEqual(self.seed_builtin(), 2)
        self.assertEqual(self.seed_builtin(), 0)  # 幂等
        items = self.client.get("/api/flows").json()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i["builtin"] for i in items))

    def test_seed_updates_outdated_template(self):
        """代码侧 DAG 修订后再次 seed：库中模板被更新且 id/created_at 不变。"""
        self.assertEqual(self.seed_builtin(), 2)
        db = self.TestingSession()
        try:
            flow = db.query(Flow).filter(
                Flow.name == "联系人提取·标准").first()
            old_id, old_created = flow.id, flow.created_at
            # 模拟旧库残留的老版本模板（无 ${limit} 接线）
            flow.dag_json = json.dumps(
                {"version": 1, "nodes": [{"id": "a", "atom": "sleep"}]},
                ensure_ascii=False)
            db.commit()
        finally:
            db.close()
        # 再次 seed：不新增（返回 0），但模板内容被更新回代码版本
        self.assertEqual(self.seed_builtin(), 0)
        db = self.TestingSession()
        try:
            flow = db.get(Flow, old_id)
            self.assertEqual(flow.dag, builtin.build_contact_fetch_dag())
            self.assertEqual(flow.created_at, old_created)   # 保留
            self.assertNotEqual(flow.dag_json,
                                json.dumps({"version": 1,
                                            "nodes": [{"id": "a",
                                                       "atom": "sleep"}]}))
            # ${limit} 接线已同步进库
            loop = next(n for n in flow.dag["nodes"] if n["id"] == "loop")
            self.assertEqual(loop["params"]["limit"], "${limit}")
        finally:
            db.close()
        # 内容一致后再次 seed：完全幂等（不再写 updated_at）
        db = self.TestingSession()
        try:
            before = db.get(Flow, old_id).updated_at
        finally:
            db.close()
        self.assertEqual(self.seed_builtin(), 0)
        db = self.TestingSession()
        try:
            self.assertEqual(db.get(Flow, old_id).updated_at, before)
        finally:
            db.close()

    def test_builtin_dags_pass_validation(self):
        for builder in (builtin.build_contact_fetch_dag,
                        builtin.build_shop_crawl_dag):
            errors, _warnings = validate_dag(builder())
            self.assertEqual(errors, [], f"{builder.__name__}: {errors}")

    def test_builtin_proxy_headed_wired(self):
        """两个内置模板：proxy/headed 进 run_inputs 并以 ${} 接线到节点。"""
        for builder in (builtin.build_contact_fetch_dag,
                        builtin.build_shop_crawl_dag):
            dag = builder()
            ri = dag["run_inputs"]
            self.assertEqual(ri["proxy"]["type"], "bool")
            self.assertIs(ri["proxy"]["default"], True)
            self.assertEqual(ri["headed"]["type"], "bool")
            self.assertIs(ri["headed"]["default"], False)
            nodes = {n["id"]: n for n in dag["nodes"]}
            self.assertEqual(nodes["acquire"]["params"]["proxy"], "${proxy}")
            self.assertEqual(nodes["browser"]["params"]["headed"],
                             "${headed}")

    def test_seeded_template_has_proxy_headed_inputs(self):
        """seed 后库中模板带新 run_inputs（含 seed 更新逻辑同步路径）。"""
        self.seed_builtin()
        items = self.client.get("/api/flows").json()
        self.assertEqual(len(items), 2)
        for item in items:
            detail = self.client.get(f"/api/flows/{item['id']}").json()
            ri = detail["dag"]["run_inputs"]
            self.assertIn("proxy", ri)
            self.assertIn("headed", ri)

    def test_builtin_put_rejected(self):
        self.seed_builtin()
        items = self.client.get("/api/flows").json()
        fid = items[0]["id"]
        resp = self.client.put(f"/api/flows/{fid}", json={"name": "改"})
        self.assertEqual(resp.status_code, 400)

    def test_builtin_delete_rejected(self):
        self.seed_builtin()
        items = self.client.get("/api/flows").json()
        fid = items[0]["id"]
        resp = self.client.delete(f"/api/flows/{fid}")
        self.assertEqual(resp.status_code, 400)
        # 内置模板可以复制出可编辑副本
        resp = self.client.post(f"/api/flows/{fid}/duplicate")
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.json()["builtin"])


class AtomsEndpointTest(FlowsApiTestBase):
    def test_catalog_has_11_atoms(self):
        resp = self.client.get("/api/atoms")
        self.assertEqual(resp.status_code, 200)
        atoms = resp.json()
        names = {a["name"] for a in atoms}
        expected = {"sleep", "acquire_channel", "launch_browser",
                    "ensure_fresh_ip", "swap_ip", "human_pause",
                    "claim_shops", "fetch_contact", "crawl_category",
                    "confirm_human", "for_each_shop"}
        self.assertEqual(expected, names & expected)
        # 独立运行恰为 11 个；全量 discover 时 P0 的 test_atoms_crawl 会
        # 额外 @register 4 个测试原子（进程级 registry 污染），故用 >=
        self.assertGreaterEqual(len(atoms), 11)
        for a in atoms:
            self.assertIn("param_spec", a)
            self.assertIn("title", a)


class FlowTaskCreateTest(FlowsApiTestBase):
    """POST /api/tasks type=flow：run_inputs 校验 + DAG 快照 + 派发隔离。"""

    def _post_flow_task(self, flow_id, params):
        with mock.patch.object(celery_mod.celery_app, "send_task") as send, \
                mock.patch.object(workers_api, "inspect_workers",
                                  return_value={"online": True}):
            resp = self.client.post(
                "/api/tasks",
                json={"type": "flow", "flow_id": flow_id, "params": params})
        return resp, send

    def test_missing_flow_id_400(self):
        resp, _ = self._post_flow_task(None, {})
        self.assertEqual(resp.status_code, 400)

    def test_flow_not_found_404(self):
        resp, _ = self._post_flow_task(999, {})
        self.assertEqual(resp.status_code, 404)

    def test_unknown_run_input_key_400(self):
        fid = self.create_flow()["id"]
        resp, send = self._post_flow_task(fid, {"bogus": 1})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("bogus", resp.json()["detail"])
        send.assert_not_called()

    def test_run_input_type_error_400(self):
        fid = self.create_flow()["id"]
        resp, _ = self._post_flow_task(fid, {"limit": "abc"})
        self.assertEqual(resp.status_code, 400)

    def test_create_ok_defaults_snapshot_and_dispatch(self):
        fid = self.create_flow()["id"]
        resp, send = self._post_flow_task(fid, {})
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["flow_id"], fid)
        params = body["params"]
        # 缺省填 default
        self.assertEqual(params["run_inputs"], {"limit": 0})
        # DAG 快照入库（防模板后改影响历史任务）
        self.assertEqual(params["_dag_snapshot"], GOOD_DAG)
        self.assertEqual(params["flow_id"], fid)
        # 派发到 flow_run
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "crawl.flow_run")
        # 落库的 task.flow_id 一致
        db = self.TestingSession()
        try:
            t = db.get(Task, body["id"])
            self.assertEqual(t.flow_id, fid)
            stored = json.loads(t.params_json)
            self.assertIn("_dag_snapshot", stored)
        finally:
            db.close()

    def test_explicit_run_input_accepted(self):
        fid = self.create_flow()["id"]
        resp, _ = self._post_flow_task(fid, {"limit": 50})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["params"]["run_inputs"]["limit"], 50)

    def test_old_task_types_unaffected(self):
        """旧任务类型仍走原参数校验（回归保护）。"""
        with mock.patch.object(celery_mod.celery_app, "send_task"), \
                mock.patch.object(workers_api, "inspect_workers",
                                  return_value={"online": True}):
            resp = self.client.post(
                "/api/tasks",
                json={"type": "shop_crawl", "params": {"target": 10}})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertIsNone(resp.json()["flow_id"])
        self.assertEqual(resp.json()["params"], {"target": 10})


if __name__ == "__main__":
    unittest.main()
