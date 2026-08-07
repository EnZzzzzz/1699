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
    p_daemon.add_argument("--queue", type=str, default="crawl_1688_contact",
                          help="消费的 work_items 队列名（P0 只支持默认值 "
                               "crawl_1688_contact，不开放其他选择）")
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

    from fetcher.control.engine import Engine
    engine = Engine(cfg, task, site=site, provider=provider, policy=policy,
                    site_name=args.site)
    return engine.run()


def _run_daemon(args) -> int:
    """daemon 常驻模式装配：1688 contact 包 DaemonTaskProxy 后跑 Engine。

    config_from_args 不读 args.task（读 task 的是站点分支的
    site.make_task(args.task)），daemon parser 已带 num/limit 默认值，
    故 config_from_args 原样复用、无需任何适配。provider/policy/Engine
    装配与站点分支逐项一致；退出语义不加新逻辑（信号走 Engine 既有
    优雅退出，--limit 走 CrawlLoop 既有收工逻辑）。
    """
    from fetcher.control.daemon_task import DaemonTaskProxy
    from fetcher.db import ShopDB

    cfg = config_from_args(args)
    site = get_site("1688")
    inner = site.make_task("contact")
    task = DaemonTaskProxy(inner, queue=args.queue, site="1688",
                           domain_suffix=".1688.com")
    if not task.prepare(cfg):
        return 0

    provider = make_provider(cfg)
    # 策略表：默认表 + 站点级覆盖（policy_overrides）+ CLI 熔断上限
    from fetcher.strategy.policy import Policy
    policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
    overrides = getattr(site, "policy_overrides", None)
    if overrides:
        policy = policy.with_overrides(overrides)

    # 崩溃恢复（SPEC §3.3 状态流）：先回收 work_items 残留认领，
    # 再重置 shops 的 in_progress（不带 domain 过滤，与既有 CLI 启动语义一致）
    db = ShopDB(cfg.resolved_db_path())
    try:
        n_items = db.reset_claimed_work_items()
        n_shops = db.reset_in_progress()
    finally:
        db.close()
    print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
          f"{n_shops} 个 in_progress 店铺 → pending")

    from fetcher.control.engine import Engine
    engine = Engine(cfg, task=task, site=site, provider=provider, policy=policy,
                    site_name="1688")
    return engine.run()


if __name__ == "__main__":
    sys.exit(main())
