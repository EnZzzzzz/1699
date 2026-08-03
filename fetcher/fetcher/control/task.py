# -*- coding: utf-8 -*-
"""Task：任务层协议（「采什么」），对应旧 FetchTask。

任务实现只关心：从哪取任务项、怎么抓、抓到怎么入库。控制层
（CrawlLoop/Engine）管「怎么连」：通道、浏览器、场景判断、策略处置。

与旧 FetchTask 的差异：hook 签名统一为 ctx 驱动（WorkerContext 携带
store/db/log/set_status/config），scrape 改名为 fetch 并返回
ActionResult；wctx 暂存改为 ctx.state["task"]。
"""

from __future__ import annotations

from fetcher.core.types import ActionResult


class Task:
    """任务基类：提供全部 hook 的默认实现，子类按需覆盖。

    类属性：
        unit                    状态行间隔单位名（"样本"/"页"）
        batch_unit              批次日志计量名词（""/"店铺"）
        cold_start_before_acquire  True=冷启动在 acquire 之前执行
                                   （如类目池需先逛首页填池）
        ip_request_budget       每出口 IP 请求预算（None=无）：采满 N 个
                                请求后主动换 IP，规避平台级匿名配额墙
    """

    name = "task"
    unit = "样本"
    batch_unit = ""
    cold_start_before_acquire = False
    ip_request_budget: int | None = None

    # ---- main 阶段 ----

    def prepare(self, config) -> bool:
        """启动前准备（重置状态/打印计划）；返回 False 直接退出。"""
        return True

    def summary(self, all_stats: dict) -> str:
        """全部 worker 结束后的汇总行。"""
        return str(all_stats)

    # ---- 状态板 ----

    def compose(self, wid: int, f: dict) -> str:
        """状态行格式（StatusBoard compose 回调）。"""
        return str(f.get("line", ""))

    def make_stats(self) -> dict:
        """每个 worker 的统计字典（结构任务自定）。"""
        return {}

    def rest_counter(self, stats: dict) -> int:
        """长休息计数基准（rest_every 按此值取模）。"""
        return 0

    # ---- worker 循环 ----

    def acquire_item(self, ctx):
        """认领一个任务项；没有可做的返回 None（worker 退出）。"""
        raise NotImplementedError

    def label(self, item) -> str:
        """状态行上显示的任务项名称。"""
        return str(item)

    def cold_start(self, ctx, item) -> None:
        """新会话冷启动软着陆（留下真实浏览轨迹）。"""

    def empty_message(self) -> str:
        """任务队列耗尽时的一行滚动日志。"""
        return "没有待做的任务了"

    def fetch(self, ctx, item) -> ActionResult:
        """抓取当前任务项（采什么）。

        实现要求：
            - 异常时写入 ctx.last_error 并按 classify_error 分级返回
              fatal/net_error（探测器据此判 BROWSER_DEAD/NET_ERROR）；
            - 自检发现不宜继续（如缺 mtop 令牌）时返回 BLOCKED，
              控制层按风控场景处理；
            - 正常返回 OK，数据放 data。
        """
        raise NotImplementedError

    def validate(self, ctx, item, result: ActionResult) -> bool:
        """抓取结果的结构化有效性校验（字段级，比文本长度阈值可靠）。

        场景判定 OK 后才调用；返回 False 按 EMPTY 场景进策略链。
        EmptyPageDetector 的文本阈值只作兜底。
        """
        return True

    def on_success(self, ctx, item, result: ActionResult) -> int:
        """抓取成功：入库/更新统计/状态行；返回计入批次配额的数量。"""
        return 1

    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
        """放弃当前任务项（kind: "net" 网络故障 / "block" 风控）；
        返回一句短语让控制层拼进日志。"""
        return "跳过"

    def on_abort(self, ctx, item) -> str:
        """连续失败触发整体中止时的一行补充说明。"""
        return ""

    def giveup_cost(self, item) -> int:
        """放弃的任务项计入批次配额的数量。"""
        return 0

    def after_item(self, ctx, item) -> None:
        """当前任务项处理完毕（含放弃）后的收尾（如释放类目占用）。"""
