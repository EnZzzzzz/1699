# Step 2.3 report — CLI daemon 子命令

## 实现了什么

按 `task-2.3-brief.md` 实现，改动全部落在 `fetcher/fetcher/cli/main.py`（纯追加 63 行，diff 层面既有站点分支零改动）+ 新增 `fetcher/tests/test_cli.py`：

1. **parser**（`build_parser()`）：站点注册表循环之后，在同一个 `sub = ap.add_subparsers(dest="site")` 上挂 `daemon` parser，不套 task 二级 subparser。参数：
   - `-n/--num`（默认 `TASK_NUM_DEFAULTS["contact"]=10`）与 `--limit`（默认 0）——brief 正文只列了「add_common_args 全套 + --queue」，但 `config_from_args` 必读 `args.num`/`args.limit`（缺了直接 AttributeError），且 brief §3 明确 `--limit N` 是冒烟收工手段，故两者必须作为真实参数挂上；定义文案与站点 task parser 逐字一致；
   - `--queue`（默认 `crawl_1688_contact`，help 注明 P0 不开放其他选择）；
   - `add_common_args(p_daemon, default_rest_every=20)`（contact 口径）。
2. **main() 分支**：`args.site == "daemon"` 在 `get_site(args.site)` 之前拦截（"daemon" 不在站点注册表，不拦会 KeyError），转入 `_run_daemon(args)`。
3. **`_run_daemon(args)`**：
   - `config_from_args(args)` 原样复用（见下节）；
   - `get_site("1688")` → `site.make_task("contact")` → `DaemonTaskProxy(inner, queue=args.queue, site="1688", domain_suffix=".1688.com")`（domain_suffix 与 `sites/alibaba1688/contact.py:90` 的 `_SHOP_DOMAIN_SUFFIX`、`:157` 的 `claim_pending_shops(1, ".1688.com")` 同口径）；
   - `task.prepare(cfg)`：站点分支在装配 provider 前调 prepare，daemon 分支镜像同一位置——DaemonTaskProxy.prepare 调 inner.prepare 并打印队列待办数（SPEC §3.3），且恒返回 True（队列空不退出）；
   - provider/policy 与站点分支**逐项一致**：`make_provider(cfg)`、`Policy(max_consecutive_fail=cfg.max_consecutive_fail)` + `getattr(site, "policy_overrides", None)` → `with_overrides`（含注释都保持一致）；
   - 启动 Engine 前依次 `db.reset_claimed_work_items()` + `db.reset_in_progress()`（`ShopDB(cfg.resolved_db_path())` 临时实例，try/finally close，仿 tmd_report 分支建法），并打印两行重置数；
   - `Engine(cfg, task=task, site=site, provider=provider, policy=policy).run()`。
4. **退出语义**：未加任何新逻辑。

## config_from_args 的 args.task 处理方式

`config_from_args`（main.py:104-134）**不读 `args.task`**——读 task 的是 main() 站点分支的 `site.make_task(args.task)`（main.py:166）。daemon 分支不经过该调用（固定 `make_task("contact")`），因此 config_from_args 零改动原样复用。它读的 `args.num`/`args.limit`/`args.retry_failed` 中：num/limit 由 daemon parser 显式提供；`retry_failed` 走 `getattr(args, "retry_failed", False)` 容错（daemon parser 无此开关，语义=不重试 failed，正确）。

## reset_in_progress 不带 domain_suffix 的依据

brief 字面为 `db.reset_in_progress()`（无参）。初看与 contact.py:108 的 `reset_in_progress(_SHOP_DOMAIN_SUFFIX)` 冲突，但 SPEC §3.3 与 PLAN 风险节已明确裁定：daemon 启动对 shops 调**无过滤**的 `reset_in_progress`，「会把其他来源的 in_progress 也重置——与现有 CLI 启动行为一致，属于既有语义，不新增风险」，并文档化「daemon 与旧 CLI 同站互斥」。故按 brief 字面实现，未加 suffix。

