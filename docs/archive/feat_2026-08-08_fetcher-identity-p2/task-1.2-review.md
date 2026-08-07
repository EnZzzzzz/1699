# Step 1.2 修复轮1 scoped re-review 审查包（bfd97d3..892a5e6）

## git log
892a5e6 feat(identity-p2): Step 1.2 修复轮1 — 移除RED注释 + 3边界测试 + 模块级import
838ebc1 docs(identity-p2): Step 1.2 report + review 包

## git diff -U10
diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-review.md b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-review.md
new file mode 100644
index 0000000..d9085ab
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-review.md
@@ -0,0 +1,255 @@
+# Step 1.1 修复轮1 scoped re-review 审查包（5a4c997..5f8764e）
+
+## git log
+5f8764e docs(identity-p2): Step 1.1 修复轮1——行号勘误
+
+## git diff -U10
+diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md b/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md
+index c648465..28b75e5 100644
+--- a/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md
++++ b/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md
+@@ -30,23 +30,23 @@
+ - **种子身份池认领粒度**：维持每 worker 一份、指纹按种子名（现状）；跨站种子隔离随 P3。
+ - **ip_stats / ip_events 存量行迁移**：历史统计行保持裸 IP 键（统计性质，无法按站点干净拆分），新行自然带前缀；tmd 报表把新旧键当不同身份行展示，可接受。
+ - **平台侧任何改动**：runner 日志正则与前端分色对带冒号键兼容（§4 假设 4 验证），展示粒度变化 P4 再统一。
+ - **多队列调度、item 挂起**：P3。
+ 
+ ## 3. 关键设计
+ 
+ ### 3.1 键格式与注入点
+ 
+ - 键：`f"{site}:{ip}"`，site 用站点注册名（`register_site("1688", ...)`、`register_site("madeinchina", ...)` 等，与 `work_items.site` 同口径）；直连 `f"{site}:direct"`。
+-- 注入点：`engine.py` 的 `_make_browser_manager`（:113-123）把 site 注册名传给 BrowserManager；identity 诞生点（`browser.py:233` 一带，launch 拿到出口 IP 处）拼前缀。**仅此一处拼键**——loop/atoms/db 全链路经 `ctx.identity` 消费，零改动。
+-- site 注册名来源（Step 1.1 回填）：插件对象的 `name` 属性**不可直接用于拼前缀**——Alibaba1688Plugin.name = `"alibaba1688"`（`fetcher/fetcher/sites/alibaba1688/__init__.py:17`），与注册名 `"1688"`（同文件:66 `register_site("1688", Alibaba1688Plugin)`）不一致。其余四站点一致（madeinchina/yiwugo/taobao/facebook 的 `plugin.name == register_site(name)`）。**方案**：新增 `site_name` 参数字段，由 CLI（`args.site`，`cli/main.py:198`）/ daemon（硬编码 `"1688"`，`cli/main.py:242`）经 `Engine.__init__` → `_make_browser_manager` 透传给 `BrowserManager`，后者在 launch 拼前缀时使用。这样保证 site 与 `work_items.site` 同口径。
+-- identity 诞生点（Step 1.1 回填）：`browser.py:217` `identity = "direct"`（默认值）；`browser.py:233` `identity = exit_ip`（代理分支覆盖）。**仅此一处**——`relaunch()` 调用 `session.close()` 后调 `self.launch()`（`browser.py:337-366`），identity 始终由 launch 重新生成，不从旧 session 携带。P2 拼前缀即在此两处：`f"{site_name}:direct"` / `f"{site_name}:{exit_ip}"`。
++- 注入点：`engine.py` 的 `_make_browser_manager`（:113）把 site 注册名传给 BrowserManager；identity 诞生点（`browser.py:233` 一带，launch 拿到出口 IP 处）拼前缀。**仅此一处拼键**——loop/atoms/db 全链路经 `ctx.identity` 消费，零改动。
++- site 注册名来源（Step 1.1 回填）：插件对象的 `name` 属性**不可直接用于拼前缀**——Alibaba1688Plugin.name = `"alibaba1688"`（`fetcher/fetcher/sites/alibaba1688/__init__.py:27`），与注册名 `"1688"`（同文件:85 `register_site("1688", Alibaba1688Plugin)`）不一致。其余四站点一致（madeinchina/yiwugo/taobao/facebook 的 `plugin.name == register_site(name)`）。**方案**：新增 `site_name` 参数字段，由 CLI（`args.site`，`cli/main.py:174`）/ daemon（硬编码 `"1688"`，`cli/main.py:215`）经 `Engine.__init__` → `_make_browser_manager` 透传给 `BrowserManager`，后者在 launch 拼前缀时使用。这样保证 site 与 `work_items.site` 同口径。
++- identity 诞生点（Step 1.1 回填）：`browser.py:217` `identity = "direct"`（默认值）；`browser.py:233` `identity = exit_ip`（代理分支覆盖）。**仅此一处**——`relaunch()` 调用 `session.close()` 后调 `self.launch()`（`browser.py:344-384`），identity 始终由 launch 重新生成，不从旧 session 携带。P2 拼前缀即在此两处：`f"{site_name}:direct"` / `f"{site_name}:{exit_ip}"`。
+ 
+ ### 3.2 辅助函数（`core/session.py` 模块级）
+ 
+ ```python
+ def bare_identity(identity: str) -> str:
+     """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回（兼容旧键/直连旧值）。"""
+     return identity.split(":", 1)[1] if ":" in identity else identity
+ 
+ def is_direct(identity: str) -> bool:
+     return bare_identity(identity) == "direct"
+@@ -106,28 +106,28 @@ def is_direct(identity: str) -> bool:
+ 
+ - identity 写入：唯一诞生点 `browser.py` launch/relaunch（拼前缀）；`Session.identity` 运行时不变。
+ - Cookie 桶读写：IdentityStore（load/save/burn/save_from_context）+ `Session.close()`；键全来自 `session.identity`，无第二来源。
+ - 簿记读写：loop `_bookkeep_*`（写）、db 报表（读）；键同上。
+ - 迁移：`_migrate()` 在 ShopDB 构造时幂等执行，谁先打开新库谁先跑（WAL 短事务，与活爬虫并发安全——迁移只 UPDATE identity 列，不改其他行）。
+ 
+ ## 4. 契约与行为后果（假设与验证）
+ 
+ | # | 行为假设 | 依据 | 验证方式 |
+ |---|---|---|---|
+-| 1 | 站点注册名可从 engine 的插件对象获得（用于拼前缀） | **已读码验证**：插件 `name` 属性对 1688 为 `"alibaba1688"`（`alibaba1688/__init__.py:17`），与注册名 `"1688"`（同文件:66）不一致——插件对象无注册名字段。改为 CLI/daemon 透传 `args.site` / `"1688"`（`cli/main.py:198/242`）经 Engine 新参到 BrowserManager（详见 §3.1） | Step 1.1 已回填 §3.1 |
++| 1 | 站点注册名可从 engine 的插件对象获得（用于拼前缀） | **已读码验证**：插件 `name` 属性对 1688 为 `"alibaba1688"`（`alibaba1688/__init__.py:27`），与注册名 `"1688"`（同文件:85）不一致——插件对象无注册名字段。改为 CLI/daemon 透传 `args.site` / `"1688"`（`cli/main.py:174/215`）经 Engine 新参到 BrowserManager（详见 §3.1） | Step 1.1 已回填 §3.1 |
+ | 2 | cookies 迁移的 domain→site 映射清单完整覆盖存量数据 | **已读生产库验证**（2026-08-08，`1688.db` 只读：18095 行、6971 distinct domain、637 identity，0 行含冒号）。映射清单详见 §3.4，无法映射的第三方域（`.mmstat.com` 544 行、`.ynuf.aliapp.org` 166 行）保持原样自然过期 | Step 1.1 已回填 §3.4 |
+ | 3 | 拼前缀后 `check_ip_fresh`/`"direct"` 字面量/报表是全部受损点 | 已读码验证（探索报告逐条 file:line） | §3.3 清单即修复范围；终审 grep 复核 |
+ | 4 | 平台日志正则 `identity=([^\s)，、]+)` 兼容带冒号键 | 推断（冒号不在排除字符集） | Step 3 冒烟时跑一条断言验证（python -c 正则匹配），报告平台侧零改动结论 |
+ | 5 | 迁移在活爬虫并发写下安全（WAL 短事务 UPDATE identity 列） | 项目约定（AGENTS.md §4：短事务+busy_timeout） | 单测模拟迁移幂等性；部署窗口要求写入 README/AGENTS 提示 |
+ 
+ ## 5. 验收标准（P2 整体）
+ 
+ 1. `cd fetcher && python -m pytest tests -x -q` 全绿（含新隔离性用例与更新的键格式断言）。
+ 2. 隔离性单测：同一裸 IP 两站点——Cookie 各落各桶、load 不串、burn 一站不殃及另一站、ip_stats/ip_events 分行、内存预算键分开。
+ 3. 兼容性：同裸 IP 的指纹参数与迁移前逐字一致（md5 输入=bare ip）；`check_ip_fresh` 对 `1688:1.2.3.4` vs `1.2.3.4` 判定相等（不误判轮换）。
+ 4. 迁移幂等：对新格式库重复执行 `_migrate` 零变化；迁移后 1688 Cookie 可被新键正常 load。
+ 5. 冒烟：临时库 `python -m fetcher daemon --db <临时库> --workers 1 --limit 2` 直连跑通，cookies 表出现 `1688:direct` 桶、抓取行为与 P1 一致；生产库零污染。
+ 6. grep 验收：全包 `!= "direct"` / `== "direct"` 对 identity 的字面量比较只剩 is_direct/bare_identity 封装内。
+ 
+ ## 6. 变更记录
+ 
+-- **2026-08-08 Step 1.1 回填**：§4 假设 1 被推翻——插件对象的 `name` 属性不可直接用于拼前缀（1688 的 `plugin.name="alibaba1688"` ≠ 注册名 `"1688"`）。方案：CLI/daemon 把注册名（`args.site` / `"1688"`）透传给 BrowserManager（§3.1）。§4 假设 2 已验证——生产库 domain→site 映射清单完整回填 §3.4（含无法映射第三方域 `.mmstat.com`、`.ynuf.aliapp.org`）。identity 诞生点精确行号 `browser.py:217/233` 确认——relaunch 不携带旧 identity，唯一诞生点即 launch（§3.1）。
++- **2026-08-08 Step 1.1 回填**：§4 假设 1 被推翻——插件对象的 `name` 属性不可直接用于拼前缀（1688 的 `plugin.name="alibaba1688"` ≠ 注册名 `"1688"`，见 `alibaba1688/__init__.py:27` vs `:85`）。该假设原文为「站点注册名可从 engine 的插件对象获得」，实际无法获得，改为 CLI/daemon 透传方案。方案：CLI/daemon 把注册名（`args.site` / `"1688"`）透传给 BrowserManager（§3.1）。§4 假设 2 已验证——生产库 domain→site 映射清单完整回填 §3.4（含无法映射第三方域 `.mmstat.com`、`.ynuf.aliapp.org`）。identity 诞生点精确行号 `browser.py:217/233` 确认——relaunch 不携带旧 identity，唯一诞生点即 launch（§3.1）。
+diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md
+new file mode 100644
+index 0000000..36cefc6
+--- /dev/null
++++ b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md
+@@ -0,0 +1,181 @@
++# Step 1.1 Report — 读码回填
++
++> 日期：2026-08-08 | commit：5a4c997 | 分支：feat/fetcher-identity-p2
++
++## ① 站点注册名来源（SPEC §4 假设 1 → §3.1）
++
++### 证据
++
++**注册表**（`fetcher/fetcher/sites/__init__.py:19-23`）：
++- `register_site(name, plugin_cls)` 将 `name → plugin_cls` 存入 `_SITE_REGISTRY`
++- `get_site(name)` 按注册名取插件实例（`_SITE_REGISTRY[name]()`）
++
++**各站点插件类属性 name vs register_site 实参**：
++
++| 站点 | `Plugin.name` 类属性 | `register_site(name, …)` 实参 | 一致？ |
++|---|---|---|---|
++| 1688 | `"alibaba1688"` (`alibaba1688/__init__.py:27`) | `"1688"` (同文件:85) | ❌ 不一致 |
++| madeinchina | `"madeinchina"` (`madeinchina/__init__.py:32`) | `"madeinchina"` (同文件:96) | ✅ |
++| yiwugo | `"yiwugo"` (`yiwugo/__init__.py:33`) | `"yiwugo"` (同文件:97) | ✅ |
++| taobao | `"taobao"` (`taobao/__init__.py:29`) | `"taobao"` (同文件:86) | ✅ |
++| facebook | `"facebook"` (`facebook/__init__.py:24`) | `"facebook"` (同文件:51) | ✅ |
++
++**Engine 端**（`fetcher/fetcher/control/engine.py`）：
++- `:42` `self.site = site` — 存储的是插件实例
++- `:49-52` `store_factory` 用 `getattr(site, "cookie_domain", "1688.com")` — 只取 cookie_domain，未取注册名
++- `:113` `_make_browser_manager` 传 homepage 给 BrowserManager，未传站点名
++
++**CLI/daemon**（`fetcher/fetcher/cli/main.py`）：
++- `:174` CLI 分支：`site = get_site(args.site)` — args.site 即注册名（如 `"1688"`）
++- `:215` daemon 分支：`site = get_site("1688")` — 硬编码注册名
++
++### 结论
++
++- **插件对象上拿不到注册名**：`self.site.name` 对 1688 返回 `"alibaba1688"` 而非 `"1688"`
++- **推翻了 SPEC §4 假设 1**（原假设「可从插件对象获得注册名」）
++- **方案**：CLI 传 `args.site`、daemon 传 `"1688"`，经 `Engine.__init__` 新参 `site_name` → `_make_browser_manager` → `BrowserManager`，在 launch 拼前缀
++
++---
++
++## ② domain→site 迁移映射清单（SPEC §4 假设 2 → §3.4）
++
++### 证据：生产库只读统计
++
++```
++SQL: SELECT domain, COUNT(*) FROM cookies GROUP BY domain ORDER BY 2 DESC
++DB:  .cache/1688.db (mode=ro, uri=True)
++总行数: 18095, distinct domain: 6971, distinct identity: 637
++含冒号行: 0（全部无前缀）
++```
++
++### 可映射域（≥3 行）
++
++| LIKE 模式 | 站点前缀 | 覆盖行数 | 关键域 |
++|---|---|---|---|
++| `%1688.com%` | `1688:` | ~6600+ | `.1688.com`(5413), `insights.1688.com`(399), `.air.1688.com`(373), `assets.1688.com`(351), `s.1688.com`(109), `widget.1688.com`(103), `work.1688.com`(103), `h5api.m.1688.com`(95), `dj.1688.com`(15), `detail.1688.com`(3) 及 ~6961 个 shop 子域 |
++| `%made-in-china.com%` | `madeinchina:` | ~2992 | `.made-in-china.com`(1695), `.cn.made-in-china.com`(651), `cn.made-in-china.com`(431), `membercenter.cn.made-in-china.com`(215) |
++| `%taobao.com%` | `taobao:` | ~95 | `.taobao.com`(72), `login.taobao.com`(23) |
++| `%yiwugo.com%` | `yiwugo:` | 4 | `.yiwugo.com`(4) |
++
++**检测顺序：先 `made-in-china` 再 `1688`**（二者无重叠，先长后短更安全）
++
++`taobao` 和 `yiwugo` 与 `1688` 也无重叠。
++
++### 无法映射的第三方域
++
++| 域 | 行数 | 处置 |
++|---|---|---|
++| `.mmstat.com` | 544 | 阿里系埋点/统计域，非站点专属——保持原样（自然过期） |
++| `.ynuf.aliapp.org` | 166 | 阿里系生态域，非站点专属——保持原样（自然过期） |
++
++### 结论
++
++- **§4 假设 2 已验证**：映射清单完整覆盖所有可归属域
++- 544 + 166 = 710 行（3.9%）无法映射到任何站点，保持原样自然过期
++- 迁移 SQL 示例：`UPDATE cookies SET identity = '1688:' || identity WHERE identity NOT LIKE '%:%' AND domain LIKE '%1688.com%'`
++
++---
++
++## ③ identity 诞生点确切代码形态（SPEC §3.1）
++
++### 证据：`browser.py` grep
++
++```
++217:        identity = "direct"
++233:            identity = exit_ip
++314:        session = Session(browser=browser, page=page, identity=identity, ...)
++```
++
++### relaunch 是否重建 identity
++
++`relaunch()`（`browser.py:344-384`）：
++1. 调用 `session.close(store=self.store, log=self.log)` 关闭旧会话
++2. 调用 `self.launch(channel=ch, seed_kit=seed_kit, stop=stop)` 启动全新会话
++3. `launch()` 内部重新生成 identity（direct 或 exit_ip），不从旧 session 携带
++
++**结论：identity 唯一诞生点即 `launch()` 的两处赋值（:217/:233），relaunch 不携带旧 identity。**
++
++### P2 拼前缀时改动点
++
++- `:217` → `identity = f"{site_name}:direct"`
++- `:233` → `identity = f"{site_name}:{exit_ip}"`
++
++仅此两处。
++
++---
++
++## 对 SPEC.md 的修改清单
++
++| 位置 | 改前 | 改后 |
++|---|---|---|
++| §3.1「site 注册名从哪拿」 | "读码确认插件上的字段…Step 1.1 回填" | 插件 name 属性不一致的详细发现 + CLI/daemon 透传方案 |
++| §3.1 新增 | — | identity 诞生点行号确认（:217/:233）+ relaunch 不携带分析 |
++| §3.4 迁移映射 | "确切映射清单 Step 1.1 …核实回填" | 完整四站点映射表 + 第三方域列表 + 检测顺序说明 |
++| §4 假设 1 依据列 | "推断（register_site...）" | "已读码验证：插件 name 属性…不一致…改为 CLI/daemon 透传" |
++| §4 假设 2 依据列 | "推断（现有站点…）" | "已读生产库验证（2026-08-08，18095 行、6971 distinct domain…）" |
++| §6 变更记录 | "（空——评审后变更在此追加）" | 追加 Step 1.1 回填条目（假设 1 推翻、假设 2 验证、诞生点确认） |
++
++---
++
++## 改动文件
++
++| 文件 | 操作 |
++|---|---|
++| `docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md` | 修改（+22 -5） |
++
++## Commit
++
++- **SHA**: `5a4c997`
++- **标题**: `docs(identity-p2): Step 1.1 回填——注册名来源/domain→site映射/identity诞生点`
++- **包含文件**: 仅 `SPEC.md`（已验证 `git diff --name-only HEAD~1..HEAD`）
++
++---
++
++## 修复轮 1（reviewer 指正，2026-08-08）
++
++### 行号修正清单（grep -n 实码验证）
++
++| # | 严重度 | 位置 | 错值 | 正确值 | grep 证据 |
++|---|--------|------|------|--------|-----------|
++| 1 | Critical | SPEC §3.1 → `_make_browser_manager` | `:113-123` | `:113` | `engine.py:113:    def _make_browser_manager` — 改为定义行单行引用 |
++| 2 | Critical | SPEC §3.1/§4 → daemon `get_site` | `cli/main.py:242` | `cli/main.py:215` | `main.py:215:    site = get_site("1688")`；:242 是 `Engine(...)` 装配 |
++| 3 | Critical | SPEC §3.1/§4 → CLI `get_site` | `cli/main.py:198` | `cli/main.py:174` | `main.py:174:    site = get_site(args.site)`；:198 是 `Engine(...)` 装配 |
++| 4 | Critical | SPEC §3.1/§4 → `Alibaba1688Plugin.name` | `alibaba1688/__init__.py:17` | `:27` | `alibaba1688/__init__.py:27:    name = "alibaba1688"` |
++| 5 | Critical | SPEC §3.1/§4 → `register_site("1688",...)` | `同文件:66` | `:85` | `alibaba1688/__init__.py:85:register_site("1688", Alibaba1688Plugin)` |
++| 6 | Important | report 插件表 → madeinchina register_site | `:103` | `:96` | `madeinchina/__init__.py:96` |
++| 7 | Important | report 插件表 → yiwugo register_site | `:94` | `:97` | `yiwugo/__init__.py:97` |
++| 8 | Important | report 插件表 → taobao register_site | `:95` | `:86` | `taobao/__init__.py:86` |
++| 9 | Important | report 插件表 → facebook register_site | `:56` | `:51` | `facebook/__init__.py:51` |
++| 10 | Important | report 插件表 → madeinchina name | `:30` | `:32` | `madeinchina/__init__.py:32` |
++| 11 | Important | report 插件表 → yiwugo name | `:29` | `:33` | `yiwugo/__init__.py:33` |
++| 12 | Important | report 插件表 → facebook name | `:23` | `:24` | `facebook/__init__.py:24` |
++| 13 | Minor | SPEC §3.1 → relaunch 范围 | `browser.py:337-366` | `browser.py:344-384` | `browser.py:344:    def relaunch` → 方法至 :384 raise |
++
++### 内容修正
++
++- **变更记录 §6** 补「假设 1 原文被推翻」事实陈述（reviewer #8）：明确写出原假设「站点注册名可从 engine 的插件对象获得」实际不成立
++
++### 实码验证（grep -n 输出摘要）
++
++```
++alibaba1688/__init__.py:27:    name = "alibaba1688"
++alibaba1688/__init__.py:85:register_site("1688", Alibaba1688Plugin)
++madeinchina/__init__.py:32:    name = "madeinchina"
++madeinchina/__init__.py:96:register_site("madeinchina", MadeInChinaPlugin)
++yiwugo/__init__.py:33:    name = "yiwugo"
++yiwugo/__init__.py:97:register_site("yiwugo", YiwugoPlugin)
++taobao/__init__.py:29:    name = "taobao"
++taobao/__init__.py:86:register_site("taobao", TaobaoPlugin)
++facebook/__init__.py:24:    name = "facebook"
++facebook/__init__.py:51:register_site("facebook", FacebookPlugin)
++main.py:174:    site = get_site(args.site)
++main.py:215:    site = get_site("1688")
++engine.py:113:    def _make_browser_manager(self, store, channel=None) -> BrowserManager:
++browser.py:344:    def relaunch(self, session: Session, channel=None,
++```
++
++### Commit（修复轮 1）
++
++- **SHA**: `db23e5e`
++- **标题**: `docs(identity-p2): Step 1.1 修复轮1——行号勘误`
++- **包含文件**: `SPEC.md` + `task-1.1-report.md`（仅 `docs/feat_2026-08-08_fetcher-identity-p2/` 下）
diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-report.md b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-report.md
new file mode 100644
index 0000000..1811a10
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-report.md
@@ -0,0 +1,147 @@
+# Step 1.2 Report — 辅助函数 + 隐藏点修正（SPEC §3.3 清单 #1-#6）
+
+> 日期：2026-08-08 | 分支：feat/fetcher-identity-p2 | commit：bfd97d3
+
+## 概述
+
+在 `fetcher/` 侧完成 identity 辅助函数 `bare_identity` / `is_direct` 及 6 处隐藏使用点的修正。所有改动按字符串工作，对当前无前缀键行为等价；prefix 拼上后（Step 1.3）这些点自动正确。
+
+## 改动清单
+
+### ① `core/session.py` — 新增模块级辅助函数
+
+```python
+def bare_identity(identity: str) -> str:
+    """剥掉站点前缀；无前缀原样返回（兼容旧键/直连旧值）。"""
+    return identity.split(":", 1)[1] if ":" in identity else identity
+
+def is_direct(identity: str) -> bool:
+    """identity 是否代表直连模式（含 'direct' 与 'site:direct' 两种形态）。"""
+    return bare_identity(identity) == "direct"
+```
+
+### ② 6 处修正（逐条）
+
+| # | 文件 | 位置 | 改前 | 改后 |
+|---|------|------|------|------|
+| 1 | `net/browser.py` | `check_ip_fresh` :196 | `if cur_ip != session.identity:` | `if cur_ip != bare_identity(session.identity):` |
+| 2 | `control/loop.py` | :451 登录墙判定 | `if login_wall and identity != "direct" and ctx.store is not None:` | `if login_wall and not is_direct(identity) and ctx.store is not None:` |
+| 3 | `atoms/identity_ops.py` | :25 ClearIdentity | `if identity == "direct":` | `if is_direct(identity):` |
+| 4 | `db.py` | :684 `ip_event_summary` | `WHERE identity != 'direct'` | `WHERE identity NOT LIKE '%:direct' AND identity != 'direct'` |
+| 5 | `db.py` | `format_tmd_report` 表头+数据行 | `:<17`（两处） | `:<22`（两处同步） |
+| 6 | `net/browser.py` | `launch` 指纹传参 :299 | `args=fingerprint_args(seed_kit["name"] if seed_kit else identity)` | `args=fingerprint_args(seed_kit["name"] if seed_kit else bare_identity(identity))` |
+
+### ③ TDD — 21 个新测试
+
+| 测试文件 | 测试数 | 覆盖 |
+|----------|--------|------|
+| `tests/test_session_helpers.py` | 8 | `bare_identity` / `is_direct` 所有输入形态 |
+| `tests/test_identity.py` | 5 | #3 ClearIdentity（prefixed direct 跳过 / 非直连清空 / 旧键回归）；#4 ip_event_summary（双滤）；#5 format_tmd_report（列宽容纳） |
+| `tests/test_browser_fresh.py` | 7 | #1 check_ip_fresh（prefixed 同 IP 不轮换 / 换 IP 触发 / 旧键回归）；#6 fingerprint_args（prefixed 与 bare 同指纹 / launch monkeypatch） |
+| `tests/test_control_loop.py` | 1 | #2 login_wall 不误烧 prefixed direct |
+
+## TDD 证据
+
+### RED（每处修正的失败证据）
+
+**Helper functions:** `ImportError: cannot import name 'bare_identity'` — 函数不存在，8 tests 全部失败。
+
+**#1 check_ip_fresh:**
+```
+AssertionError: True is not false : 不应触发 relaunch，reason=出口 IP 已轮换（1688:1.2.3.4 -> 1.2.3.4）
+```
+预期：`"1.2.3.4" != "1688:1.2.3.4"` → True → 误判轮换。修正后 `bare_identity("1688:1.2.3.4")` = `"1.2.3.4"` → 相等 → 不触发。
+
+**#2 login_wall:**
+```
+AssertionError: 0 != 1 : prefixed direct 身份应保留 Cookie，不应被烧毁
+```
+预期：`"1688:direct" != "direct"` → True → 触发 burn。修正后 `is_direct("1688:direct")` → True → 跳过。
+
+**#3 ClearIdentity:**
+```
+AssertionError: <Outcome.OK: 'ok'> is not <Outcome.SKIPPED: 'skipped'> : 期望跳过直连身份
+```
+预期：`"1688:direct" == "direct"` → False → 走 burn 路径。修正后 `is_direct("1688:direct")` → True → skipped。
+
+**#4 ip_event_summary:**
+```
+AssertionError: Items in the first set but not the second: '1688:direct'
+期望只含 IP 行，实际={'1.2.3.4', '1688:direct', '1688:1.2.3.4'}
+```
+预期：SQL `!= 'direct'` 不排除 `'1688:direct'`。修正后双滤排除。
+
+**#5 format_tmd_report:**
+```
+AssertionError: 27 != 25 : 不同长度 identity 的请求列应对齐
+实际 1.2.3.4=25, madeinchina:1.2.3.4=27
+```
+预期：列宽 17 < 21 → 长 identity 撑列宽，两行不对齐。修正后 22 容纳全部。
+
+### GREEN（修正后）
+
+```
+cd fetcher && python -m pytest tests -x -q
+270 passed, 2 subtests passed in 11.48s
+```
+
+### SPEC §5 grep 审计
+
+```bash
+grep -rn '!= "direct"\|== "direct"' fetcher/fetcher/ --include="*.py" | grep -v vendor
+# 仅剩一行：fetcher/fetcher/core/session.py:32: return bare_identity(identity) == "direct"
+```
+
+Python 侧字面量 `"direct"` 比较只剩 `is_direct()` 自己内部。`db.py:684` 的 SQL 字符串 `!= 'direct'` 按 §3.3#4 豁免。
+
+## 改动统计
+
+| 文件 | 改动 |
+|------|------|
+| `fetcher/fetcher/core/session.py` | +16 行（2 个辅助函数） |
+| `fetcher/fetcher/net/browser.py` | 2 行改（import + #1 + #6） |
+| `fetcher/fetcher/control/loop.py` | 2 行改（import + #2） |
+| `fetcher/fetcher/atoms/identity_ops.py` | 2 行改（import + #3） |
+| `fetcher/fetcher/db.py` | 3 行改（#4 SQL + #5 两处列宽） |
+| `fetcher/tests/test_session_helpers.py` | +53 行（新文件） |
+| `fetcher/tests/test_browser_fresh.py` | +129 行（新文件） |
+| `fetcher/tests/test_identity.py` | +130 行 |
+| `fetcher/tests/test_control_loop.py` | +26 行 |
+| **合计** | **9 files, +363/-10** |
+
+## 验证
+
+- [x] 6 处修正与 §3.3 表一致
+- [x] SPEC §5 第 6 条 grep 达成
+- [x] 全量 270 passed 无回归
+- [x] 只改 `fetcher/`，未碰 platform/、vendor/wa-check/、scraper/、util/
+- [x] commit 显式列文件（9 files），不含工作区其他未提交改动
+- [x] 未做 Step 1.3（不拼前缀、不改 engine、不加 site_name）
+
+## 疑虑
+
+无。本步为纯字符串级别修正，对当前无前缀旧键行为逐字等价，无运行时行为变化。
+
+---
+
+## 修复轮 1（review 反馈）
+
+### 改动
+
+1. **移除 RED 注释**：`:7` 行 `# 函数尚未实现，导入会失败——这是预期的 RED` 已删除，GREEN 态不需要。
+2. **边界测试**：新增 3 条 `bare_identity` 边界 case：
+   - `bare_identity("") == ""` — 空字符串原样
+   - `bare_identity("a:b:c") == "b:c"` — 多冒号只切第一个
+   - `bare_identity("1688:") == ""` — 仅前缀无值返回空串
+3. **延迟导入改模块级**：`from fetcher.core.session import bare_identity, is_direct` 移至文件顶部（TDD RED 阶段的方法内导入不再需要）。
+
+### 测试
+
+```bash
+cd fetcher && python -m pytest tests -x -q
+# 273 passed, 2 subtests passed in 12.81s
+```
+
+### commit
+
+`<待提交>` feat(identity-p2): Step 1.2 修复轮1 — 移除RED注释 + 3边界测试 + 模块级import
diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-review.md b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-review.md
new file mode 100644
index 0000000..fd87616
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.2-review.md
@@ -0,0 +1,692 @@
+# Step 1.2 review 审查包（BASE 446effa..HEAD bfd97d3）
+
+## git log
+bfd97d3 feat(identity-p2): Step 1.2 辅助函数 + 隐藏点修正（SPEC §3.3 #1-#6）
+
+## git diff --stat
+ fetcher/fetcher/atoms/identity_ops.py |   3 +-
+ fetcher/fetcher/control/loop.py       |   4 +-
+ fetcher/fetcher/core/session.py       |  16 +++++
+ fetcher/fetcher/db.py                 |   6 +-
+ fetcher/fetcher/net/browser.py        |   6 +-
+ fetcher/tests/test_browser_fresh.py   | 129 +++++++++++++++++++++++++++++++++
+ fetcher/tests/test_control_loop.py    |  26 +++++++
+ fetcher/tests/test_identity.py        | 130 +++++++++++++++++++++++++++++++++-
+ fetcher/tests/test_session_helpers.py |  53 ++++++++++++++
+ 9 files changed, 363 insertions(+), 10 deletions(-)
+
+## git diff -U10
+diff --git a/fetcher/fetcher/atoms/identity_ops.py b/fetcher/fetcher/atoms/identity_ops.py
+index d1659ab..c60334c 100644
+--- a/fetcher/fetcher/atoms/identity_ops.py
++++ b/fetcher/fetcher/atoms/identity_ops.py
+@@ -1,33 +1,34 @@
+ # -*- coding: utf-8 -*-
+ """身份操作原子：ClearIdentity（登录墙烧毁清空 Cookie）。"""
+ 
+ from __future__ import annotations
+ 
++from fetcher.core.session import is_direct
+ from fetcher.core.types import ActionResult
+ 
+ 
+ class ClearIdentity:
+     """清空当前 identity 名下的全部 Cookie。
+ 
+     登录墙 = 会话身份被最高级标记：清空该 IP 名下的 Cookie，避免代理
+     把此 IP 轮换回来时复活已烧毁的会话（迁移自引擎的登录墙处理段）。
+     直连身份（direct）不清空 —— 直连 Cookie 是本机签发的，登录墙
+     时应由人工处理而不是烧毁本机身份。
+     """
+ 
+     name = "clear_identity"
+     title = "清空身份 Cookie"
+ 
+     def run(self, ctx, params: dict) -> ActionResult:
+         if ctx.store is None:
+             return ActionResult.fatal("未装配 identity store")
+         identity = ctx.identity
+-        if identity == "direct":
++        if is_direct(identity):
+             return ActionResult.skipped("直连身份不清空（由人工处理）")
+         try:
+             n = ctx.store.burn(identity)
+             ctx.log(f"    🧹 登录墙标记：已清空 {identity} 名下的 {n} 条 Cookie"
+                     f"（会话身份已烧毁，此 IP 轮换回来时按全新身份重建）")
+             return ActionResult.success(f"已清空 {n} 条 Cookie", count=n)
+         except Exception as e:  # noqa: BLE001
+             return ActionResult.blocked(f"清空登录墙 IP Cookie 失败: {e}")
+diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
+index a214e94..724af46 100644
+--- a/fetcher/fetcher/control/loop.py
++++ b/fetcher/fetcher/control/loop.py
+@@ -23,21 +23,21 @@ item 级重试循环 → 收尾清理），但风控状态机不再写死在控
+ from __future__ import annotations
+ 
+ import random
+ import time
+ 
+ from fetcher.atoms.browser_ops import RelaunchBrowser
+ from fetcher.control.board import wait_countdown
+ from fetcher.control.circuit import CircuitBreaker
+ from fetcher.control.task import Task
+ from fetcher.core.errors import UserInterrupted
+-from fetcher.core.session import Session
++from fetcher.core.session import Session, is_direct
+ from fetcher.core.types import Outcome, Scenario
+ from fetcher.detect.base import SceneInspector
+ from fetcher.net.seeds import SeedBurnTracker
+ from fetcher.strategy.base import PolicyAction
+ from fetcher.strategy.policy import AttemptTracker, Policy
+ 
+ # fetch 自报 outcome 到 Scenario 的兜底映射（探测器判 OK 但 fetch
+ # 显式报告异常时，信 fetch —— 对应旧 scrape 返回 _blocked/_fatal/
+ # _net_error 标记的契约）
+ _OUTCOME_FALLBACK = {
+@@ -441,21 +441,21 @@ class CrawlLoop:
+             ctx.store.record_event(identity,
+                                    _EVENT_NAMES.get(scenario, "block_other"),
+                                    reason, req_since_block=since)
+             ctx.store.stat_block(identity)
+         ctr["since"] = 0
+         self.log(f"  [tmd] 出口 {identity} 在 {since} 次请求后"
+                  f"触发反爬（本 IP 累计 {ctr['n']} 次请求）")
+ 
+         # 登录墙 = 会话身份最高级标记：判定当下立即烧毁该 IP 名下的
+         # Cookie（避免轮换回来复活已烧毁会话）——与旧引擎同点位
+-        if login_wall and identity != "direct" and ctx.store is not None:
++        if login_wall and not is_direct(identity) and ctx.store is not None:
+             try:
+                 n = ctx.store.burn(identity)
+                 self.log(f"  🧹 登录墙标记：已清空 {identity} 名下的 {n} 条"
+                          f" Cookie（此 IP 轮换回来时按全新身份重建）")
+             except Exception as e:  # noqa: BLE001
+                 self.log(f"  [!] 清空登录墙 IP Cookie 失败: {e}")
+ 
+         # 种子烧毁判定：首请求秒拦/登录墙记到种子头上
+         if self.seed_tracker.note_block(identity, since, login_wall,
+                                         log=self.log):
+diff --git a/fetcher/fetcher/core/session.py b/fetcher/fetcher/core/session.py
+index ce67860..2c2f477 100644
+--- a/fetcher/fetcher/core/session.py
++++ b/fetcher/fetcher/core/session.py
+@@ -9,20 +9,36 @@
+ 
+ from __future__ import annotations
+ 
+ from dataclasses import dataclass, field
+ from typing import TYPE_CHECKING, Any
+ 
+ if TYPE_CHECKING:  # 避免 core -> net 的反向依赖
+     from fetcher.net.proxy.base import Channel
+ 
+ 
++# ---------- identity 辅助函数 ----------
++
++def bare_identity(identity: str) -> str:
++    """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回。
++
++    指纹/保鲜检查等需要裸 IP 的场合用此函数从 identity 键中提取裸 IP。
++    兼容旧键（无前缀直存 IP 或 'direct'）。
++    """
++    return identity.split(":", 1)[1] if ":" in identity else identity
++
++
++def is_direct(identity: str) -> bool:
++    """identity 是否代表直连模式（含 'direct' 与 'site:direct' 两种形态）。"""
++    return bare_identity(identity) == "direct"
++
++
+ @dataclass
+ class Session:
+     """一次浏览器启动的产物。
+ 
+     browser/page 为 Playwright 对象（Any 以保持本包可独立 import，
+     不依赖 playwright 安装）。
+     """
+ 
+     browser: Any = None
+     page: Any = None
+diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
+index 43e98d8..6f1f978 100644
+--- a/fetcher/fetcher/db.py
++++ b/fetcher/fetcher/db.py
+@@ -674,21 +674,21 @@ class ShopDB:
+             pass  # 事件流水不影响主流程
+ 
+     def ip_event_summary(self) -> list[dict]:
+         """按 IP 汇总事件次数（评估 IP 质量用）。"""
+         rows = self.conn.execute(
+             """SELECT identity,
+                       SUM(event='launch')       AS launches,
+                       SUM(event='block_slider') AS sliders,
+                       SUM(event='block_login')  AS login_walls,
+                       MAX(created_at)           AS last_seen
+-               FROM ip_events WHERE identity != 'direct'
++               FROM ip_events WHERE identity NOT LIKE '%:direct' AND identity != 'direct'
+                GROUP BY identity ORDER BY last_seen DESC""").fetchall()
+         return [dict(r) for r in rows]
+ 
+     # ---------- tmd（反爬验证）触发统计 ----------
+ 
+     def ip_stat_request(self, identity: str, ok: bool = False) -> None:
+         """累计该出口 IP 的一次页面请求（ok=True 表示成功解析）。
+ 
+         每次 scrape 调用 = 一次页面请求；网络/代理层错误（请求没到目标站）
+         由调用方跳过不计。tmd 率 = blocks / requests。
+@@ -755,28 +755,28 @@ class ShopDB:
+         回答三个问题：
+             - tmd 率是多少：触发次数 / 页面请求数
+             - 每爬多少个会触发一次反爬：触发间隔的平均/最少/最多
+             - 一个 IP 爬多少个以内算安全：最少触发间隔 × 0.8
+         """
+         rep = self.tmd_report()
+         rows, gaps = rep["rows"], rep["gaps"]
+         if not rows:
+             return "暂无 tmd 统计（还没有带统计的抓取记录）"
+         lines = ["tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:",
+-                 f"    {'出口IP':<17}{'请求':>6}{'成功':>6}{'触发':>5}"
++                 f"    {'出口IP':<22}{'请求':>6}{'成功':>6}{'触发':>5}"
+                  f"{'tmd率':>8}{'平均间隔':>9}{'最少':>6}{'最多':>6}  最近触发"]
+         for r in rows:
+             rate = (f"{r['blocks'] / r['requests'] * 100:.1f}%"
+                     if r["requests"] else "—")
+             fmt = lambda v: f"{v:.0f}" if v is not None else "—"
+             lines.append(
+-                f"    {r['identity']:<17}{r['requests']:>6}{r['ok']:>6}"
++                f"    {r['identity']:<22}{r['requests']:>6}{r['ok']:>6}"
+                 f"{r['blocks']:>5}{rate:>8}{fmt(r['avg_gap']):>9}"
+                 f"{fmt(r['min_gap']):>6}{fmt(r['max_gap']):>6}  "
+                 f"{r['last_block_at'] or '—'}")
+         tot_req = sum(r["requests"] for r in rows)
+         tot_blk = sum(r["blocks"] for r in rows)
+         if tot_req:
+             lines.append(f"    整体: {tot_req} 次页面请求，触发 {tot_blk} 次，"
+                          f"tmd率 {tot_blk / tot_req * 100:.2f}%")
+         if gaps:
+             avg = sum(gaps) / len(gaps)
+diff --git a/fetcher/fetcher/net/browser.py b/fetcher/fetcher/net/browser.py
+index 39e224b..e987cb9 100644
+--- a/fetcher/fetcher/net/browser.py
++++ b/fetcher/fetcher/net/browser.py
+@@ -29,21 +29,21 @@ import threading
+ import time
+ from pathlib import Path
+ 
+ from fetcher.core.context import RunConfig
+ from fetcher.core.errors import (
+     BrowserLaunchError,
+     ExitIPError,
+     LicenseSeatTimeout,
+     UserInterrupted,
+ )
+-from fetcher.core.session import Session
++from fetcher.core.session import Session, bare_identity
+ from fetcher.net.identity import IdentityStore
+ 
+ # ---------- 配置加载 ----------
+ 
+ # 各套餐的并发会话席位上限（服务端强制，超限的 launch 会以退出码 76
+ # 拒绝；此处仅用于启动前主动等待，上限未知的套餐不阻塞直接放行）
+ PLAN_SEATS = {"free": 1, "solo": 5}
+ 
+ 
+ def load_license_key(config_json: Path | None = None) -> str | None:
+@@ -186,21 +186,21 @@ class BrowserManager:
+ 
+         青果出口 IP 每 30 分钟轮换一次：查询到的 IP 与 identity 不一致
+         即视为已过期；查询失败先短重试 3 次确认隧道是否真的失效。
+         查询仍失败时不强制 relaunch —— 重启同样依赖该查询，查询挂时重启
+         大概率也失败；跳过本轮检查，交给 fetch 的 BROWSER_DEAD/NET_ERROR
+         处置兜底，避免一个瞬时查询故障打死整个 worker。
+         """
+         cur_ip = self._query_exit_ip_with_retry(session.req_proxies)
+         if cur_ip is None:
+             return False, None, "出口 IP 查询失败（跳过本轮保鲜检查）"
+-        if cur_ip != session.identity:
++        if cur_ip != bare_identity(session.identity):
+             return True, cur_ip, f"出口 IP 已轮换（{session.identity} -> {cur_ip}）"
+         return False, cur_ip, ""
+ 
+     # ---- 启动 ----
+ 
+     def launch(self, channel=None, seed_kit: dict = None,
+                stop: threading.Event | None = None) -> Session:
+         """启动 CloakBrowser 并注入 Cookie，返回 Session。
+ 
+         channel: Channel 实例，或旧版兼容的 "host:port" 字符串
+@@ -289,21 +289,21 @@ class BrowserManager:
+         threading.Thread(target=_watchdog, daemon=True,
+                          name=f"launch-watchdog-{identity}").start()
+         try:
+             browser = cloak_launch(
+                 headless=cfg.headless,
+                 license_key=load_license_key(),
+                 humanize=True,
+                 locale="zh-CN",
+                 timezone="Asia/Shanghai",
+                 stealth_args=False,
+-                args=fingerprint_args(seed_kit["name"] if seed_kit else identity),
++                args=fingerprint_args(seed_kit["name"] if seed_kit else bare_identity(identity)),
+                 **({"proxy": proxy_conf, "geoip": True} if proxy_conf else {}),
+             )
+         except SystemExit as e:
+             raise BrowserLaunchError(
+                 f"CloakBrowser 二进制退出（code={e.code}，"
+                 f"多为会话席位被占或 License 校验失败）") from e
+         finally:
+             launch_done.set()
+ 
+         self.log(f"    [launch] 浏览器进程已启动，创建上下文并注入 Cookie…")
+diff --git a/fetcher/tests/test_browser_fresh.py b/fetcher/tests/test_browser_fresh.py
+new file mode 100644
+index 0000000..3ed6eb4
+--- /dev/null
++++ b/fetcher/tests/test_browser_fresh.py
+@@ -0,0 +1,129 @@
++# -*- coding: utf-8 -*-
++"""BrowserManager 单测：check_ip_fresh + fingerprint_args（Step 1.2 #1, #6）。"""
++
++import unittest
++from unittest.mock import patch, MagicMock
++
++from fetcher import RunConfig
++from fetcher.core.session import Session, bare_identity, is_direct
++from fetcher.net.browser import BrowserManager, fingerprint_args
++
++
++class CheckIPFreshP2Test(unittest.TestCase):
++    """#1: check_ip_fresh 使用 bare_identity 比较（避免误判 IP 轮换）。"""
++
++    def setUp(self):
++        config = RunConfig(headless=True, use_proxy=False)
++        self.mgr = BrowserManager(
++            config=config, store=MagicMock(), log=lambda m: None)
++
++    def _session(self, identity, req_proxies=None):
++        return Session(identity=identity, req_proxies=req_proxies)
++
++    def test_prefixed_identity_same_ip_no_relaunch(self):
++        """identity='1688:1.2.3.4' 出口 IP 同为 1.2.3.4 → 不触发 relaunch。
++
++        RED 预期（修正前）：cur_ip('1.2.3.4') != session.identity('1688:1.2.3.4')
++        → True → (True, ...) → 误判轮换。
++        """
++        session = self._session(identity="1688:1.2.3.4")
++        with patch.object(self.mgr, "_query_exit_ip_with_retry",
++                          return_value="1.2.3.4"):
++            need, cur, reason = self.mgr.check_ip_fresh(session)
++        self.assertFalse(need, f"不应触发 relaunch，reason={reason}")
++        self.assertEqual(cur, "1.2.3.4")
++
++    def test_bare_identity_same_ip_no_relaunch(self):
++        """identity='1.2.3.4'（旧键）出口 IP 同为 1.2.3.4 → 不触发 relaunch。
++
++        回归验证：旧键行为不变。
++        """
++        session = self._session(identity="1.2.3.4")
++        with patch.object(self.mgr, "_query_exit_ip_with_retry",
++                          return_value="1.2.3.4"):
++            need, cur, reason = self.mgr.check_ip_fresh(session)
++        self.assertFalse(need)
++
++    def test_prefixed_identity_changed_ip_triggers_relaunch(self):
++        """identity='1688:1.2.3.4' 出口 IP 变为 5.5.5.5 → 触发 relaunch。"""
++        session = self._session(identity="1688:1.2.3.4")
++        with patch.object(self.mgr, "_query_exit_ip_with_retry",
++                          return_value="5.5.5.5"):
++            need, cur, reason = self.mgr.check_ip_fresh(session)
++        self.assertTrue(need)
++        self.assertEqual(cur, "5.5.5.5")
++
++    def test_bare_identity_changed_ip_triggers_relaunch(self):
++        """identity='1.2.3.4'（旧键）出口 IP 变为 5.5.5.5 → 触发 relaunch。"""
++        session = self._session(identity="1.2.3.4")
++        with patch.object(self.mgr, "_query_exit_ip_with_retry",
++                          return_value="5.5.5.5"):
++            need, cur, reason = self.mgr.check_ip_fresh(session)
++        self.assertTrue(need)
++        self.assertEqual(cur, "5.5.5.5")
++
++
++class FingerprintArgsP2Test(unittest.TestCase):
++    """#6: fingerprint_args 接收裸 IP（非种子分支）。"""
++
++    def test_prefixed_ip_same_fingerprint_as_bare_ip(self):
++        """fingerprint_args 对 prefixed identity 与裸 IP 返回相同指纹。
++
++        修正后的调用形态：fingerprint_args(bare_identity("1688:1.2.3.4"))
++        应等于 fingerprint_args("1.2.3.4")。
++        """
++        self.assertEqual(
++            fingerprint_args(bare_identity("1688:1.2.3.4")),
++            fingerprint_args("1.2.3.4"),
++            "带前缀 identity 经 bare_identity 剥取后，指纹应与裸 IP 一致")
++
++    def test_prefixed_direct_same_fingerprint_as_direct(self):
++        """fingerprint_args 对 '1688:direct' 与 'direct' 返回相同指纹。"""
++        self.assertEqual(
++            fingerprint_args(bare_identity("1688:direct")),
++            fingerprint_args("direct"),
++            "prefixed direct 经 bare_identity 剥取后，指纹应与 'direct' 一致")
++
++    def test_launch_passes_bare_identity_to_fingerprint_args(self):
++        """launch 非种子分支传 bare_identity(identity) 给 fingerprint_args。
++
++        因当前代码 identity 尚未拼前缀（Step 1.3），这里验证修正后的
++        调用点：seed_kit=None 时传 bare_identity(identity)。
++        直连模式 identity='direct' → bare_identity 后仍为 'direct'，
++        与修正前行为逐字等价。
++
++        通过 monkeypatch fingerprint_args 捕获入参进行验证。
++        """
++        import fetcher.net.browser as browser_mod
++
++        captured_fp_args = []
++
++        def _capture_fp(identity):
++            captured_fp_args.append(identity)
++            return ["--no-sandbox", "--fingerprint=12345",
++                    "--fingerprint-platform=macos"]
++
++        config = RunConfig(
++            headless=True, use_proxy=False,
++            db_path="/nonexistent/test_1688.db")
++        mgr = BrowserManager(
++            config=config, store=MagicMock(), log=lambda m: None)
++
++        with patch.object(browser_mod, "fingerprint_args", _capture_fp):
++            try:
++                mgr.launch()
++            except Exception:
++                pass  # 预期后续步骤失败（无 cookies / cloakbrowser）
++
++        self.assertTrue(len(captured_fp_args) > 0,
++                        "fingerprint_args 应被调用过")
++        # 直连模式：identity='direct'，bare_identity 后仍为 'direct'
++        # 修正前传 'direct'，修正后传 bare_identity('direct')='direct' ——
++        # 行为等价（回归验证）
++        self.assertEqual(captured_fp_args[0], "direct",
++                         f"直连模式指纹入参应为 'direct'，"
++                         f"实际={captured_fp_args[0]!r}")
++
++
++if __name__ == "__main__":
++    unittest.main()
+diff --git a/fetcher/tests/test_control_loop.py b/fetcher/tests/test_control_loop.py
+index e7a9524..2430599 100644
+--- a/fetcher/tests/test_control_loop.py
++++ b/fetcher/tests/test_control_loop.py
+@@ -309,20 +309,46 @@ class CrawlLoopTest(LoopTestBase):
+             [("page", "https://login.1688.com/member/signin.htm", "请登录", {})])
+         table = {Scenario.RISK_LOGIN: [("wait_login", 1),
+                                        ("give_up", None)]}
+         policy = Policy(table=table, strategies={"wait_login": wait})
+         CrawlLoop(ctx, task, policy=policy).run()
+         # 判定当下即烧毁身份（与旧引擎同点位），不等策略链
+         rows = self.db_query("SELECT COUNT(*) AS c FROM cookies"
+                              " WHERE identity='1.1.1.1'")
+         self.assertEqual(rows[0]["c"], 0)
+ 
++    def test_login_wall_does_not_burn_prefixed_direct(self):
++        """登录墙对 identity='1688:direct' 不烧毁（视为直连）。
++
++        RED 预期（修正前）：identity != "direct" → "1688:direct" != "direct"
++        → True → 触发 burn → Cookie 被清空 → 断言 cookies 仍存在失败。
++        """
++        # 构造返回 identity='1688:direct' 的 MockBrowserManager
++        mgr = MockBrowserManager(self.page, identities=("1688:direct",))
++        config = make_config(self.tmp)
++        ctx = make_ctx(self.tmp, self.page, mgr, config)
++        # 预置 Cookie 到 "1688:direct" 名下
++        ctx.store.save("1688:direct", [{"name": "cna", "value": "v",
++                                        "domain": ".1688.com", "path": "/"}])
++        wait = FakeStrategy()
++        task = ScriptedTask(
++            [("page", "https://login.1688.com/member/signin.htm", "请登录", {})])
++        table = {Scenario.RISK_LOGIN: [("wait_login", 1),
++                                       ("give_up", None)]}
++        policy = Policy(table=table, strategies={"wait_login": wait})
++        CrawlLoop(ctx, task, policy=policy).run()
++        # 修正后：is_direct("1688:direct") → True → 不清空
++        rows = self.db_query("SELECT COUNT(*) AS c FROM cookies"
++                             " WHERE identity='1688:direct'")
++        self.assertEqual(rows[0]["c"], 1,
++                         "prefixed direct 身份应保留 Cookie，不应被烧毁")
++
+     def test_swap_ip_replaces_session_and_restarts_warm(self):
+         swap = SwapForReal()
+         task = ScriptedTask(
+             [("page", "https://sec.1688.com/x5sec/p.htm", "滑动验证", {}),
+              ("page", "https://shop123.1688.com/page/contactinfo.htm",
+               "正常页面文本，足够长，包含电话、手机、地址字段标签内容，"
+               "再补充一些文字确保超过空白页判定阈值。", {"v": 1})])
+         table = {Scenario.RISK_SLIDER_PAGE: [("swap", 2), ("give_up", None)]}
+         loop, ctx, _ = self.run_loop(task, table, {"swap": swap})
+         self.assertEqual(task.succeeded, ["item1"])
+diff --git a/fetcher/tests/test_identity.py b/fetcher/tests/test_identity.py
+index 1b95cf4..f8a8ee2 100644
+--- a/fetcher/tests/test_identity.py
++++ b/fetcher/tests/test_identity.py
+@@ -1,20 +1,23 @@
+ # -*- coding: utf-8 -*-
+ """IdentityStore 单测：Cookie 按 identity 隔离、过期剔除、burn 清空。
+ 使用临时 sqlite 文件，不碰真实数据库。"""
+ 
+ import tempfile
++import threading
+ import time
+ import unittest
+ from pathlib import Path
+ 
+-from fetcher import IdentityStore, ShopDB
++from fetcher import IdentityStore, RunConfig, Session, ShopDB, WorkerContext
++from fetcher.atoms.identity_ops import ClearIdentity
++from fetcher.core.types import Outcome
+ 
+ NOW = int(time.time())
+ 
+ 
+ def ck(name, value="v", domain=".1688.com", expires=None):
+     c = {"name": name, "value": value, "domain": domain, "path": "/",
+          "secure": False, "httpOnly": False}
+     if expires is not None:
+         c["expires"] = expires
+     return c
+@@ -114,12 +117,137 @@ class IdentityStoreTest(unittest.TestCase):
+     def test_ip_event_recording(self):
+         self.store.record_event("1.2.3.4", "block_slider", "测试", req_since_block=7)
+         rows = self.db.conn.execute(
+             "SELECT event, req_since_block FROM ip_events"
+             " WHERE identity='1.2.3.4'").fetchall()
+         self.assertEqual(len(rows), 1)
+         self.assertEqual(rows[0]["event"], "block_slider")
+         self.assertEqual(rows[0]["req_since_block"], 7)
+ 
+ 
++class IdentityP2CompatibilityTest(unittest.TestCase):
++    """Step 1.2 identity 辅助函数集成测试：验证 6 处修正点的行为。"""
++
++    def setUp(self):
++        self._tmp = tempfile.TemporaryDirectory()
++        self.db_path = Path(self._tmp.name) / "test.db"
++        self.db = ShopDB(self.db_path)
++        self.store = IdentityStore(self.db, domain="1688.com")
++
++    def tearDown(self):
++        self.db.close()
++        self._tmp.cleanup()
++
++    # ---- #3: ClearIdentity 对 prefixed direct 跳过 ----
++
++    def test_clear_identity_skips_prefixed_direct(self):
++        """ClearIdentity: '1688:direct' 视为直连，跳过不清空。
++
++        RED 预期（修正前）：'1688:direct' == 'direct' → False → 尝试
++        burn → 不走 skipped 路径 → 断言 Outcome.SKIPPED 失败。
++        """
++        config = RunConfig(db_path=str(self.db_path))
++        ctx = WorkerContext(config=config, store=self.store,
++                            stop=threading.Event(), log=lambda m: None)
++        ctx.session = Session(identity="1688:direct")
++        result = ClearIdentity().run(ctx, {})
++        self.assertIs(result.outcome, Outcome.SKIPPED,
++                      f"期望跳过直连身份，实际 outcome={result.outcome}")
++
++    def test_clear_identity_burns_non_direct(self):
++        """ClearIdentity: 非直连 IP 正常清空。"""
++        # 预置 Cookie
++        self.store.save("1.2.3.4", [{"name": "cna", "value": "v",
++                                      "domain": ".1688.com", "path": "/"}])
++        config = RunConfig(db_path=str(self.db_path))
++        ctx = WorkerContext(config=config, store=self.store,
++                            stop=threading.Event(), log=lambda m: None)
++        ctx.session = Session(identity="1.2.3.4")
++        result = ClearIdentity().run(ctx, {})
++        self.assertIs(result.outcome, Outcome.OK)
++        self.assertEqual(self.store.load("1.2.3.4"), [])
++
++    def test_clear_identity_skips_bare_direct(self):
++        """ClearIdentity: 旧键 'direct' 行为不变（回归验证）。"""
++        config = RunConfig(db_path=str(self.db_path))
++        ctx = WorkerContext(config=config, store=self.store,
++                            stop=threading.Event(), log=lambda m: None)
++        ctx.session = Session(identity="direct")
++        result = ClearIdentity().run(ctx, {})
++        self.assertIs(result.outcome, Outcome.SKIPPED)
++
++    # ---- #4: ip_event_summary 过滤 site:direct ----
++
++    def _seed_ip_events(self):
++        """插入 4 行 ip_events：'direct', '1688:direct', '1.2.3.4',
++        '1688:1.2.3.4' 各一条 launch 事件。"""
++        for ident in ("direct", "1688:direct", "1.2.3.4", "1688:1.2.3.4"):
++            self.db.conn.execute(
++                "INSERT INTO ip_events (identity, event, detail, "
++                "req_since_block, created_at) VALUES (?, 'launch', '', 0, "
++                "datetime('now', 'localtime'))", (ident,))
++        self.db.conn.commit()
++
++    def test_ip_event_summary_excludes_prefixed_direct(self):
++        """ip_event_summary: '1688:direct' 与 'direct' 都应被排除。
++
++        RED 预期（修正前）：WHERE identity != 'direct' → '1688:direct'
++        满足 != 'direct' → 被包含在结果中 → 断言 len==2 失败（得 3）。
++        """
++        self._seed_ip_events()
++        rows = self.db.ip_event_summary()
++        idents = {r["identity"] for r in rows}
++        # 修正后：只保留不带 :direct 后缀的 IP 身份
++        self.assertEqual(idents, {"1.2.3.4", "1688:1.2.3.4"},
++                         f"期望只含 IP 行，实际={idents}")
++        self.assertEqual(len(rows), 2)
++
++    # ---- #5: format_tmd_report 列宽容纳 site:ip ----
++
++    def _seed_ip_stats(self, identity, requests=10, ok=8, blocks=2):
++        """插入一条 ip_stats 行并记录一次 block 事件。"""
++        self.db.conn.execute(
++            "INSERT INTO ip_stats (identity, requests, ok, updated_at) "
++            "VALUES (?, ?, ?, datetime('now', 'localtime'))",
++            (identity, requests, ok))
++        # 记录一次 block 事件以生成 tmd 统计
++        self.db.conn.execute(
++            "INSERT INTO ip_events (identity, event, detail, "
++            "req_since_block, created_at) VALUES "
++            "(?, 'block_slider', '', ?, datetime('now', 'localtime'))",
++            (identity, 5))
++        self.db.conn.commit()
++
++    def test_format_tmd_report_fits_long_identity(self):
++        """format_tmd_report: 不同长度 identity 的请求列对齐到同一位。
++
++        RED 预期（修正前）：列宽 17 < 21-long identity → 短 identity
++        ("1.2.3.4") 的请求列在 position 21，长 identity
++        ("madeinchina:1.2.3.4") 在 position 25 → 不相等 → 断言失败。
++        """
++        ident_long = "madeinchina:1.2.3.4"
++        ident_short = "1.2.3.4"
++        self._seed_ip_stats(ident_long)
++        self._seed_ip_stats(ident_short)
++        report = self.db.format_tmd_report()
++        # 提取两条数据行，计算「请求」列（第一个数字）的起始位置
++        positions = {}
++        for ident in (ident_long, ident_short):
++            self.assertIn(ident, report,
++                          f"期望报告中包含 identity={ident}")
++            line = [l for l in report.split("\n") if ident in l][0]
++            # identity 在行中的位置
++            idx = line.index(ident)
++            # identity 之后第一个数字的位置
++            after = line[idx + len(ident):]
++            digit_pos = idx + len(ident) + len(after) - len(after.lstrip())
++            positions[ident] = digit_pos
++        # 修正后：两行的请求列应起始于同一列
++        self.assertEqual(
++            positions[ident_long], positions[ident_short],
++            f"不同长度 identity 的请求列应对齐，实际 "
++            f"{ident_short}={positions[ident_short]}, "
++            f"{ident_long}={positions[ident_long]}")
++
++
+ if __name__ == "__main__":
+     unittest.main()
+diff --git a/fetcher/tests/test_session_helpers.py b/fetcher/tests/test_session_helpers.py
+new file mode 100644
+index 0000000..b2d2344
+--- /dev/null
++++ b/fetcher/tests/test_session_helpers.py
+@@ -0,0 +1,53 @@
++# -*- coding: utf-8 -*-
++"""bare_identity / is_direct 辅助函数单测（TDD RED→GREEN）。"""
++
++import unittest
++
++
++# 函数尚未实现，导入会失败——这是预期的 RED
++class BareIdentityTest(unittest.TestCase):
++    def test_strips_site_prefix(self):
++        """带站点前缀的 IP：剥掉前缀返回裸 IP。"""
++        from fetcher.core.session import bare_identity
++        self.assertEqual(bare_identity("1688:1.2.3.4"), "1.2.3.4")
++
++    def test_strips_prefix_for_direct(self):
++        """带站点前缀的 direct：剥掉前缀返回 direct。"""
++        from fetcher.core.session import bare_identity
++        self.assertEqual(bare_identity("madeinchina:direct"), "direct")
++
++    def test_passthrough_bare_ip(self):
++        """无前缀 IP：原样返回（兼容旧键）。"""
++        from fetcher.core.session import bare_identity
++        self.assertEqual(bare_identity("1.2.3.4"), "1.2.3.4")
++
++    def test_passthrough_direct(self):
++        """无前缀 direct：原样返回（兼容旧键）。"""
++        from fetcher.core.session import bare_identity
++        self.assertEqual(bare_identity("direct"), "direct")
++
++
++class IsDirectTest(unittest.TestCase):
++    def test_bare_direct_is_direct(self):
++        """无前缀 direct 判定为直连。"""
++        from fetcher.core.session import is_direct
++        self.assertTrue(is_direct("direct"))
++
++    def test_prefixed_direct_is_direct(self):
++        """带站点前缀的 direct 也判定为直连。"""
++        from fetcher.core.session import is_direct
++        self.assertTrue(is_direct("1688:direct"))
++
++    def test_ip_is_not_direct(self):
++        """裸 IP 不是直连。"""
++        from fetcher.core.session import is_direct
++        self.assertFalse(is_direct("1.2.3.4"))
++
++    def test_prefixed_ip_is_not_direct(self):
++        """带站点前缀的 IP 不是直连。"""
++        from fetcher.core.session import is_direct
++        self.assertFalse(is_direct("1688:1.2.3.4"))
++
++
++if __name__ == "__main__":
++    unittest.main()
diff --git a/fetcher/tests/test_session_helpers.py b/fetcher/tests/test_session_helpers.py
index b2d2344..252029f 100644
--- a/fetcher/tests/test_session_helpers.py
+++ b/fetcher/tests/test_session_helpers.py
@@ -1,53 +1,60 @@
 # -*- coding: utf-8 -*-
-"""bare_identity / is_direct 辅助函数单测（TDD RED→GREEN）。"""
+"""bare_identity / is_direct 辅助函数单测。"""
 
 import unittest
 
+from fetcher.core.session import bare_identity, is_direct
+
 
-# 函数尚未实现，导入会失败——这是预期的 RED
 class BareIdentityTest(unittest.TestCase):
     def test_strips_site_prefix(self):
         """带站点前缀的 IP：剥掉前缀返回裸 IP。"""
-        from fetcher.core.session import bare_identity
         self.assertEqual(bare_identity("1688:1.2.3.4"), "1.2.3.4")
 
     def test_strips_prefix_for_direct(self):
         """带站点前缀的 direct：剥掉前缀返回 direct。"""
-        from fetcher.core.session import bare_identity
         self.assertEqual(bare_identity("madeinchina:direct"), "direct")
 
     def test_passthrough_bare_ip(self):
         """无前缀 IP：原样返回（兼容旧键）。"""
-        from fetcher.core.session import bare_identity
         self.assertEqual(bare_identity("1.2.3.4"), "1.2.3.4")
 
     def test_passthrough_direct(self):
         """无前缀 direct：原样返回（兼容旧键）。"""
-        from fetcher.core.session import bare_identity
         self.assertEqual(bare_identity("direct"), "direct")
 
+    # ---- 边界 ----
+
+    def test_empty_string_passthrough(self):
+        """空字符串无冒号，原样返回。"""
+        self.assertEqual(bare_identity(""), "")
+
+    def test_multi_colon_splits_only_first(self):
+        """多冒号只切第一个：'a:b:c' → 'b:c'。"""
+        self.assertEqual(bare_identity("a:b:c"), "b:c")
+
+    def test_trailing_colon_returns_empty(self):
+        """仅前缀无值：'1688:' → ''。"""
+        self.assertEqual(bare_identity("1688:"), "")
+
 
 class IsDirectTest(unittest.TestCase):
     def test_bare_direct_is_direct(self):
         """无前缀 direct 判定为直连。"""
-        from fetcher.core.session import is_direct
         self.assertTrue(is_direct("direct"))
 
     def test_prefixed_direct_is_direct(self):
         """带站点前缀的 direct 也判定为直连。"""
-        from fetcher.core.session import is_direct
         self.assertTrue(is_direct("1688:direct"))
 
     def test_ip_is_not_direct(self):
         """裸 IP 不是直连。"""
-        from fetcher.core.session import is_direct
         self.assertFalse(is_direct("1.2.3.4"))
 
     def test_prefixed_ip_is_not_direct(self):
         """带站点前缀的 IP 不是直连。"""
-        from fetcher.core.session import is_direct
         self.assertFalse(is_direct("1688:1.2.3.4"))
 
 
 if __name__ == "__main__":
     unittest.main()
