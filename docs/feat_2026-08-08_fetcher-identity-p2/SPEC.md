# SPEC — identity (site, IP) 分桶（P2）

> 上游设计：docs/scheduler-architecture.md §7（本 SPEC 对齐该节并做两处有据修正，见 §3.5/§3.6）
> 前置：daemon P0 + 冷却迁移 P1 已合并 main
> 本文档是 P2 的需求与设计唯一来源；评审通过后相对稳定，变更在文末「变更记录」追加。

## 1. 背景与目标

当前 `identity = 出口 IP`，Cookie、风控簿记、请求预算全部按 IP 记账。P3 要让一个消费者在同一 IP 上跨站点填充（1688 冷却时去爬 madeinchina），前提是同 IP 多站点的身份数据互不污染。

**P2 的目标：identity 键升级为 `f"{site}:{ip}"`，同 IP 两站点 Cookie/簿记互不污染；单站点行为与现状完全等价。**

- 改造后 1688 的 Cookie 落在 `1688:1.2.3.4` 桶、madeinchina 落在 `madeinchina:1.2.3.4` 桶，burn/统计/预算互不影响；
- 单站点（现状唯一运行形态）下行为逐字等价：同样的 Cookie 信任链、同样的指纹、同样的簿记口径。

## 2. 范围与非目标

### 2.1 范围（P2 做）

1. identity 键改造：诞生点（`net/browser.py` launch，:233 一带）拼 `f"{site}:{exit_ip}"`；site 经 `engine.py` 注入 BrowserManager（engine 已持有 `self.site`，:113-123）；直连为 `f"{site}:direct"`。
2. 隐藏使用点修正（探索已定位，§4 逐条）：`check_ip_fresh` 裸 IP 比较、`"direct"` 字面量三处、DB 报表兼容。
3. Cookie 域过滤收紧：`Session.close()` 回写与 `save_from_context` 同语义（按 store.domain 过滤），保证桶内只有本站 Cookie。
4. `_migrate()` 一次性数据迁移：cookies 表存量行按 Cookie 自身 domain 列加站点前缀（幂等）。
5. 隔离性单测（同 IP 两站点互不污染）+ 既有测试键格式更新 + 等价性冒烟。

### 2.2 非目标（P2 明确不做）

- **BrowserContext 多站点隔离**：路线图 §10 P2 原含此项，裁定为 P3 内容——没有多队列（P3）之前，一个消费者只服务一个站点，多 context 机制是死代码；且 CloakBrowser 席位语义（按进程）决定多 context 方案可行性，应随 P3 一起验证。
- **指纹按 (site, IP) 生成**：不采用，维持按裸 IP（裁定与理由见 §3.5）。
- **种子身份池认领粒度**：维持每 worker 一份、指纹按种子名（现状）；跨站种子隔离随 P3。
- **ip_stats / ip_events 存量行迁移**：历史统计行保持裸 IP 键（统计性质，无法按站点干净拆分），新行自然带前缀；tmd 报表把新旧键当不同身份行展示，可接受。
- **平台侧任何改动**：runner 日志正则与前端分色对带冒号键兼容（§4 假设 4 验证），展示粒度变化 P4 再统一。
- **多队列调度、item 挂起**：P3。

## 3. 关键设计

### 3.1 键格式与注入点

