# -*- coding: utf-8 -*-
"""CLI 入口：python -m fetcher <site> <task> [options]。

CLI 只做装配：参数 → RunConfig → 站点插件 → 策略表（可被参数覆盖）
→ Engine。共享参数迁移自旧 add_common_args，业务参数为各任务自有。
"""

from __future__ import annotations

import argparse
import sys

from fetcher.core.context import RunConfig
from fetcher.sites import get_site, site_names

# 任务默认批量（新站点未登记时用 DEFAULT_NUM）
TASK_NUM_DEFAULTS = {"contact": 10, "shop": 200, "company": 200}
DEFAULT_NUM = 50


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="fetcher",
        description="站点插件 + 策略表驱动的采集框架")
    ap.add_argument("--version", action="store_true", help="打印版本后退出")
    sub = ap.add_subparsers(dest="site")

    # 站点/任务全部来自 sites 注册表：加目录即接入，CLI 零修改
    for site_name in site_names():
        site = get_site(site_name)
        p_site = sub.add_parser(site_name, help=f"{site_name} 站点")
        task_sub = p_site.add_subparsers(dest="task", required=True)
        for task_name in site.task_names():
            t = task_sub.add_parser(task_name, help=f"{site_name} {task_name} 任务")
            t.add_argument("-n", "--num", type=int,
                           default=TASK_NUM_DEFAULTS.get(task_name, DEFAULT_NUM),
                           help="每个 worker 每批采集数量；采满一批后强制休息")
            t.add_argument("--limit", type=int, default=0,
                           help="每个 worker 本次最多采集量（默认 0=不限）")
            if task_name == "contact":
                t.add_argument("--retry-failed", action="store_true",
                               help="先把 failed 店铺重置为 pending 再开始抓取")
                t.add_argument("--tmd-report", action="store_true",
                               help="只打印各出口 IP 的 tmd 触发统计后退出")
            add_common_args(t, default_rest_every=(20 if task_name == "contact"
                                                   else 15))

    # daemon 常驻模式：与站点 subparsers 平级（dest 同为 "site"），不属于
    # 任何站点、不套 task 二级 subparser；num/limit 按 contact 口径给出，
    # 供 config_from_args 复用（--limit 是冒烟收工手段，走 CrawlLoop 既有逻辑）
    p_daemon = sub.add_parser(
        "daemon", help="常驻模式：从 work_items 队列持续消费（P0 仅 1688 contact）")
    p_daemon.add_argument("-n", "--num", type=int,
                          default=TASK_NUM_DEFAULTS["contact"],
                          help="每个 worker 每批采集数量；采满一批后强制休息")
    p_daemon.add_argument("--limit", type=int, default=0,
                          help="每个 worker 本次最多采集量（默认 0=不限）")
    p_daemon.add_argument("--queues", nargs="+", default=None,
                          help="消费的 work_items 队列列表（默认全量；可选: "
                               "crawl_1688_contact, crawl_mic_contact）")
    p_daemon.add_argument("--local-workers", type=int, default=2,
                          help="无浏览器 local 消费者线程数（wa_check 等"
                               "非站点队列消费用，默认 2，不占浏览器席位）")
    add_common_args(p_daemon, default_rest_every=20)
    return ap


