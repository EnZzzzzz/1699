# Step 2.3 brief — CLI daemon 子命令

> 来源：PLAN.md Phase 2 Step 2.3 + SPEC §3.4。本文本是你的需求唯一来源。

## 内容

在 `fetcher/fetcher/cli/main.py` 加 daemon 子命令：

1. **parser**：`build_parser()`（main.py:21-47）的顶层 subparsers 增加 `daemon` parser（与站点 subparsers 平级，不属于任何站点），带 `add_common_args()`（main.py:50-101）全套参数 + `--queue`（默认 `crawl_1688_contact`，P0 不开放其他选择，help 文案注明）。
   - 注意现有结构：`sub = ap.add_subparsers(dest="site")`，daemon 挂在同一个 sub 上即可（dest 同为 "site"，main() 里按 `args.site == "daemon"` 分支）。daemon parser **不再套 task 二级 subparser**。
2. **main() 分支**（main.py:145-180）：`args.site == "daemon"` 时：
   - `config_from_args(args)` 复用（注意它是否读 `args.task`——若读，daemon 分支要处理，report 说明怎么处理的）；
   - `get_site("1688")` 取插件 → `site.make_task("contact")` → 包 `DaemonTaskProxy(inner, queue=args.queue, site="1688", domain_suffix=".1688.com")`（domain_suffix 口径与 `contact.py:155-160` 的 `claim_pending_shops(1, ".1688.com")` 一致）；
   - provider/policy 装配与现有站点分支**逐项一致**（`make_provider`、`Policy(...)` + `site.policy_overrides`）；
   - 启动 Engine 前依次调用：`db.reset_claimed_work_items()` + `db.reset_in_progress()`（SPEC §3.3 状态流；ShopDB 用 `cfg.resolved_db_path()` 建一个临时实例即可，参照现有代码怎么建）；这两步打日志说明重置了多少行；
   - `Engine(cfg, task=proxy, site=site, provider=provider, policy=policy).run()`。
3. **退出语义**：不加任何新逻辑——SIGTERM/SIGHUP/KeyboardInterrupt 走 Engine 既有优雅退出；`--limit N` 由 CrawlLoop 既有逻辑收工（这是冒烟的退出手段，不要拦）。

## 验收

- [ ] `python -m fetcher daemon --help` 输出正常（含 --queue 与全套 common 参数）
- [ ] 既有子命令（1688 shop/contact/company、yiwugo search）`--help` 与行为无变化（diff 层面：既有分支零改动）
- [ ] main() daemon 分支装配参数与 site 分支逐项一致（provider/policy/Engine 参数）
- [ ] 新增解析层测试：parser 能正确解析 `daemon`（含 --queue 默认值）与既有站点子命令（防装配层回归的挂载测试，放 `fetcher/tests/` 下，若已有 CLI 测试文件则并入，命名跟随既有惯例）
- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归

## 约束

- 只动 `fetcher/fetcher/cli/main.py` + 一个测试文件；不碰 engine/loop/daemon_task/db/站点插件。
- 既有站点分支的代码零改动（重构出公共函数也算改动——如果复用需要提取公共段，允许提取但既有调用点的行为必须逐字等价，report 说明提取前后对照）。
- DaemonTaskProxy 的接口见 `fetcher/fetcher/control/daemon_task.py`（Step 2.1 产出），先读再用。