- 键：`f"{site}:{ip}"`，site 用站点注册名（`register_site("1688", ...)`、`register_site("madeinchina", ...)` 等，与 `work_items.site` 同口径）；直连 `f"{site}:direct"`。
- 注入点：`engine.py` 的 `_make_browser_manager`（:113）把 site 注册名传给 BrowserManager；identity 诞生点（`browser.py:233` 一带，launch 拿到出口 IP 处）拼前缀。**仅此一处拼键**——loop/atoms/db 全链路经 `ctx.identity` 消费，零改动。
- site 注册名来源（Step 1.1 回填）：插件对象的 `name` 属性**不可直接用于拼前缀**——Alibaba1688Plugin.name = `"alibaba1688"`（`fetcher/fetcher/sites/alibaba1688/__init__.py:27`），与注册名 `"1688"`（同文件:85 `register_site("1688", Alibaba1688Plugin)`）不一致。其余四站点一致（madeinchina/yiwugo/taobao/facebook 的 `plugin.name == register_site(name)`）。**方案**：新增 `site_name` 参数字段，由 CLI（`args.site`，`cli/main.py:174`）/ daemon（硬编码 `"1688"`，`cli/main.py:215`）经 `Engine.__init__` → `_make_browser_manager` 透传给 `BrowserManager`，后者在 launch 拼前缀时使用。这样保证 site 与 `work_items.site` 同口径。
- identity 诞生点（Step 1.1 回填）：`browser.py:217` `identity = "direct"`（默认值）；`browser.py:233` `identity = exit_ip`（代理分支覆盖）。**仅此一处**——`relaunch()` 调用 `session.close()` 后调 `self.launch()`（`browser.py:344-384`），identity 始终由 launch 重新生成，不从旧 session 携带。P2 拼前缀即在此两处：`f"{site_name}:direct"` / `f"{site_name}:{exit_ip}"`。

### 3.2 辅助函数（`core/session.py` 模块级）

```python
def bare_identity(identity: str) -> str:
    """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回（兼容旧键/直连旧值）。"""
    return identity.split(":", 1)[1] if ":" in identity else identity

def is_direct(identity: str) -> bool:
    return bare_identity(identity) == "direct"
```

（实现细节以 Step 1.1 读码为准：若现有键里可能出现其他含冒号形态需另议——IPv4/域名/"direct"/"site:xxx" 均安全。）

### 3.3 隐藏使用点修正清单（探索报告 §结论，逐条）

| # | 位置 | 现状 | 修正 |
|---|---|---|---|
| 1 | `net/browser.py:196` `check_ip_fresh` | `cur_ip != session.identity` 裸 IP 比带前缀键→**永远不等、每轮误判 IP 轮换** | 改比 `bare_identity(session.identity)` |
| 2 | `control/loop.py:451` | `identity != "direct"`（登录墙 burn 保护） | 改 `not is_direct(identity)` |
| 3 | `atoms/identity_ops.py:25` | 同上 | 同上 |
| 4 | `db.py:684` `ip_event_summary` | `WHERE identity != 'direct'` | 改 `NOT LIKE '%:direct' AND identity != 'direct'`（新旧键都滤） |
| 5 | `db.py:772` `format_tmd_report` | 列宽 `:<17`（按裸 IP 长度） | 列宽自适应或放宽到容纳 `madeinchina:1.2.3.4`（22） |
| 6 | `net/browser.py:299` 指纹 | `seed_kit["name"] if seed_kit else identity` | 非种子分支改传 `bare_identity(identity)`——**指纹输入保持裸 IP，与迁移前逐字一致**（§3.5） |
| 7 | `platform/server/app/runner.py:137` + `web/.../task-ui.tsx:112` | 日志正则提取 identity 做 worker 分色 | 不改代码，验证正则兼容（§4 假设 4） |

内存键（`ip_req`/`budget_stuck`/`SeedBurnTracker.burn_ips`）随字符串自然分桶，零改动——「同 IP 跨站预算/烧毁互不连带」正由此获得。

### 3.4 Cookie 域过滤收紧 + 数据迁移

