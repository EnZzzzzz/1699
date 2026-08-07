# Step 1.3 完成报告 — identity 诞生点拼前缀 + engine 注入 + 既有测试键格式更新

> commit: `68ef08e` feat(identity-p2): Step 1.3 identity 诞生点拼前缀 + engine 注入 + 既有测试键格式更新

## 改动清单（8 文件，+113/-15 行）

### 生产代码（3 文件）

| 文件 | 改动 | 改前 | 改后 |
|---|---|---|---|
| `fetcher/fetcher/net/browser.py` | `BrowserManager.__init__` 加必传 `site_name: str`（在 `store` 后、`provider` 前） | 无 site_name 参数 | `site_name: str`（必传，无默认值） |
| | `launch()` :221 直连 identity | `identity = "direct"` | `identity = f"{self.site_name}:direct"` |
| | `launch()` :237 代理 identity | `identity = exit_ip` | `identity = f"{self.site_name}:{exit_ip}"` |
| `fetcher/fetcher/control/engine.py` | `Engine.__init__` 加 `site_name: str \| None = None` + guard | 无 site_name 参数 | `site is not None and site_name is None` → RuntimeError |
| | `_make_browser_manager` 透传 site_name | 不传 site_name | `site_name=self.site_name or "unknown"` |
| `fetcher/fetcher/cli/main.py` | 站点分支 Engine 构造 | `Engine(cfg, task, site=site, ...)` | 加 `site_name=args.site` |
| | daemon 分支 Engine 构造 | `Engine(cfg, task=task, site=site, ...)` | 加 `site_name="1688"` |

### 测试更新（5 文件）

| 文件 | 改动内容 |
|---|---|
| `fetcher/tests/test_browser_fresh.py` | 3 处 `BrowserManager(...)` 构造加 `site_name="1688"`；新增 `LaunchPrefixedIdentityTest`（2 个 TDD 用例） |
| `fetcher/tests/test_control_loop.py` | MockBrowserManager 默认 identities：`"1.1.1.1"` → `"1688:1.1.1.1"` 等；`test_swap_ip` 断言 `"2.2.2.2"` → `"1688:2.2.2.2"`；`test_login_wall_burns_identity` Cookie 键 `"1.1.1.1"` → `"1688:1.1.1.1"` |
| `fetcher/tests/test_daemon_task.py` | MockBrowserManager launch identity `"1.1.1.1"` → `"1688:1.1.1.1"` |
| `fetcher/tests/test_cooldown.py` | MockBrowserManager launch identity `"1.1.1.1"` → `"1688:1.1.1.1"` |
| `fetcher/tests/test_engine.py` | `test_allocated_channel_threaded_to_browser_manager` Engine 构造加 `site_name="1688"` |

## TDD 证据

### RED 阶段

```
命令：python -m pytest tests/test_browser_fresh.py::LaunchPrefixedIdentityTest -x -q
失败输出：
  TypeError: BrowserManager.__init__() got an unexpected keyword argument 'site_name'
```
**为何符合预期**：BrowserManager 尚未接受 `site_name` 参数 → 构造即失败，证实新测试能探测到缺失。

### GREEN 阶段

```
命令：python -m pytest tests -x -q
通过输出：
  275 passed, 2 subtests passed in 15.24s
```
新增的 2 个 TDD 用例：
1. `test_launch_produces_prefixed_identity_proxy_mode` — 代理模式 identity == `"1688:1.2.3.4"`
2. `test_launch_produces_prefixed_direct_direct_mode` — 直连模式 identity == `"1688:direct"`

## 拼键唯一性 grep 证据

```
$ grep -rn 'f"{self.site_name}' fetcher/ tests/
fetcher/net/browser.py:221:        identity = f"{self.site_name}:direct"
fetcher/net/browser.py:237:            identity = f"{self.site_name}:{exit_ip}"
```

**仅此两处**。engine/cli 只透传不拼键；loop/atoms/db 经 `ctx.identity` 消费带前缀键（Step 1.2 的 bare_identity/is_direct 修正点已埋好）。

## 测试键格式更新清单

| 测试文件 | 旧键格式 | 新键格式 | 变更点 |
|---|---|---|---|
| `test_browser_fresh.py` | `"direct"` | `"1688:direct"` | TDD 断言 |
| | `"1.2.3.4"` | `"1688:1.2.3.4"` | TDD 断言 |
| `test_control_loop.py` | `("1.1.1.1", "2.2.2.2", "3.3.3.3")` | `("1688:1.1.1.1", "1688:2.2.2.2", "1688:3.3.3.3")` | MockBrowserManager 默认 identities |
| | `"2.2.2.2"` | `"1688:2.2.2.2"` | swap_ip 断言 |
| | `"1.1.1.1"`（Cookie 键） | `"1688:1.1.1.1"` | login_wall burn 预置 |
| `test_daemon_task.py` | `"1.1.1.1"` | `"1688:1.1.1.1"` | MockBrowserManager launch |
| `test_cooldown.py` | `"1.1.1.1"` | `"1688:1.1.1.1"` | MockBrowserManager launch |