def add_common_args(ap: argparse.ArgumentParser,
                    default_rest_every: int = 20) -> None:
    """所有任务共享的网络层参数（迁移旧 add_common_args）。"""
    ap.add_argument("--batch-rest", type=float, default=900,
                    help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
    ap.add_argument("--max-batches", type=int, default=0,
                    help="每个 worker 最多采集多少批（默认 0=不限）")
    ap.add_argument("--ip-retry", type=int, default=3,
                    help="重启浏览器获取新出口 IP 的重试次数（默认 3）")
    ap.add_argument("--block-rest-min", type=float, default=600,
                    help="风控后保持当前 IP 的休息时长下限秒数（默认 600=10 分钟）")
    ap.add_argument("--block-rest-max", type=float, default=900,
                    help="风控后保持当前 IP 的休息时长上限秒数（默认 900=15 分钟）")
    ap.add_argument("--net-retry", type=int, default=5,
                    help="单个任务项遇到网络/代理层错误时的重试次数（默认 5，"
                         "不计入风控连续失败计数）")
    ap.add_argument("--max-consecutive-fail", type=int, default=5,
                    help="连续失败多少次后判定被风控并中止整个任务（默认 5）")
    ap.add_argument("--headed", action="store_true",
                    help="有头模式运行（部分站点对 headless 更敏感）")
    ap.add_argument("--rest-every", type=int, default=default_rest_every,
                    help=f"每个 worker 每完成多少个单位后长休息一次"
                         f"（默认 {default_rest_every}，0 关闭）")
    ap.add_argument("--sample-min", type=float, default=13.0,
                    help="样本之间随机间隔的下限秒数（默认 13）")
    ap.add_argument("--sample-max", type=float, default=20.0,
                    help="样本之间随机间隔的上限秒数（默认 20）")
    ap.add_argument("--rest-min", type=float, default=60,
                    help="长休息随机时长的下限秒数（默认 60）")
    ap.add_argument("--rest-max", type=float, default=180,
                    help="长休息随机时长的上限秒数（默认 180）")
    ap.add_argument("--stagger-min", type=float, default=15.0,
                    help="worker 启动错开的最小秒数（默认 15）")
    ap.add_argument("--stagger-max", type=float, default=60.0,
                    help="worker 启动错开的最大秒数（默认 60）")
    ap.add_argument("--proxy", action="store_true",
                    help="走青果住宅代理；Cookie 按出口 IP 存 SQLite，"
                         "退出时自动把最新 Cookie 写回该 IP 名下")
    ap.add_argument("--seeds", type=str, default=None,
                    help="种子身份池目录（默认 .cache/seeds）；代理模式下 "
                         "worker 一对一独占认领")
    ap.add_argument("--seed-x5sec", action="store_true",
                    help="x5sec 免滑块实验：偶数 worker 的种子保留未过期的 "
                         "x5sec/x5secdata（A 组），奇数 worker 不含（B 组对照）")
    ap.add_argument("--channels", type=int, default=0,
                    help="青果通道池大小（默认取 provider 配置）")
    ap.add_argument("--workers", type=int, default=0,
                    help="并发 worker 数；代理模式默认=通道数，直连模式默认 1")
    ap.add_argument("--db", type=str, default=None,
                    help="数据库路径（默认项目根 .cache/1688.db）")
    ap.add_argument("--no-auto-solve", action="store_true",
                    help="关闭滑块轨迹回放自动过证（退化为纯人工/休息换 IP）")


def config_from_args(args) -> RunConfig:
    """argparse 命名空间 → RunConfig。"""
    cfg = RunConfig(
        headless=not args.headed,
        use_proxy=args.proxy,
        channels=args.channels,
        db_path=args.db,
        seeds_dir=args.seeds,
        seed_x5sec=args.seed_x5sec,
        ip_retry=args.ip_retry,
        net_retry=args.net_retry,
        max_consecutive_fail=args.max_consecutive_fail,
        block_rest_min=args.block_rest_min,
        block_rest_max=args.block_rest_max,
        batch_num=args.num,
        batch_rest=args.batch_rest,
        max_batches=args.max_batches,
        limit=args.limit,
        sample_min=args.sample_min,
        sample_max=args.sample_max,
        rest_every=args.rest_every,
        rest_min=args.rest_min,
        rest_max=args.rest_max,
        stagger_min=args.stagger_min,
        stagger_max=args.stagger_max,
        workers=args.workers,
        auto_solve_slider=not args.no_auto_solve,
    )
    # contact 任务的业务开关挂在 config 上（prepare 读取）
    cfg.retry_failed = getattr(args, "retry_failed", False)
    return cfg


def make_provider(cfg: RunConfig):
    """按配置装配代理 provider（青果为默认厂商）。"""
    if not cfg.use_proxy:
        return None
    from fetcher.net.proxy import QingGuoProvider  # 延迟导入
    return QingGuoProvider(cfg.channels or None)


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "version", False):
        from fetcher import __version__
        print(__version__)
        return 0
    if not getattr(args, "site", None):
        build_parser().print_help()
        return 2

    # daemon 常驻模式分支（"daemon" 不在站点注册表，必须先于 get_site 拦截）
    if args.site == "daemon":
        return _run_daemon(args)

    site = get_site(args.site)

    # contact 的 tmd 报表独立出口（不装配引擎）
    if getattr(args, "tmd_report", False):
        from fetcher.db import ShopDB
        db = ShopDB(RunConfig(db_path=args.db).resolved_db_path())
        print(db.format_tmd_report())
        db.close()
        return 0

    cfg = config_from_args(args)
    task = site.make_task(args.task)
    if not task.prepare(cfg):
        return 0

    provider = make_provider(cfg)
    # 策略表：默认表 + 站点级覆盖（policy_overrides）+ CLI 熔断上限
    from fetcher.strategy.policy import Policy
    policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
    overrides = getattr(site, "policy_overrides", None)
    if overrides:
        policy = policy.with_overrides(overrides)

    engine = _build_engine(cfg, task, site=site, provider=provider,
                           policy=policy, site_name=args.site)
    return engine.run()


