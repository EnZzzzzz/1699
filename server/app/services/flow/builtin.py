# -*- coding: utf-8 -*-
"""内置流水线模板：1:1 复刻现有 contact_fetch / shop_crawl 两个任务。

参数默认值对齐 app/workers/{contact_fetch,shop_crawl}.py 的 _normalize_params。
模板 builtin=1 只读，用户经「复制」派生自己的版本后修改。
seed_builtin_flows 由 db.init_db() 调用（按 name 查重，幂等）。
"""
from __future__ import annotations

import json


def build_contact_fetch_dag() -> dict:
    """等价 contact_fetch：启动等待 → 申请通道 → 起浏览器 → 店铺循环。

    循环体：认领店铺 → IP 保鲜 → 抓联系方式（风控/网络失败换 IP 重试 + 熔断）
    → 拟人停顿（对应 docs/flow-architecture.md §4 示例）。
    注：contact_fetch 的 rest_every/rest_min/rest_max（每 N 个长休）与
    rotate_every 暂不在 for_each_shop 的 param_spec 中，容器节奏参数由后续
    引擎版本补齐后回填；批间休息语义由 num/batch_rest/max_batches 覆盖。
    """
    return {
        "version": 1,
        "resources": ["channel", "browser"],
        "run_inputs": {
            "limit": {"type": "int", "default": 0,
                      "label": "本次最多抓取（0=抓完全部 pending）"},
            "proxy": {"type": "bool", "default": True,
                      "label": "走代理（False=直连本机 IP）"},
            "headed": {"type": "bool", "default": False,
                       "label": "有头模式"},
        },
        "nodes": [
            # start_delay_min/max 默认 0（相等=固定等待 0，即立即开始）
            {"id": "start_delay", "atom": "sleep",
             "params": {"min": 0, "max": 0}},
            # channels=1；proxy 经 ${proxy} 引用 run_inputs（默认走代理）
            {"id": "acquire", "atom": "acquire_channel",
             "params": {"n": 1, "proxy": "${proxy}"}},
            # headed 经 ${headed} 引用 run_inputs（默认无头）
            {"id": "browser", "atom": "launch_browser",
             "params": {"headed": "${headed}"}},
            {"id": "loop", "atom": "for_each_shop",
             # num=10 / batch_rest=900 / max_batches=0 / parallel=1；
             # limit 经 ${limit} 引用 run_inputs（默认 0=不限）
             "params": {"num": 10, "batch_rest": 900, "max_batches": 0,
                        "limit": "${limit}", "parallel": 1},
             "body": [
                 {"id": "claim", "atom": "claim_shops",
                  "params": {"n": 1}},
                 {"id": "check_ip", "atom": "ensure_fresh_ip",
                  "params": {"ip_retry": 3}},          # ip_retry=3
                 {"id": "fetch", "atom": "fetch_contact",
                  "on_blocked": {"do": "swap_ip", "retry": 2},    # block_retry=2
                  "on_net_error": {"do": "swap_ip", "retry": 5},  # net_retry=5
                  # max_consecutive_fail=5：连续风控即中止整个任务
                  "circuit_breaker": {"consecutive_fail": 5,
                                      "action": "abort_task"}},
                 {"id": "pause", "atom": "human_pause",
                  "params": {"min": 3, "max": 7}},
             ]},
        ],
        "edges": [["start_delay", "acquire"], ["acquire", "browser"],
                  ["browser", "loop"]],
    }


def build_shop_crawl_dag() -> dict:
    """等价 shop_crawl：启动等待 → 申请通道 → 起浏览器 → 人工确认 → 采集循环。

    取舍说明：crawl_category 是「单轮类目分页采集」，本身不是容器。
    shop_crawl 主循环语义是「反复采轮次直到 target 达成」，与 for_each_shop
    容器（循环 + limit 上限）最接近，故用容器套 crawl_category：
    - limit 经 ${target} 引用 run_inputs（默认 0=不限）；旧任务 target=0 时
      「每 worker 1 轮」的语义（max_batches=1 兜底）暂不回填，属已知差异。
    - body 无 claim_shops 节点，validate 会给「未设上限可能无限循环」的
      warning，实际由 crawl_category 内部 empty_streak 退出与
      run_inputs.target 上限兜底，属可接受提示。
    - confirm_human 的跳过：run_inputs.yes=true 时引擎跳过该节点
      （无人值守，对齐旧任务 yes 参数）；headed+yes=false 才真正等待确认。
    - rest_every/rest_min/rest_max/rotate_every 同 contact_fetch 的说明，
      容器节奏参数补齐后回填。
    """
    return {
        "version": 1,
        "resources": ["channel", "browser"],
        "run_inputs": {
            "target": {"type": "int", "default": 0,
                       "label": "目标新增店铺数（0=采 1 轮）"},
            "category": {"type": "str", "default": "",
                         "label": "指定类目（空=全类目轮采）"},
            "yes": {"type": "bool", "default": True,
                    "label": "跳过人工确认（无人值守）"},
            "proxy": {"type": "bool", "default": True,
                      "label": "走代理（False=直连本机 IP）"},
            "headed": {"type": "bool", "default": False,
                       "label": "有头模式"},
        },
        "nodes": [
            {"id": "start_delay", "atom": "sleep",
             "params": {"min": 0, "max": 0}},
            {"id": "acquire", "atom": "acquire_channel",
             "params": {"n": 1, "proxy": "${proxy}"}},
            {"id": "browser", "atom": "launch_browser",
             "params": {"headed": "${headed}"}},
            # yes=false 且 headed 时才实际等待；timeout 对齐原子默认 600s
            {"id": "confirm", "atom": "confirm_human",
             "params": {"timeout": 600}},
            {"id": "loop", "atom": "for_each_shop",
             # 每批 1 轮、批间不强制休息（delay 在 crawl_category 内部）；
             # limit 经 ${target} 引用 run_inputs（默认 0=不限）
             "params": {"num": 1, "batch_rest": 0, "max_batches": 0,
                        "limit": "${target}", "parallel": 1},
             "body": [
                 # delay_min/max=15/45 对齐 shop_crawl._normalize_params
                 {"id": "crawl", "atom": "crawl_category",
                  "params": {"delay_min": 15, "delay_max": 45}},
             ]},
        ],
        "edges": [["start_delay", "acquire"], ["acquire", "browser"],
                  ["browser", "confirm"], ["confirm", "loop"]],
    }