- `Session.close()`（session.py:50-54）回写时按 `store.domain` 过滤（与 `save_from_context` 同语义），注释说明：多站共存前提下的桶纯度保证。
- `_migrate()` 追加幂等迁移（仿既有「探测+回填」模式，:225-250）：cookies 表中 `identity NOT LIKE '%:%'` 的存量行，按 Cookie 自身 `domain` 列映射站点前缀。**映射清单（Step 1.1 回填，2026-08-08 生产库 18095 行、6971 个 distinct domain 只读统计）**：

  | LIKE 模式 | 站点前缀 | 覆盖行数 | 覆盖域例 |
  |---|---|---|---|
  | `%1688.com%` | `1688:` | ~6600+ | `.1688.com`(5413), `insights.1688.com`(399), `.air.1688.com`(373), `assets.1688.com`(351), `s.1688.com`(109), `widget.1688.com`(103), `work.1688.com`(103), `h5api.m.1688.com`(95), `dj.1688.com`(15), `detail.1688.com`(3) 及 ~6961 个 shop 子域 |
  | `%made-in-china.com%` | `madeinchina:` | ~2992 | `.made-in-china.com`(1695), `.cn.made-in-china.com`(651), `cn.made-in-china.com`(431), `membercenter.cn.made-in-china.com`(215) |
  | `%taobao.com%` | `taobao:` | ~95 | `.taobao.com`(72), `login.taobao.com`(23) |
  | `%yiwugo.com%` | `yiwugo:` | 4 | `.yiwugo.com`(4) |

  逐映射一条 `UPDATE cookies SET identity = <prefix> || identity WHERE identity NOT LIKE '%:%' AND domain LIKE '<pattern>'`；**检测顺序：先 made-in-china 再 1688（二者无重叠，但仍先长后短更安全）。**

- **无法映射的第三方域（保持原样，自然过期）**：

  | 域 | 行数 | 处置 |
  |---|---|---|
  | `.mmstat.com` | 544 | 阿里系埋点/统计域，非站点专属——保持原样 |
  | `.ynuf.aliapp.org` | 166 | 阿里系生态域，非站点专属——保持原样 |
- **运维注意（行为后果）**：迁移生效后，仍在跑的旧代码进程按裸 IP 键查找会找不到已加前缀的 Cookie（信任链对它们失效、按白板重启）。合并部署应在活爬虫停跑窗口进行，或接受运行中爬虫一次性重置。新代码进程读旧库：未迁移行（迁移前旧进程新写入的）按白板处理，无副作用。

### 3.5 对 scheduler-architecture §7 的修正一：指纹不按 (site, IP)

§7 原写「指纹种子按 (site, IP) 生成」。**裁定为维持按裸 IP**，理由：

1. 指纹输入若改 `site:ip`，同一 IP 的指纹随之改变——已迁移 Cookie 会配上新指纹，Cookie/指纹错配本身就是风控信号，迁移反而毁掉信任链；
2. 真实用户是一台设备（一份指纹）访问多个站点，指纹随设备不随站点，按裸 IP 更拟人；
3. §7 真正要防的「同指纹双会话并发」是同站点场景，已由结构保证（一通道一消费者、一消费者一时刻一个工作项），跨站同指纹无相关风险（站点间不共享指纹数据）。

### 3.6 对 §7 的修正二：CloakBrowser 席位语义

§7 写「席位按进程还是 context 计数需实测」。已读已安装包源码（cloakbrowser 0.5.2 `license.py:368`）：会话席位由**浏览器二进制进程**向服务端租约（退出码 76=session limit），注释与 API（`/api/license/session/count`）均指向按进程计数。**依据升级为「包源码证据」**，服务端实测仍随 P3 多 context 落地前做一次（P2 不涉及多 context）。

### 3.7 状态流（职责分配）

- identity 写入：唯一诞生点 `browser.py` launch/relaunch（拼前缀）；`Session.identity` 运行时不变。
- Cookie 桶读写：IdentityStore（load/save/burn/save_from_context）+ `Session.close()`；键全来自 `session.identity`，无第二来源。
- 簿记读写：loop `_bookkeep_*`（写）、db 报表（读）；键同上。
- 迁移：`_migrate()` 在 ShopDB 构造时幂等执行，谁先打开新库谁先跑（WAL 短事务，与活爬虫并发安全——迁移只 UPDATE identity 列，不改其他行）。

## 4. 契约与行为后果（假设与验证）

