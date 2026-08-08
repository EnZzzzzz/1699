# Step 1.2 brief — 辅助函数 + 隐藏点修正（SPEC §3.3 清单 #1-#6）

> 来源：PLAN.md Phase 1 Step 1.2。本文本是你的需求唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699

## 内容

### ① `core/session.py` 模块级辅助函数（SPEC §3.2）

在 `fetcher/fetcher/core/session.py` 模块级（Session 类外）加两个函数：

```python
def bare_identity(identity: str) -> str:
    """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回（兼容旧键/直连旧值）。"""
    return identity.split(":", 1)[1] if ":" in identity else identity

def is_direct(identity: str) -> bool:
    return bare_identity(identity) == "direct"
```

（注释按项目习惯写中文，说明「指纹/保鲜检查等需要裸 IP 的场合用 bare_identity」）

### ② 隐藏使用点修正（§3.3 清单 #1-#6，逐条）

| # | 位置（当前代码） | 修正 |
|---|---|---|
| 1 | `net/browser.py` `check_ip_fresh`：`if cur_ip != session.identity:`（:196 一带） | 改 `if cur_ip != bare_identity(session.identity):`（**不误判 IP 轮换**；log 消息里的 `{session.identity}` 保持原样展示即可） |
| 2 | `control/loop.py:451`：`if login_wall and identity != "direct" and ctx.store is not None:` | 改 `if login_wall and not is_direct(identity) and ctx.store is not None:` |
| 3 | `atoms/identity_ops.py:25`：`if identity == "direct":` | 改 `if is_direct(identity):` |
| 4 | `db.py:684` `ip_event_summary`：`WHERE identity != 'direct'` | 改 `WHERE identity NOT LIKE '%:direct' AND identity != 'direct'`（**新旧键都滤**；SQL 里的 `!= 'direct'` 字面量按 §3.3#4 明确保留） |
| 5 | `db.py` `format_tmd_report`：列宽 `:<17`（表头 `{'出口IP':<17}` 与数据行 `{r['identity']:<17}` 两处） | 放宽到容纳 `madeinchina:1.2.3.4`（SPEC 建议 22；两处同步改） |
| 6 | `net/browser.py` launch 指纹：`args=fingerprint_args(seed_kit["name"] if seed_kit else identity)`（:299 一带） | 非种子分支改传 `bare_identity(identity)`——**指纹输入保持裸 IP，与迁移前逐字一致**（SPEC §3.5 铁律，不许改 site:ip） |

**顺序裁定**：先修比较点（1-5），再修指纹（6）；第 6 处是本次最重要的一处，改错会导致已迁移 Cookie 配错指纹。

### ③ TDD（先写失败测试、亲眼看红、再实现转绿）

- 先写 `bare_identity` / `is_direct` 的测试（新文件 `fetcher/tests/test_session_helpers.py` 或并入既有测试文件，看既有组织习惯）：
  - `bare_identity("1688:1.2.3.4") == "1.2.3.4"`、`bare_identity("madeinchina:direct") == "direct"`、`bare_identity("1.2.3.4") == "1.2.3.4"`（无前缀原样）、`bare_identity("direct") == "direct"`
  - `is_direct("direct")` True、`is_direct("1688:direct")` True、`is_direct("1.2.3.4")` False、`is_direct("1688:1.2.3.4")` False
- 每处修正配一条测试（**当前键还没前缀，测试用带前缀字符串直接构造**——函数是按字符串工作的，不依赖键诞生点）：
  - #1：mock `_query_exit_ip_with_retry` 返回 `"1.2.3.4"`，构造 `Session(identity="1688:1.2.3.4", ...)`，断言 `check_ip_fresh` 返回 `(False, ...)`（不触发 relaunch）；裸键 `"1.2.3.4"` 对照同样 `(False, ...)`；返回 `"5.5.5.5"` 时两键都 `(True, ...)`
  - #2：构造登录墙 block 场景（参照 `tests/test_control_loop.py` 既有 block 测试的构造方式），identity 用 `"1688:direct"`，断言**不**触发 burn；`"1.2.3.4"` 对照触发 burn
  - #3：`ClearIdentity().run(ctx, {})`，ctx.identity=`"1688:direct"` → skipped（不清空）；`"1.2.3.4"` → 清空
  - #4：向 ip_events 插 `"direct"`、`"1688:direct"`、`"1.2.3.4"`、`"1688:1.2.3.4"` 四行，断言 `ip_event_summary()` 只含后两者
  - #5：造 ip_stats 行 identity=`"madeinchina:1.2.3.4"`（带 req/ok/blocks），断言 `format_tmd_report()` 输出行中该 identity 完整显示且列不错位（比如断言 identity 子串在、行长度断言或肉眼对齐检查——选可断言的）
  - #6：`fingerprint_args` 对 `"1688:1.2.3.4"` 与 `"1.2.3.4"` 返回相同指纹参数（md5 输入=裸 IP）；launch 链路测试如不便构造可退化为对 `bare_identity` 传参点的单测断言（monkeypatch `fingerprint_args` 记录入参，断言收到的是裸 IP）——优先真行为，mock 兜底
- 跑法：`cd fetcher && python -m pytest tests -x -q`（TDD 阶段先跑聚焦测试，commit 前全量）

## 背景

P2：identity 键将从「出口 IP」升级为「site:出口 IP」（Step 1.3 做，**本步不做**）。本步先埋好所有按字符串工作的修正点与辅助函数——键还没前缀时全部行为与现状逐字等价（`bare_identity` 对无前缀键原样返回），Step 1.3 拼前缀后这些点自动正确。**本步无运行时行为变化。**

## 验收

- [ ] 6 处修正与 §3.3 表一致（含 db.py SQL 保留 `!= 'direct'` 的双滤写法）
- [ ] SPEC §5 第 6 条 grep 达成（此阶段口径：Python 侧对 identity 的 `!= "direct"` / `== "direct"` 字面量比较只剩 is_direct/bare_identity 封装内；db.py:684 的 SQL 字符串按 §3.3#4 豁免）
- [ ] 全量无回归（TDD 先红后绿，report 附 RED/GREEN 证据）

## 约束

- **只改 `fetcher/` 下的代码与测试**；不碰 platform/、不碰 fetcher/vendor/wa-check/、不碰生产库 .cache/1688.db
- **不做 Step 1.3 的内容**：不拼前缀、不改 engine、不给 BrowserManager 加 site_name 参数——那是下一步
- 不动 `scraper/`、`util/` 旧脚本
- **commit 纪律**：工作区有另一功能的未提交改动（platform/*、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_*、platform/server/tests/test_wa_pairing_login.py），**git add 必须显式列文件**，禁止 `-A`/`.`；commit 信息 `feat(identity-p2): Step 1.2 …`；用 `git status` + `git diff --cached --stat` 自查提交范围
- 注释中文、遵循既有代码模式；不重构任务范围外的代码

## 报告

完整报告写入 `docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-report.md`：
- 每处修正的改前/改后
- **TDD 证据**：RED（命令 + 失败输出 + 为什么符合预期）/ GREEN（命令 + 通过输出）
- 全量测试结果（总数）
- 改动的文件、commit（短 SHA + 标题）
- 自查发现与疑虑
