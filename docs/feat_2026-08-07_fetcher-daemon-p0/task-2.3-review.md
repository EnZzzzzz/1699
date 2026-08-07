=== git log ===
e377a29 docs(fetcher): Step 2.3 daemon CLI 子命令实现报告
24cfe7d feat(fetcher): CLI 新增 daemon 子命令（1688 contact 常驻模式装配）

=== diff --stat ===
 .../task-2.3-brief.md                              | 31 +++++++++
 .../task-2.3-report.md                             | 75 ++++++++++++++++++++++
 fetcher/fetcher/cli/main.py                        | 63 ++++++++++++++++++
 fetcher/tests/test_cli.py                          | 70 ++++++++++++++++++++
 4 files changed, 239 insertions(+)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.3-brief.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.3-brief.md
new file mode 100644
index 0000000..fbad413
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.3-brief.md
@@ -0,0 +1,31 @@
+# Step 2.3 brief — CLI daemon 子命令
+
+> 来源：PLAN.md Phase 2 Step 2.3 + SPEC §3.4。本文本是你的需求唯一来源。
+
+## 内容
+
+在 `fetcher/fetcher/cli/main.py` 加 daemon 子命令：
+
+1. **parser**：`build_parser()`（main.py:21-47）的顶层 subparsers 增加 `daemon` parser（与站点 subparsers 平级，不属于任何站点），带 `add_common_args()`（main.py:50-101）全套参数 + `--queue`（默认 `crawl_1688_contact`，P0 不开放其他选择，help 文案注明）。
+   - 注意现有结构：`sub = ap.add_subparsers(dest="site")`，daemon 挂在同一个 sub 上即可（dest 同为 "site"，main() 里按 `args.site == "daemon"` 分支）。daemon parser **不再套 task 二级 subparser**。
+2. **main() 分支**（main.py:145-180）：`args.site == "daemon"` 时：
+   - `config_from_args(args)` 复用（注意它是否读 `args.task`——若读，daemon 分支要处理，report 说明怎么处理的）；
+   - `get_site("1688")` 取插件 → `site.make_task("contact")` → 包 `DaemonTaskProxy(inner, queue=args.queue, site="1688", domain_suffix=".1688.com")`（domain_suffix 口径与 `contact.py:155-160` 的 `claim_pending_shops(1, ".1688.com")` 一致）；
+   - provider/policy 装配与现有站点分支**逐项一致**（`make_provider`、`Policy(...)` + `site.policy_overrides`）；
+   - 启动 Engine 前依次调用：`db.reset_claimed_work_items()` + `db.reset_in_progress()`（SPEC §3.3 状态流；ShopDB 用 `cfg.resolved_db_path()` 建一个临时实例即可，参照现有代码怎么建）；这两步打日志说明重置了多少行；
+   - `Engine(cfg, task=proxy, site=site, provider=provider, policy=policy).run()`。
+3. **退出语义**：不加任何新逻辑——SIGTERM/SIGHUP/KeyboardInterrupt 走 Engine 既有优雅退出；`--limit N` 由 CrawlLoop 既有逻辑收工（这是冒烟的退出手段，不要拦）。
+
+## 验收
+
+- [ ] `python -m fetcher daemon --help` 输出正常（含 --queue 与全套 common 参数）
+- [ ] 既有子命令（1688 shop/contact/company、yiwugo search）`--help` 与行为无变化（diff 层面：既有分支零改动）
+- [ ] main() daemon 分支装配参数与 site 分支逐项一致（provider/policy/Engine 参数）
+- [ ] 新增解析层测试：parser 能正确解析 `daemon`（含 --queue 默认值）与既有站点子命令（防装配层回归的挂载测试，放 `fetcher/tests/` 下，若已有 CLI 测试文件则并入，命名跟随既有惯例）
+- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归
+
+## 约束
+
+- 只动 `fetcher/fetcher/cli/main.py` + 一个测试文件；不碰 engine/loop/daemon_task/db/站点插件。
+- 既有站点分支的代码零改动（重构出公共函数也算改动——如果复用需要提取公共段，允许提取但既有调用点的行为必须逐字等价，report 说明提取前后对照）。
+- DaemonTaskProxy 的接口见 `fetcher/fetcher/control/daemon_task.py`（Step 2.1 产出），先读再用。
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.3-report.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.3-report.md
new file mode 100644
index 0000000..13a191e
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-2.3-report.md
@@ -0,0 +1,75 @@
+# Step 2.3 report — CLI daemon 子命令
+
+## 实现了什么
+
+按 `task-2.3-brief.md` 实现，改动全部落在 `fetcher/fetcher/cli/main.py`（纯追加 63 行，diff 层面既有站点分支零改动）+ 新增 `fetcher/tests/test_cli.py`：
+
+1. **parser**（`build_parser()`）：站点注册表循环之后，在同一个 `sub = ap.add_subparsers(dest="site")` 上挂 `daemon` parser，不套 task 二级 subparser。参数：
+   - `-n/--num`（默认 `TASK_NUM_DEFAULTS["contact"]=10`）与 `--limit`（默认 0）——brief 正文只列了「add_common_args 全套 + --queue」，但 `config_from_args` 必读 `args.num`/`args.limit`（缺了直接 AttributeError），且 brief §3 明确 `--limit N` 是冒烟收工手段，故两者必须作为真实参数挂上；定义文案与站点 task parser 逐字一致；
+   - `--queue`（默认 `crawl_1688_contact`，help 注明 P0 不开放其他选择）；
+   - `add_common_args(p_daemon, default_rest_every=20)`（contact 口径）。
+2. **main() 分支**：`args.site == "daemon"` 在 `get_site(args.site)` 之前拦截（"daemon" 不在站点注册表，不拦会 KeyError），转入 `_run_daemon(args)`。
+3. **`_run_daemon(args)`**：
+   - `config_from_args(args)` 原样复用（见下节）；
+   - `get_site("1688")` → `site.make_task("contact")` → `DaemonTaskProxy(inner, queue=args.queue, site="1688", domain_suffix=".1688.com")`（domain_suffix 与 `sites/alibaba1688/contact.py:90` 的 `_SHOP_DOMAIN_SUFFIX`、`:157` 的 `claim_pending_shops(1, ".1688.com")` 同口径）；
+   - `task.prepare(cfg)`：站点分支在装配 provider 前调 prepare，daemon 分支镜像同一位置——DaemonTaskProxy.prepare 调 inner.prepare 并打印队列待办数（SPEC §3.3），且恒返回 True（队列空不退出）；
+   - provider/policy 与站点分支**逐项一致**：`make_provider(cfg)`、`Policy(max_consecutive_fail=cfg.max_consecutive_fail)` + `getattr(site, "policy_overrides", None)` → `with_overrides`（含注释都保持一致）；
+   - 启动 Engine 前依次 `db.reset_claimed_work_items()` + `db.reset_in_progress()`（`ShopDB(cfg.resolved_db_path())` 临时实例，try/finally close，仿 tmd_report 分支建法），并打印两行重置数；
+   - `Engine(cfg, task=task, site=site, provider=provider, policy=policy).run()`。
+4. **退出语义**：未加任何新逻辑。
+
+## config_from_args 的 args.task 处理方式
+
+`config_from_args`（main.py:104-134）**不读 `args.task`**——读 task 的是 main() 站点分支的 `site.make_task(args.task)`（main.py:166）。daemon 分支不经过该调用（固定 `make_task("contact")`），因此 config_from_args 零改动原样复用。它读的 `args.num`/`args.limit`/`args.retry_failed` 中：num/limit 由 daemon parser 显式提供；`retry_failed` 走 `getattr(args, "retry_failed", False)` 容错（daemon parser 无此开关，语义=不重试 failed，正确）。
+
+## reset_in_progress 不带 domain_suffix 的依据
+
+brief 字面为 `db.reset_in_progress()`（无参）。初看与 contact.py:108 的 `reset_in_progress(_SHOP_DOMAIN_SUFFIX)` 冲突，但 SPEC §3.3 与 PLAN 风险节已明确裁定：daemon 启动对 shops 调**无过滤**的 `reset_in_progress`，「会把其他来源的 in_progress 也重置——与现有 CLI 启动行为一致，属于既有语义，不新增风险」，并文档化「daemon 与旧 CLI 同站互斥」。故按 brief 字面实现，未加 suffix。
+
+## TDD 证据（先红后绿）
+
+测试先行：`fetcher/tests/test_cli.py`（5 用例：daemon 默认值/参数覆盖/config_from_args 复用/无 task 二级 subparser/既有站点子命令防回归）。
+
+- RED（实现前）：
+  ```
+  $ cd fetcher && python -m pytest tests/test_cli.py -x -q
+  FAILED tests/test_cli.py::CliParserTest::test_daemon_config_from_args - SystemExit: 2
+  fetcher: error: argument site: invalid choice: 'daemon' (choose from 1688, facebook, madeinchina, taobao, yiwugo)
+  1 failed in 0.14s
+  ```
+  符合预期：daemon parser 未注册。
+- GREEN（实现后）：同一命令 → `5 passed in 0.04s`
+
+## --help 验证输出要点
+
+- `python -m fetcher daemon --help`：正常输出，usage 含 `[-n NUM] [--limit LIMIT] [--queue QUEUE]` + 全套 common 参数（--batch-rest/--ip-retry/--proxy/--seeds/--workers/--db 等 21 项）；`--queue` help 文案注明「P0 只支持默认值 crawl_1688_contact，不开放其他选择」。
+- `python -m fetcher --help`：顶层 choices 变为 `{1688,facebook,madeinchina,taobao,yiwugo,daemon}`，daemon 帮助行正常。
+- 既有子命令：`1688 contact --help`（含 --retry-failed/--tmd-report）、`1688 shop/company --help`、`yiwugo search --help` 输出与改动前一致（diff 为纯追加，站点分支零改动）。
+- `python -m fetcher daemon contact` 正确报错退出（无 task 二级 subparser）。
+
+## 全量测试结果
+
+```
+$ cd fetcher && python -m pytest tests -x -q
+231 passed, 2 subtests passed in 8.53s
+```
+无回归（新增 5 个 CLI 用例全绿）。
+
+## 改动的文件
+
+- `fetcher/fetcher/cli/main.py`（+63 行纯追加：daemon parser + main() 拦截分支 + `_run_daemon()`）
+- `fetcher/tests/test_cli.py`（新增，5 用例）
+
+commit：`24cfe7d feat(fetcher): CLI 新增 daemon 子命令（1688 contact 常驻模式装配）`（同时收录 task-2.3-brief.md，与前序 Step 收录 brief 的做法一致）。
+
+## 自查发现
+
+- 对照验收清单逐条核验：daemon --help 正常 ✓；既有子命令 --help/行为无变化（diff 纯追加）✓；provider/policy/Engine 装配与站点分支逐项一致 ✓；解析层测试含 --queue 默认值与站点挂载防回归 ✓；全量无回归 ✓。
+- 约束核验：只动了 main.py + 一个测试文件；未碰 engine/loop/daemon_task/db/站点插件；未提取公共函数（装配段短，逐字复制站点分支片段比抽公共函数更符合「既有调用点行为逐字等价」要求——两处的注释也保持了一致）。
+- 防假阳性：RED 阶段失败信息确为「daemon 未注册」（invalid choice），非测试本身错误。
+
+## 疑虑
+
+1. **num/limit 超出 brief 字面清单**：brief parser 节只写「add_common_args 全套 + --queue」，但 config_from_args 必读 num/limit 且 brief §3 明确 --limit 是冒烟收工手段，故补挂了两者（contact 口径默认值）。若评审认为应更克制，可改为 `set_defaults(num=10, limit=0)` 隐藏参数，但那样 --limit 冒烟手段不可达，不推荐。
+2. **prepare 调用位置**：brief 步骤清单未列 prepare，但站点分支有且 DaemonTaskProxy.prepare 即为此设计（SPEC §3.3）；镜像站点分支位置调用。inner.prepare 内的 scoped `reset_in_progress` 会先于 daemon 分支的无过滤 reset 执行一次，幂等无害。
+3. 冒烟实测（真跑 daemon + --limit）不属于本 Step 验收范围（PLAN 归 Step 3.x），未执行。
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index e48d39a..b5e61c1 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -37,20 +37,35 @@ def build_parser() -> argparse.ArgumentParser:
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
+
+    # daemon 常驻模式：与站点 subparsers 平级（dest 同为 "site"），不属于
+    # 任何站点、不套 task 二级 subparser；num/limit 按 contact 口径给出，
+    # 供 config_from_args 复用（--limit 是冒烟收工手段，走 CrawlLoop 既有逻辑）
+    p_daemon = sub.add_parser(
+        "daemon", help="常驻模式：从 work_items 队列持续消费（P0 仅 1688 contact）")
+    p_daemon.add_argument("-n", "--num", type=int,
+                          default=TASK_NUM_DEFAULTS["contact"],
+                          help="每个 worker 每批采集数量；采满一批后强制休息")
+    p_daemon.add_argument("--limit", type=int, default=0,
+                          help="每个 worker 本次最多采集量（默认 0=不限）")
+    p_daemon.add_argument("--queue", type=str, default="crawl_1688_contact",
+                          help="消费的 work_items 队列名（P0 只支持默认值 "
+                               "crawl_1688_contact，不开放其他选择）")
+    add_common_args(p_daemon, default_rest_every=20)
     return ap
 
 
 def add_common_args(ap: argparse.ArgumentParser,
                     default_rest_every: int = 20) -> None:
     """所有任务共享的网络层参数（迁移旧 add_common_args）。"""
     ap.add_argument("--batch-rest", type=float, default=900,
                     help="每批采满后的强制休息秒数（默认 900=15 分钟，±10%% 抖动）")
     ap.add_argument("--max-batches", type=int, default=0,
                     help="每个 worker 最多采集多少批（默认 0=不限）")