def build_contact_fetch_slider_dag() -> dict:
    """联系人提取·滑块自愈版：在标准版基础上接入自动过滑块与分级修复。

    与「联系人提取·标准」的唯一差异在 fetch 节点的补救策略：
    - on_blocked → slider_repair（滑块优先的分阶段处置）：
      第 1~2 次自动过滑块（保住 IP/Cookie，零资源成本）→
      第 3 次原地等待 3~5 分钟并刷新页面 → 第 4 次刷新后再过滑块 →
      第 5 次换出口 IP；retry=5 覆盖全部阶段
    - on_net_error → net_repair（先刷新后换 IP）：
      第 1~2 次原地刷新页面（不换通道不重启浏览器）→ 第 3 次起换 IP
    - 熔断放宽到连续 6 次（补救链比标准版长，第 6 次仍 blocked 才中止）
    """
    dag = build_contact_fetch_dag()
    for node in dag["nodes"]:
        if node["id"] != "loop":
            continue
        for child in node["body"]:
            if child["id"] != "fetch":
                continue
            child["on_blocked"] = {"do": "slider_repair", "retry": 5}
            child["on_net_error"] = {"do": "net_repair", "retry": 5}
            child["circuit_breaker"] = {"consecutive_fail": 6,
                                        "action": "abort_task"}
    return dag


# (name, description, builder)；seed 按 name 查重
_BUILTIN_FLOWS = [
    ("联系人提取·标准",
     "内置模板：复刻 contact_fetch 任务（批式抓取店铺联系方式，"
     "风控/网络故障自动换 IP 重试 + 连续失败熔断）",
     build_contact_fetch_dag),
    ("店铺采集·标准",
     "内置模板：复刻 shop_crawl 任务（类目分页轮采店铺，"
     "支持人工确认与指定类目）",
     build_shop_crawl_dag),
    ("联系人提取·滑块自愈",
     "内置模板：联系人提取 + 自动过滑块（风控先自动拖滑块，连打失败则等待"
     "数分钟刷新页面再试，仍不行才换 IP；网络故障先原地刷新页面再换 IP）",
     build_contact_fetch_slider_dag),
]


def seed_builtin_flows(db) -> int:
    """幂等插入内置模板（按 name 查重），返回新增数（不含更新数）。

    已存在的 builtin 模板若 dag_json / description 与代码不一致则执行
    更新（保留 id 与 created_at，刷新 updated_at）——代码侧模板修订
    （如参数引用接线）能同步到已 seed 过的旧库；模板内容完全一致时
    不做任何写操作（幂等）。
    """
    from loguru import logger  # noqa: PLC0415
    from ... import config  # noqa: PLC0415
    from ...models import Flow  # noqa: PLC0415 - 延迟导入避免循环

    added = 0
    for name, description, builder in _BUILTIN_FLOWS:
        dag_json = json.dumps(builder(), ensure_ascii=False)
        row = db.query(Flow).filter(Flow.name == name).first()
        if row is not None:
            if row.dag_json != dag_json or row.description != description:
                row.dag_json = dag_json
                row.description = description
                row.updated_at = config.now_str()
                db.commit()
                logger.info("内置流水线模板「{}」已按代码版本更新 (id={})",
                            name, row.id)
            continue
        now = config.now_str()
        db.add(Flow(name=name, description=description,
                    dag_json=dag_json,
                    builtin=1, created_at=now, updated_at=now))
        added += 1
    if added:
        db.commit()
    return added