**语义断言保持**：隔离/burn/统计的语义不变（LoginWall burn 仍清空 Cookie、swap 仍换 IP 并置 warm、cooldown 仍执行等待），只是键带前缀。

## 全量测试结果

```
275 passed, 2 subtests passed in 15.24s
```

（基线 273 + 新增 2 个 TDD 用例）

## 改动文件

```
fetcher/fetcher/cli/main.py
fetcher/fetcher/control/engine.py
fetcher/fetcher/net/browser.py
fetcher/tests/test_browser_fresh.py
fetcher/tests/test_control_loop.py
fetcher/tests/test_cooldown.py
fetcher/tests/test_daemon_task.py
fetcher/tests/test_engine.py
```

## 自查

- [x] 拼键只出现在 browser.py launch 的两处赋值
- [x] site_name 必须是注册名（"1688"），不是插件 name（"alibaba1688"）
- [x] Engine guard：site 非空时 site_name 必须非空
- [x] BrowserManager.site_name 必传（无默认值，构造时缺失即报错）
- [x] 指纹输入保持裸 IP（`bare_identity(identity)` 已由 Step 1.2 埋好，本步未碰）
- [x] 全量 275 passed 无回归
- [x] 不碰 fetcher/vendor/wa-check/、platform/、scraper/、util/、生产库
- [x] 未做 Step 2 内容（Cookie 域过滤收紧、_migrate 迁移）
- [x] 只做 brief 要求的事，不多不少
- [x] git add 显式列文件（8 个），未使用 -A/`.`

## 疑虑

无。

---

## 修复轮 1（reviewer 反馈）

> commit: `d96f977` feat(identity-p2): Step 1.3 修复轮1 — C1 _build_engine 抽辅函+C2 guard 测试+I1 docstring+M1 显式 nil-guard

### C1 ADDRESSED — CLI 装配无测试触达（方案 a：抽辅函）

**改前**：`main()` 与 `_run_daemon()` 各自在 inline 构造 `Engine(..., site_name=...)`，无测试触达。

**改后**：
- `cli/main.py` 新增 `_build_engine(cfg, task, site, provider, policy, site_name)` 纯装配辅助函数（注释中文），两个分支统一经它装配。
- `tests/test_cli.py` 新增 `BuildEngineTest`（3 条）：
  1. `test_site_name_passed_to_engine_site_branch` — site_name="1688" → engine.site_name=="1688"
  2. `test_site_name_passed_to_engine_daemon_branch` — daemon 硬编码 "1688" 路径验证
  3. `test_site_name_None_allowed` — site=None 时 site_name 可为 None

### C2 ADDRESSED — Engine guard 无测试

**改后**：`tests/test_engine.py` 新增 3 条：
1. `test_site_without_site_name_raises_runtime_error` — `Engine(site=MagicMock(), site_name=None)` → RuntimeError，消息包含 "site_name 必传"
2. `test_site_with_site_name_constructs_successfully` — 正常对照，`engine.site_name == "1688"`
3. `test_site_none_without_site_name_constructs_successfully` — site=None 时不触发 guard

### I1 ADDRESSED — browser.py docstring 缺 site_name

**改前**：`BrowserManager(cfg, store, provider=QingGuoProvider())`（缺 site_name → TypeError）
**改后**：`BrowserManager(cfg, store, site_name="1688", provider=QingGuoProvider())`

### M1 ADDRESSED — nil-guard 显式化

**改前**：`site_name=self.site_name or "unknown"`
**改后**：`site_name=(self.site_name if self.site_name else "unknown")`

### 测试结果

```
命令：cd fetcher && python -m pytest tests -x -q
输出：281 passed, 2 subtests passed in 11.43s
```

新增 6 条测试（C1: 3 + C2: 3），全量无回归。

### 改动文件（本轮）

```
fetcher/fetcher/cli/main.py         (+14/-6)
fetcher/fetcher/control/engine.py   (+2/-1)
fetcher/fetcher/net/browser.py      (+2/-1)
fetcher/tests/test_cli.py           (+42/-1)
fetcher/tests/test_engine.py        (+32/-0)
```