def _build_engine(cfg, task, site, provider, policy, site_name):
    """纯装配辅助：构造 Engine 并返回（不调 run）。

    提取为独立函数便于测试 site_name 透传正确性。
    """
    from fetcher.control.engine import Engine
    return Engine(cfg, task, site=site, provider=provider, policy=policy,
                  site_name=site_name)


def _build_registry(selected_queues: list[str] | None = None) -> list:
    """构建 daemon 全量队列注册表（本 Step 2 条队列，P3-4/P3-5 加 shop/company）。

    selected_queues 非空时只保留指定队列；None=全量。
    返回值即 spec.queue 的全量列表，可作为 argparse choices 的来源。
    """
    from fetcher.control.queue_router import QueueSpec

    specs = []

    # crawl_1688_contact
    site_1688 = get_site("1688")
    specs.append(QueueSpec(
        queue="crawl_1688_contact",
        site="1688",
        task=site_1688.make_task("contact"),
        topup=lambda db, limit: db.topup_contact_work_items(
            "crawl_1688_contact", "1688", ".1688.com", limit),
        domain_suffix=".1688.com",
    ))

    # crawl_mic_contact
    site_mic = get_site("madeinchina")
    specs.append(QueueSpec(
        queue="crawl_mic_contact",
        site="madeinchina",
        task=site_mic.make_task("contact"),
        topup=lambda db, limit: db.topup_contact_work_items(
            "crawl_mic_contact", "madeinchina", ".cn.made-in-china.com", limit),
        domain_suffix=".cn.made-in-china.com",
    ))

    # crawl_mic_shop（feeder 队列：topup=None，不参与 in_progress reset）
    specs.append(QueueSpec(
        queue="crawl_mic_shop",
        site="madeinchina",
        task=site_mic.make_task("shop"),
        topup=None,
        domain_suffix="",
        requires={"channel", "browser"},
    ))

    # crawl_1688_shop（feeder 队列：topup=None，不参与 in_progress reset）
    specs.append(QueueSpec(
        queue="crawl_1688_shop",
        site="1688",
        task=site_1688.make_task("shop"),
        topup=None,
        domain_suffix="",
        requires={"channel", "browser"},
    ))

    # crawl_1688_company（feeder 队列：topup=None，不参与 in_progress reset）
    specs.append(QueueSpec(
        queue="crawl_1688_company",
        site="1688",
        task=site_1688.make_task("company"),
        topup=None,
        domain_suffix="",
        requires={"channel", "browser"},
    ))

    if selected_queues:
        specs = [s for s in specs if s.queue in selected_queues]
    return specs