## TDD 证据（先红后绿）

测试先行：`fetcher/tests/test_cli.py`（5 用例：daemon 默认值/参数覆盖/config_from_args 复用/无 task 二级 subparser/既有站点子命令防回归）。

- RED（实现前）：
  ```
  $ cd fetcher && python -m pytest tests/test_cli.py -x -q
  FAILED tests/test_cli.py::CliParserTest::test_daemon_config_from_args - SystemExit: 2
  fetcher: error: argument site: invalid choice: 'daemon' (choose from 1688, facebook, madeinchina, taobao, yiwugo)
  1 failed in 0.14s
  ```
  符合预期：daemon parser 未注册。
- GREEN（实现后）：同一命令 → `5 passed in 0.04s`

## --help 验证输出要点

- `python -m fetcher daemon --help`：正常输出，usage 含 `[-n NUM] [--limit LIMIT] [--queue QUEUE]` + 全套 common 参数（--batch-rest/--ip-retry/--proxy/--seeds/--workers/--db 等 21 项）；`--queue` help 文案注明「P0 只支持默认值 crawl_1688_contact，不开放其他选择」。
- `python -m fetcher --help`：顶层 choices 变为 `{1688,facebook,madeinchina,taobao,yiwugo,daemon}`，daemon 帮助行正常。
- 既有子命令：`1688 contact --help`（含 --retry-failed/--tmd-report）、`1688 shop/company --help`、`yiwugo search --help` 输出与改动前一致（diff 为纯追加，站点分支零改动）。
- `python -m fetcher daemon contact` 正确报错退出（无 task 二级 subparser）。

## 全量测试结果

```
$ cd fetcher && python -m pytest tests -x -q
231 passed, 2 subtests passed in 8.53s
```
无回归（新增 5 个 CLI 用例全绿）。

## 改动的文件

- `fetcher/fetcher/cli/main.py`（+63 行纯追加：daemon parser + main() 拦截分支 + `_run_daemon()`）
- `fetcher/tests/test_cli.py`（新增，5 用例）

commit：`24cfe7d feat(fetcher): CLI 新增 daemon 子命令（1688 contact 常驻模式装配）`（同时收录 task-2.3-brief.md，与前序 Step 收录 brief 的做法一致）。

## 自查发现

- 对照验收清单逐条核验：daemon --help 正常 ✓；既有子命令 --help/行为无变化（diff 纯追加）✓；provider/policy/Engine 装配与站点分支逐项一致 ✓；解析层测试含 --queue 默认值与站点挂载防回归 ✓；全量无回归 ✓。
- 约束核验：只动了 main.py + 一个测试文件；未碰 engine/loop/daemon_task/db/站点插件；未提取公共函数（装配段短，逐字复制站点分支片段比抽公共函数更符合「既有调用点行为逐字等价」要求——两处的注释也保持了一致）。
- 防假阳性：RED 阶段失败信息确为「daemon 未注册」（invalid choice），非测试本身错误。

## 疑虑

1. **num/limit 超出 brief 字面清单**：brief parser 节只写「add_common_args 全套 + --queue」，但 config_from_args 必读 num/limit 且 brief §3 明确 --limit 是冒烟收工手段，故补挂了两者（contact 口径默认值）。若评审认为应更克制，可改为 `set_defaults(num=10, limit=0)` 隐藏参数，但那样 --limit 冒烟手段不可达，不推荐。
2. **prepare 调用位置**：brief 步骤清单未列 prepare，但站点分支有且 DaemonTaskProxy.prepare 即为此设计（SPEC §3.3）；镜像站点分支位置调用。inner.prepare 内的 scoped `reset_in_progress` 会先于 daemon 分支的无过滤 reset 执行一次，幂等无害。
3. 冒烟实测（真跑 daemon + --limit）不属于本 Step 验收范围（PLAN 归 Step 3.x），未执行。
