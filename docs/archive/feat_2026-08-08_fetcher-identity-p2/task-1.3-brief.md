# Step 1.3 brief — identity 诞生点拼前缀 + engine 注入 + 既有测试键格式更新

> 来源：PLAN.md Phase 1 Step 1.3。本文本是你的需求唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699

## 内容

### ① site_name 注入链路（Step 1.1 已回填的方案，SPEC §3.1）

- `fetcher/fetcher/control/engine.py`：`Engine.__init__` 加新参 `site_name: str | None = None`（存 `self.site_name`）；`_make_browser_manager`（:113）在真实构造路径把 `site_name` 传给 `BrowserManager`。`browser_manager_factory` 注入路径**不改签名**（测试用 factory 返回 mock，不涉及拼前缀）。
- `fetcher/fetcher/net/browser.py`：`BrowserManager.__init__` 加**必传**参数 `site_name: str`（存 `self.site_name`；**无默认值**——宁可在构造时报错，也不许拼出 `alibaba1688:` 或空前缀）。`Engine` 侧若 `site is not None` 而 `site_name` 缺失，报清晰错误（如 RuntimeError「site_name 必传（CLI/daemon 传入注册名）」）。
- `fetcher/fetcher/cli/main.py`：
  - 站点分支（:198 `Engine(cfg, task, site=site, provider=provider, policy=policy)`）→ 加 `site_name=args.site`（args.site 即注册名，Step 1.1 已确认 :174 `site = get_site(args.site)`）
  - daemon 分支（:242 `Engine(cfg, task=task, site=site, provider=provider, policy=policy)`）→ 加 `site_name="1688"`（注册名，与 DaemonTaskProxy 的 site="1688" 同口径）

### ② identity 诞生点拼前缀（SPEC §3.1，仅此一处）

`fetcher/fetcher/net/browser.py` `launch()` 的两处 identity 赋值（Step 1.1 确认）：
- `:217` `identity = "direct"` → `identity = f"{self.site_name}:direct"`
- `:233` `identity = exit_ip` → `identity = f"{self.site_name}:{exit_ip}"`

**拼键只许在这两处**。relaunch 调 launch 重建 identity（Step 1.1 确认不携带旧值），无需其他改动。launch 内后续 `store.load/save/record_event/seed_from_json`、`Session(identity=...)`、日志全部自动带前缀——零改动。loop/atoms/db 经 `ctx.identity` 消费，Step 1.2 的修正点已保证正确。

### ③ 既有测试键格式更新（PLAN 明确要求）

- `fetcher/tests/test_browser_fresh.py`：`BrowserManager(config=..., store=..., log=...)` 构造处全部加 `site_name="1688"`；`test_launch_passes_bare_identity_to_fingerprint_args` 的断言（直连指纹入参 == "direct"）在拼前缀后依然成立（bare_identity("1688:direct") == "direct"），保持即可。
- `fetcher/tests/test_control_loop.py`：MockBrowserManager 的 identities 从裸键改为带前缀键（如 `("1688:1.1.1.1", "1688:2.2.2.2")`），`test_swap_ip_replaces_session_and_restarts_warm` 的断言 `ctx.session.identity == "2.2.2.2"` 改为 `"1688:2.2.2.2"`；`test_login_wall_burns_identity_at_detection` 的预置 Cookie 键 `"1.1.1.1"` 同步改 `"1688:1.1.1.1"`；`test_login_wall_does_not_burn_prefixed_direct` 已用 `"1688:direct"`，保持。
- `fetcher/tests/test_daemon_task.py`：mock launch 的 `identity="1.1.1.1"`（:121 一带）改 `"1688:1.1.1.1"`，并核对相关断言。
- 其他构造 `BrowserManager`/`Engine` 或断言 identity 的测试：grep 全量扫描（`BrowserManager(`、`Engine(`、`session.identity`、`identity=`）逐个适配；涉及 `Engine(..., site=...)` 的测试若走真实 BrowserManager 路径需加 site_name。
- **语义断言保持**：隔离/burn/统计的语义不变，只是键带前缀。

### ④ TDD

先写失败测试（如：launch 产出 prefixed identity——mock cloak_launch 后断言 session.identity == "1688:1.2.3.4"；engine 把 site_name 传给 manager——注入 spy factory 或断言真实构造路径），亲眼看红，再实现转绿。测试构造 BrowserManager 用 MagicMock store、mock `_query_exit_ip_with_retry` 与 cloak_launch（参考 test_browser_fresh.py 已有模式；有头/真实浏览器不适用，本步全 mock）。

## 背景

P2：identity 键升级为 `f"{site}:{ip}"`。Step 1.2 已把 6 处按字符串工作的修正点埋好（bare_identity/is_direct 等）；本步是**唯一拼键处**——拼上之后，Cookie/簿记/内存键全链路自动按 site 分桶。单站点行为等价性：同 IP 下指纹输入（bare_identity）与迁移前逐字一致，无前缀旧键的读取路径由 Step 2.1 迁移衔接（下一步）。

## 验收

- [ ] 拼键只出现在诞生点一处（grep 证据：`f"{self.site_name}:` 只出现在 browser.py launch 的两处赋值；engine/cli 只透传不拼）
- [ ] 全量无回归；既有测试的语义断言（隔离/burn/统计）在带前缀键下仍成立
- [ ] `cd fetcher && python -m pytest tests -x -q` 全绿

## 约束

- 只改 `fetcher/` 下代码与测试；不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/、生产库 .cache/1688.db
- 不做 Step 2 内容（不做 Cookie 域过滤收紧、不做 _migrate 迁移——那是 Step 2.1）
- **commit 纪律**：git add 显式列文件（禁止 -A/`.`，工作区有另一功能未提交改动）；commit 信息 `feat(identity-p2): Step 1.3 …`；自查 `git status` / `git diff --cached --stat`
- 注释中文、遵循既有模式；只改任务范围内的代码

## 报告

完整报告写入 `docs/feat_2026-08-08_fetcher-identity-p2/task-1.3-report.md`：
- 每处改动的改前/改后
- **TDD 证据**：RED（命令 + 失败输出 + 为何符合预期）/ GREEN（命令 + 通过输出）
- 拼键唯一性 grep 证据
- 测试键格式更新清单（哪些测试改了、改了什么）
- 全量测试结果（总数）、改动的文件、commit（短 SHA + 标题）
- 自查发现与疑虑
