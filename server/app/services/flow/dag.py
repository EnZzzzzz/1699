# -*- coding: utf-8 -*-
"""
DAG 校验（docs/flow-architecture.md §4 约束）。

validate_dag(dag) -> (errors, warnings)：
- errors   阻断保存/执行（结构非法、原子不存在、参数类型错、环等）
- warnings 不阻断但提示（如容器 body 无认领节点且未设上限，可能无限循环）

同时供 API 保存前校验（POST /api/flows/validate）与引擎执行前校验。
"""
from __future__ import annotations

from typing import Any

from . import registry

# 策略键允许的目标 outcome（与 base.py 常量对应）
_VALID_OUTCOMES = {"ok", "blocked", "net_error", "empty", "stopped", "timeout"}

# JSON Schema type → python 类型（宽松校验，bool 先于 int 判）
_TYPE_MAP = {
    "int": int, "integer": int, "float": (int, float), "number": (int, float),
    "str": str, "string": str, "bool": bool, "boolean": bool,
    "list": list, "array": list, "dict": dict, "object": dict,
}

# 容器原子（带 body 子图）；由 Atom 类属性 is_container 识别，此处仅注释
_CONTAINER_HINT = "容器原子"


class DagValidationError(ValueError):
    """DAG 校验失败（errors 列表语义见 validate_dag）。"""

    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("; ".join(errors))


def _check_params(atom_name: str, spec: dict, params: dict, path: str) -> list[str]:
    """按 atom.param_spec 宽松校验 params：未知字段拒绝、required 补齐、类型匹配。"""
    errors = []
    props = (spec or {}).get("properties", {})
    required = (spec or {}).get("required", [])
    params = params or {}
    for k in required:
        if k not in params:
            errors.append(f"{path}: 原子 {atom_name} 缺少必填参数 {k!r}")
    for k, v in params.items():
        if k not in props:
            errors.append(f"{path}: 原子 {atom_name} 不支持参数 {k!r}"
                          f"（允许: {sorted(props)}）")
            continue
        ptype = props[k].get("type")
        py_types = _TYPE_MAP.get(ptype)
        if py_types is None:
            continue  # 未知 schema 类型不校验
        # bool 是 int 子类，显式区分
        if py_types is bool and not isinstance(v, bool):
            errors.append(f"{path}: 参数 {k} 必须是布尔值")
        elif py_types is int and (isinstance(v, bool) or not isinstance(v, int)):
            errors.append(f"{path}: 参数 {k} 必须是整数")
        elif isinstance(py_types, tuple) and (isinstance(v, bool)
                                              or not isinstance(v, py_types)):
            errors.append(f"{path}: 参数 {k} 必须是数值")
        elif py_types in (str, list, dict) and not isinstance(v, py_types):
            errors.append(f"{path}: 参数 {k} 类型必须是 {ptype}")
    return errors