| # | 行为假设 | 依据 | 验证方式 |
|---|---|---|---|
| 1 | 站点注册名可从 engine 的插件对象获得（用于拼前缀） | **已读码验证**：插件 `name` 属性对 1688 为 `"alibaba1688"`（`alibaba1688/__init__.py:27`），与注册名 `"1688"`（同文件:85）不一致——插件对象无注册名字段。改为 CLI/daemon 透传 `args.site` / `"1688"`（`cli/main.py:174/215`）经 Engine 新参到 BrowserManager（详见 §3.1） | Step 1.1 已回填 §3.1 |
| 2 | cookies 迁移的 domain→site 映射清单完整覆盖存量数据 | **已读生产库验证**（2026-08-08，`1688.db` 只读：18095 行、6971 distinct domain、637 identity，0 行含冒号）。映射清单详见 §3.4，无法映射的第三方域（`.mmstat.com` 544 行、`.ynuf.aliapp.org` 166 行）保持原样自然过期 | Step 1.1 已回填 §3.4 |
| 3 | 拼前缀后 `check_ip_fresh`/`"direct"` 字面量/报表是全部受损点 | 已读码验证（探索报告逐条 file:line） | §3.3 清单即修复范围；终审 grep 复核 |
| 4 | 平台日志正则 `identity=([^\s)，、]+)` 兼容带冒号键 | 推断（冒号不在排除字符集） | Step 3 冒烟时跑一条断言验证（python -c 正则匹配），报告平台侧零改动结论 |
| 5 | 迁移在活爬虫并发写下安全（WAL 短事务 UPDATE identity 列） | 项目约定（AGENTS.md §4：短事务+busy_timeout） | 单测模拟迁移幂等性；部署窗口要求写入 README/AGENTS 提示 |

## 5. 验收标准（P2 整体）

1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新隔离性用例与更新的键格式断言）。
2. 隔离性单测：同一裸 IP 两站点——Cookie 各落各桶、load 不串、burn 一站不殃及另一站、ip_stats/ip_events 分行、内存预算键分开。
3. 兼容性：同裸 IP 的指纹参数与迁移前逐字一致（md5 输入=bare ip）；`check_ip_fresh` 对 `1688:1.2.3.4` vs `1.2.3.4` 判定相等（不误判轮换）。
4. 迁移幂等：对新格式库重复执行 `_migrate` 零变化；迁移后 1688 Cookie 可被新键正常 load。
5. 冒烟：临时库 `python -m fetcher daemon --db <临时库> --workers 1 --limit 2` 直连跑通，cookies 表出现 `1688:direct` 桶、抓取行为与 P1 一致；生产库零污染。
6. grep 验收：全包 `!= "direct"` / `== "direct"` 对 identity 的字面量比较只剩 is_direct/bare_identity 封装内。

## 6. 变更记录

- **2026-08-08 Step 3.1 冒烟发现（summary 路径修复）**：冒烟收尾发现 `Task.summary()`（各站点 exit 汇总）内部 `ShopDB()` 不带路径默认开生产库——P2 的 `_migrate` cookies 迁移使该既有路径获得一次性写副作用（冒烟期间已提前触发生产库迁移，完整幂等无数据损失）。已修复：Task.summary 签名透传 `db_path`，engine 传 `config.resolved_db_path()`，8 处站点实现同步（`fix(identity-p2): summary 透传 db_path`）；临时库运行不再触碰生产库。生产库迁移已实际发生（17385 行带前缀 + 710 行第三方域保持裸键），部署窗口后果（旧代码白板重启一次）提前生效。

- **2026-08-08 Step 1.1 回填**：§4 假设 1 被推翻——插件对象的 `name` 属性不可直接用于拼前缀（1688 的 `plugin.name="alibaba1688"` ≠ 注册名 `"1688"`，见 `alibaba1688/__init__.py:27` vs `:85`）。该假设原文为「站点注册名可从 engine 的插件对象获得」，实际无法获得，改为 CLI/daemon 透传方案。方案：CLI/daemon 把注册名（`args.site` / `"1688"`）透传给 BrowserManager（§3.1）。§4 假设 2 已验证——生产库 domain→site 映射清单完整回填 §3.4（含无法映射第三方域 `.mmstat.com`、`.ynuf.aliapp.org`）。identity 诞生点精确行号 `browser.py:217/233` 确认——relaunch 不携带旧 identity，唯一诞生点即 launch（§3.1）。