def reset_daemon_state(db, registry: list) -> tuple[int, int]:
    """daemon 启动崩溃恢复：全量回收 claimed + 逐有 topup 的队列重置
    in_progress（feeder 队列跳过——不产生 in_progress shops）。

    返回 (n_claimed_reset, n_in_progress_reset)。
    提取为独立函数便于测试（I2）。
    """
    n_items = db.reset_claimed_work_items()
    total_shops = 0
    for spec in registry:
        if spec.topup is not None:
            n = db.reset_in_progress(spec.domain_suffix)
            total_shops += n
    return n_items, total_shops


def _run_daemon(args) -> int:
    """daemon 常驻模式装配：QueueRouter 跨队列认领 + Engine 跑。"""
    from fetcher.control.engine import Engine
    from fetcher.control.queue_router import QueueRouter
    from fetcher.db import ShopDB

    cfg = config_from_args(args)

    # 先建全量 registry（供校验用）
    full_registry = _build_registry()
    all_queue_names = [s.queue for s in full_registry]
    if args.queues:
        for q in args.queues:
            if q not in all_queue_names:
                print(f"[!] 未知队列: {q!r}（可选: {', '.join(all_queue_names)}）")
                return 2

    registry = _build_registry(args.queues)
    if not registry:
        print("[!] 没有可用的队列（--queues 过滤后为空）")
        return 2

    router = QueueRouter(registry)
    if not router.prepare(cfg):
        return 0

    provider = make_provider(cfg)

    # P4 daemon 可观测：装配 ConsumerStatusStore（心跳/租约/claim 上报）。
    # 线程本地连接（sqlite 不可跨线程），用 daemon 同一数据库。
    from fetcher.control.status import ConsumerStatusStore
    status_store = None
    if getattr(args, "status_report", True):
        status_store = ConsumerStatusStore(cfg.resolved_db_path())

    # 策略表：对 registry 涉及的每个 site 建 Policy
    from fetcher.strategy.policy import Policy
    policies = {}
    site_set = set()
    for spec in registry:
        if spec.site not in site_set:
            site_set.add(spec.site)
            site = get_site(spec.site)
            policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
            overrides = getattr(site, "policy_overrides", None)
            if overrides:
                policy = policy.with_overrides(overrides)
            policies[spec.site] = policy

    # daemon 用注册表首个 site 的默认 policy 作为 Engine 级 policy
    first_site = registry[0].site
    default_policy = policies[first_site]

    # 站点 dict（供 loop _bind_item_site 按 active_site 切换）
    sites = {}
    for site_name in site_set:
        sites[site_name] = get_site(site_name)

    # 崩溃恢复：先回收 work_items 残留认领（全量），
    # 再逐 site 重置 shops 的 in_progress（按 domain_suffix 过滤）
    db = ShopDB(cfg.resolved_db_path())
    try:
        n_items, total_shops = reset_daemon_state(db, registry)
    finally:
        db.close()
    print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
          f"{total_shops} 个 in_progress 店铺 → pending"
          f"（逐 site: {', '.join(spec.domain_suffix for spec in registry)}）")

    # Engine 装配：site 用首个注册 site（BrowserManager 初始 view identity 前缀），
    # policy 用 default_policy（多 site 的 _bind_item_site 会动态切换）
    first_site_obj = get_site(first_site)
    engine = Engine(cfg, task=router, site=first_site_obj,
                    provider=provider, policy=default_policy,
                    sites=sites, policies=policies,
                    site_name=first_site, status_store=status_store,
                    local_workers=getattr(args, "local_workers", 2))
    return engine.run()


if __name__ == "__main__":
    sys.exit(main())