@@ -145,20 +160,24 @@ def make_provider(cfg: RunConfig):
 def main(argv: list | None = None) -> int:
     args = build_parser().parse_args(argv)
     if getattr(args, "version", False):
         from fetcher import __version__
         print(__version__)
         return 0
     if not getattr(args, "site", None):
         build_parser().print_help()
         return 2
 
+    # daemon 常驻模式分支（"daemon" 不在站点注册表，必须先于 get_site 拦截）
+    if args.site == "daemon":
+        return _run_daemon(args)
+
     site = get_site(args.site)
 
     # contact 的 tmd 报表独立出口（不装配引擎）
     if getattr(args, "tmd_report", False):
         from fetcher.db import ShopDB
         db = ShopDB(RunConfig(db_path=args.db).resolved_db_path())
         print(db.format_tmd_report())
         db.close()
         return 0
 
@@ -173,12 +192,56 @@ def main(argv: list | None = None) -> int:
     policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
     overrides = getattr(site, "policy_overrides", None)
     if overrides:
         policy = policy.with_overrides(overrides)
 
     from fetcher.control.engine import Engine
     engine = Engine(cfg, task, site=site, provider=provider, policy=policy)
     return engine.run()
 
 
+def _run_daemon(args) -> int:
+    """daemon 常驻模式装配：1688 contact 包 DaemonTaskProxy 后跑 Engine。
+
+    config_from_args 不读 args.task（读 task 的是站点分支的
+    site.make_task(args.task)），daemon parser 已带 num/limit 默认值，
+    故 config_from_args 原样复用、无需任何适配。provider/policy/Engine
+    装配与站点分支逐项一致；退出语义不加新逻辑（信号走 Engine 既有
+    优雅退出，--limit 走 CrawlLoop 既有收工逻辑）。
+    """
+    from fetcher.control.daemon_task import DaemonTaskProxy
+    from fetcher.db import ShopDB
+
+    cfg = config_from_args(args)
+    site = get_site("1688")
+    inner = site.make_task("contact")
+    task = DaemonTaskProxy(inner, queue=args.queue, site="1688",
+                           domain_suffix=".1688.com")
+    if not task.prepare(cfg):
+        return 0
+
+    provider = make_provider(cfg)
+    # 策略表：默认表 + 站点级覆盖（policy_overrides）+ CLI 熔断上限
+    from fetcher.strategy.policy import Policy
+    policy = Policy(max_consecutive_fail=cfg.max_consecutive_fail)
+    overrides = getattr(site, "policy_overrides", None)
+    if overrides:
+        policy = policy.with_overrides(overrides)
+
+    # 崩溃恢复（SPEC §3.3 状态流）：先回收 work_items 残留认领，
+    # 再重置 shops 的 in_progress（不带 domain 过滤，与既有 CLI 启动语义一致）
+    db = ShopDB(cfg.resolved_db_path())
+    try:
+        n_items = db.reset_claimed_work_items()
+        n_shops = db.reset_in_progress()
+    finally:
+        db.close()
+    print(f"[daemon] 启动重置：{n_items} 个 claimed 工作项 → pending，"
+          f"{n_shops} 个 in_progress 店铺 → pending")
+
+    from fetcher.control.engine import Engine
+    engine = Engine(cfg, task=task, site=site, provider=provider, policy=policy)
+    return engine.run()
+
+
 if __name__ == "__main__":
     sys.exit(main())
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
new file mode 100644
index 0000000..ca063a7
--- /dev/null
+++ b/fetcher/tests/test_cli.py
@@ -0,0 +1,70 @@
+# -*- coding: utf-8 -*-
+"""CLI 解析层测试：daemon 子命令挂载 + 既有站点子命令防装配回归。"""
+
+import unittest
+
+from fetcher.cli.main import build_parser, config_from_args
+
+
+class CliParserTest(unittest.TestCase):
+    def setUp(self):
+        self.ap = build_parser()
+
+    # ---- daemon 子命令 ----
+
+    def test_daemon_defaults(self):
+        args = self.ap.parse_args(["daemon"])
+        self.assertEqual(args.site, "daemon")
+        # --queue 默认值（P0 不开放其他选择）
+        self.assertEqual(args.queue, "crawl_1688_contact")
+        # daemon 不套 task 二级 subparser
+        self.assertIsNone(getattr(args, "task", None))
+        # add_common_args 全套已挂载（抽查代表项）
+        self.assertEqual(args.rest_every, 20)
+        self.assertEqual(args.batch_rest, 900)
+        self.assertFalse(args.proxy)
+        self.assertFalse(args.headed)
+        # config_from_args 依赖的 num/limit 必须有默认（contact 口径）
+        self.assertEqual(args.num, 10)
+        self.assertEqual(args.limit, 0)
+
+    def test_daemon_queue_and_common_override(self):
+        args = self.ap.parse_args(
+            ["daemon", "--queue", "q2", "--workers", "3", "--limit", "5"])
+        self.assertEqual(args.queue, "q2")
+        self.assertEqual(args.workers, 3)
+        self.assertEqual(args.limit, 5)
+
+    def test_daemon_config_from_args(self):
+        # config_from_args 不读 args.task，daemon 命名空间可直接复用
+        cfg = config_from_args(self.ap.parse_args(["daemon"]))
+        self.assertEqual(cfg.batch_num, 10)
+        self.assertEqual(cfg.limit, 0)
+
+    def test_daemon_has_no_task_subparser(self):
+        # daemon 后不能再跟 task 位置参数（argparse 报错退出）
+        with self.assertRaises(SystemExit):
+            self.ap.parse_args(["daemon", "contact"])
+
+    # ---- 既有站点子命令防回归 ----
+
+    def test_existing_site_subcommands_unchanged(self):
+        cases = {
+            ("1688", "shop"): 200,
+            ("1688", "contact"): 10,
+            ("1688", "company"): 200,
+        }
+        for (site, task), num in cases.items():
+            args = self.ap.parse_args([site, task])
+            self.assertEqual(args.site, site)
+            self.assertEqual(args.task, task)
+            self.assertEqual(args.num, num)
+        args = self.ap.parse_args(["yiwugo", "search"])
+        self.assertEqual((args.site, args.task), ("yiwugo", "search"))
+        # contact 业务开关仍在
+        args = self.ap.parse_args(["1688", "contact", "--retry-failed"])
+        self.assertTrue(args.retry_failed)
+
+
+if __name__ == "__main__":
+    unittest.main()