def _validate_node(node: dict, path: str, errors: list[str],
                   warnings: list[str]) -> str | None:
    """校验单个节点（递归容器 body），返回节点 id（无 id 返回 None）。"""
    if not isinstance(node, dict):
        errors.append(f"{path}: 节点必须是对象")
        return None
    nid = node.get("id")
    atom_name = node.get("atom")
    if not nid or not isinstance(nid, str):
        errors.append(f"{path}: 节点缺少字符串 id")
    if not atom_name or not isinstance(atom_name, str):
        errors.append(f"{path}: 节点缺少 atom 名称")
        return nid

    try:
        atom_cls = registry._REGISTRY.get(atom_name)
        if atom_cls is None:
            raise KeyError(atom_name)
    except KeyError:
        errors.append(f"{path}: 未知原子 {atom_name!r}"
                      f"（可用: {registry.names()}）")
        return nid

    # 参数校验
    errors.extend(_check_params(atom_name, atom_cls.param_spec,
                                node.get("params"), f"{path}({nid})"))

    # 策略键校验：on_<outcome>: {"do": <atom>, "retry": N}
    for key, val in node.items():
        if not key.startswith("on_"):
            continue
        outcome = key[3:]
        if outcome not in _VALID_OUTCOMES:
            errors.append(f"{path}({nid}): 未知策略键 {key!r}"
                          f"（outcome 允许: {sorted(_VALID_OUTCOMES)}）")
            continue
        if not isinstance(val, dict):
            errors.append(f"{path}({nid}): 策略 {key} 必须是对象")
            continue
        do_atom = val.get("do")
        if do_atom and do_atom not in registry._REGISTRY:
            errors.append(f"{path}({nid}): 策略 {key} 的 do 原子不存在: {do_atom!r}")
        retry = val.get("retry", 0)
        if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
            errors.append(f"{path}({nid}): 策略 {key} 的 retry 必须是非负整数")

    # 熔断配置校验
    cb = node.get("circuit_breaker")
    if cb is not None:
        if not isinstance(cb, dict):
            errors.append(f"{path}({nid}): circuit_breaker 必须是对象")
        else:
            cf = cb.get("consecutive_fail")
            if not isinstance(cf, int) or isinstance(cf, bool) or cf < 1:
                errors.append(f"{path}({nid}): circuit_breaker.consecutive_fail"
                              " 必须是正整数")
            if cb.get("action", "abort_task") != "abort_task":
                errors.append(f"{path}({nid}): circuit_breaker.action"
                              " 目前仅支持 'abort_task'")

    # 容器 body 递归校验
    body = node.get("body")
    if body is not None:
        if not getattr(atom_cls, "is_container", False):
            errors.append(f"{path}({nid}): 原子 {atom_name} 不是容器，"
                          "不允许带 body")
        elif not isinstance(body, list) or not body:
            errors.append(f"{path}({nid}): 容器 body 必须是非空数组")
        else:
            child_ids = set()
            for i, child in enumerate(body):
                cid = _validate_node(child, f"{path}({nid}).body[{i}]",
                                     errors, warnings)
                if cid:
                    if cid in child_ids:
                        errors.append(f"{path}({nid}): body 内节点 id 重复: {cid!r}")
                    child_ids.add(cid)
            # 容器安全提示：body 无认领类节点且未设上限 → 可能无限循环
            params = node.get("params") or {}
            has_bound = bool(params.get("limit")) or bool(params.get("max_batches"))
            claim_atoms = {"claim_shops"}
            has_claim = any(isinstance(c, dict) and c.get("atom") in claim_atoms
                            for c in body)
            if not has_claim and not has_bound:
                warnings.append(
                    f"{path}({nid}): 容器 body 无认领节点（如 claim_shops）且未设"
                    " limit/max_batches，队列不枯竭时可能无限循环")
    return nid


def _check_acyclic(node_ids: set[str], edges: list) -> list[str]:
    """Kahn 拓扑判环 + 边端点存在性校验。"""
    errors = []
    indeg: dict[str, int] = {n: 0 for n in node_ids}
    adj: dict[str, list[str]] = {n: [] for n in node_ids}
    for e in edges:
        if not (isinstance(e, (list, tuple)) and len(e) == 2):
            errors.append(f"edges: 边必须是 [from, to] 二元组，得到: {e!r}")
            continue
        u, v = e
        if u not in node_ids or v not in node_ids:
            errors.append(f"edges: 边 [{u!r}, {v!r}] 引用了不存在的节点")
            continue
        adj[u].append(v)
        indeg[v] += 1
    queue = [n for n in node_ids if indeg[n] == 0]
    seen = 0
    while queue:
        u = queue.pop()
        seen += 1
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    if seen < len(node_ids):
        errors.append("edges: 存在环（DAG 不允许回边；循环请用容器节点 body）")
    return errors


def validate_dag(dag: dict) -> tuple[list[str], list[str]]:
    """校验 DAG 定义，返回 (errors, warnings)。errors 非空即不可保存/执行。"""
    errors: list[str] = []
    warnings: list[str] = []
    registry.load_all()

    if not isinstance(dag, dict):
        return ["dag 必须是对象"], []
    if dag.get("version", 1) != 1:
        errors.append(f"不支持的 dag version: {dag.get('version')!r}")

    resources = dag.get("resources", [])
    if not isinstance(resources, list):
        errors.append("resources 必须是数组（如 [\"channel\", \"browser\"]）")

    run_inputs = dag.get("run_inputs", {})
    if not isinstance(run_inputs, dict):
        errors.append("run_inputs 必须是对象")
    else:
        for k, spec in run_inputs.items():
            if not isinstance(spec, dict) or "type" not in spec:
                errors.append(f"run_inputs.{k}: 必须含 type 字段")

    nodes = dag.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes 必须是非空数组")
        return errors, warnings

    node_ids: set[str] = set()
    for i, node in enumerate(nodes):
        nid = _validate_node(node, f"nodes[{i}]", errors, warnings)
        if nid:
            if nid in node_ids:
                errors.append(f"nodes[{i}]: 节点 id 重复: {nid!r}")
            node_ids.add(nid)

    edges = dag.get("edges", [])
    if not isinstance(edges, list):
        errors.append("edges 必须是数组")
    else:
        errors.extend(_check_acyclic(node_ids, edges))

    return errors, warnings


def validate_or_raise(dag: dict) -> list[str]:
    """校验失败抛 DagValidationError；通过则返回 warnings。"""
    errors, warnings = validate_dag(dag)
    if errors:
        raise DagValidationError(errors, warnings)
    return warnings
