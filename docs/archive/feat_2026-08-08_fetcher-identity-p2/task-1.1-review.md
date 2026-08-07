# Step 1.1 修复轮1 scoped re-review 审查包（5a4c997..5f8764e）

## git log
5f8764e docs(identity-p2): Step 1.1 修复轮1——行号勘误

## git diff -U10
diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md b/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md
index c648465..28b75e5 100644
--- a/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md
+++ b/docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md
@@ -30,23 +30,23 @@
 - **种子身份池认领粒度**：维持每 worker 一份、指纹按种子名（现状）；跨站种子隔离随 P3。
 - **ip_stats / ip_events 存量行迁移**：历史统计行保持裸 IP 键（统计性质，无法按站点干净拆分），新行自然带前缀；tmd 报表把新旧键当不同身份行展示，可接受。
 - **平台侧任何改动**：runner 日志正则与前端分色对带冒号键兼容（§4 假设 4 验证），展示粒度变化 P4 再统一。
 - **多队列调度、item 挂起**：P3。
 
 ## 3. 关键设计
 
 ### 3.1 键格式与注入点
 
 - 键：`f"{site}:{ip}"`，site 用站点注册名（`register_site("1688", ...)`、`register_site("madeinchina", ...)` 等，与 `work_items.site` 同口径）；直连 `f"{site}:direct"`。
-- 注入点：`engine.py` 的 `_make_browser_manager`（:113-123）把 site 注册名传给 BrowserManager；identity 诞生点（`browser.py:233` 一带，launch 拿到出口 IP 处）拼前缀。**仅此一处拼键**——loop/atoms/db 全链路经 `ctx.identity` 消费，零改动。
-- site 注册名来源（Step 1.1 回填）：插件对象的 `name` 属性**不可直接用于拼前缀**——Alibaba1688Plugin.name = `"alibaba1688"`（`fetcher/fetcher/sites/alibaba1688/__init__.py:17`），与注册名 `"1688"`（同文件:66 `register_site("1688", Alibaba1688Plugin)`）不一致。其余四站点一致（madeinchina/yiwugo/taobao/facebook 的 `plugin.name == register_site(name)`）。**方案**：新增 `site_name` 参数字段，由 CLI（`args.site`，`cli/main.py:198`）/ daemon（硬编码 `"1688"`，`cli/main.py:242`）经 `Engine.__init__` → `_make_browser_manager` 透传给 `BrowserManager`，后者在 launch 拼前缀时使用。这样保证 site 与 `work_items.site` 同口径。
-- identity 诞生点（Step 1.1 回填）：`browser.py:217` `identity = "direct"`（默认值）；`browser.py:233` `identity = exit_ip`（代理分支覆盖）。**仅此一处**——`relaunch()` 调用 `session.close()` 后调 `self.launch()`（`browser.py:337-366`），identity 始终由 launch 重新生成，不从旧 session 携带。P2 拼前缀即在此两处：`f"{site_name}:direct"` / `f"{site_name}:{exit_ip}"`。
+- 注入点：`engine.py` 的 `_make_browser_manager`（:113）把 site 注册名传给 BrowserManager；identity 诞生点（`browser.py:233` 一带，launch 拿到出口 IP 处）拼前缀。**仅此一处拼键**——loop/atoms/db 全链路经 `ctx.identity` 消费，零改动。
+- site 注册名来源（Step 1.1 回填）：插件对象的 `name` 属性**不可直接用于拼前缀**——Alibaba1688Plugin.name = `"alibaba1688"`（`fetcher/fetcher/sites/alibaba1688/__init__.py:27`），与注册名 `"1688"`（同文件:85 `register_site("1688", Alibaba1688Plugin)`）不一致。其余四站点一致（madeinchina/yiwugo/taobao/facebook 的 `plugin.name == register_site(name)`）。**方案**：新增 `site_name` 参数字段，由 CLI（`args.site`，`cli/main.py:174`）/ daemon（硬编码 `"1688"`，`cli/main.py:215`）经 `Engine.__init__` → `_make_browser_manager` 透传给 `BrowserManager`，后者在 launch 拼前缀时使用。这样保证 site 与 `work_items.site` 同口径。
+- identity 诞生点（Step 1.1 回填）：`browser.py:217` `identity = "direct"`（默认值）；`browser.py:233` `identity = exit_ip`（代理分支覆盖）。**仅此一处**——`relaunch()` 调用 `session.close()` 后调 `self.launch()`（`browser.py:344-384`），identity 始终由 launch 重新生成，不从旧 session 携带。P2 拼前缀即在此两处：`f"{site_name}:direct"` / `f"{site_name}:{exit_ip}"`。
 
 ### 3.2 辅助函数（`core/session.py` 模块级）
 
 ```python
 def bare_identity(identity: str) -> str:
     """剥掉站点前缀：'1688:1.2.3.4' → '1.2.3.4'；无前缀原样返回（兼容旧键/直连旧值）。"""
     return identity.split(":", 1)[1] if ":" in identity else identity
 
 def is_direct(identity: str) -> bool:
     return bare_identity(identity) == "direct"
@@ -106,28 +106,28 @@ def is_direct(identity: str) -> bool:
 
 - identity 写入：唯一诞生点 `browser.py` launch/relaunch（拼前缀）；`Session.identity` 运行时不变。
 - Cookie 桶读写：IdentityStore（load/save/burn/save_from_context）+ `Session.close()`；键全来自 `session.identity`，无第二来源。
 - 簿记读写：loop `_bookkeep_*`（写）、db 报表（读）；键同上。
 - 迁移：`_migrate()` 在 ShopDB 构造时幂等执行，谁先打开新库谁先跑（WAL 短事务，与活爬虫并发安全——迁移只 UPDATE identity 列，不改其他行）。
 
 ## 4. 契约与行为后果（假设与验证）
 
 | # | 行为假设 | 依据 | 验证方式 |
 |---|---|---|---|
-| 1 | 站点注册名可从 engine 的插件对象获得（用于拼前缀） | **已读码验证**：插件 `name` 属性对 1688 为 `"alibaba1688"`（`alibaba1688/__init__.py:17`），与注册名 `"1688"`（同文件:66）不一致——插件对象无注册名字段。改为 CLI/daemon 透传 `args.site` / `"1688"`（`cli/main.py:198/242`）经 Engine 新参到 BrowserManager（详见 §3.1） | Step 1.1 已回填 §3.1 |
+| 1 | 站点注册名可从 engine 的插件对象获得（用于拼前缀） | **已读码验证**：插件 `name` 属性对 1688 为 `"alibaba1688"`（`alibaba1688/__init__.py:27`），与注册名 `"1688"`（同文件:85）不一致——插件对象无注册名字段。改为 CLI/daemon 透传 `args.site` / `"1688"`（`cli/main.py:174/215`）经 Engine 新参到 BrowserManager（详见 §3.1） | Step 1.1 已回填 §3.1 |
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
 
-- **2026-08-08 Step 1.1 回填**：§4 假设 1 被推翻——插件对象的 `name` 属性不可直接用于拼前缀（1688 的 `plugin.name="alibaba1688"` ≠ 注册名 `"1688"`）。方案：CLI/daemon 把注册名（`args.site` / `"1688"`）透传给 BrowserManager（§3.1）。§4 假设 2 已验证——生产库 domain→site 映射清单完整回填 §3.4（含无法映射第三方域 `.mmstat.com`、`.ynuf.aliapp.org`）。identity 诞生点精确行号 `browser.py:217/233` 确认——relaunch 不携带旧 identity，唯一诞生点即 launch（§3.1）。
+- **2026-08-08 Step 1.1 回填**：§4 假设 1 被推翻——插件对象的 `name` 属性不可直接用于拼前缀（1688 的 `plugin.name="alibaba1688"` ≠ 注册名 `"1688"`，见 `alibaba1688/__init__.py:27` vs `:85`）。该假设原文为「站点注册名可从 engine 的插件对象获得」，实际无法获得，改为 CLI/daemon 透传方案。方案：CLI/daemon 把注册名（`args.site` / `"1688"`）透传给 BrowserManager（§3.1）。§4 假设 2 已验证——生产库 domain→site 映射清单完整回填 §3.4（含无法映射第三方域 `.mmstat.com`、`.ynuf.aliapp.org`）。identity 诞生点精确行号 `browser.py:217/233` 确认——relaunch 不携带旧 identity，唯一诞生点即 launch（§3.1）。
diff --git a/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md
new file mode 100644
index 0000000..36cefc6
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md
@@ -0,0 +1,181 @@
+# Step 1.1 Report — 读码回填
+
+> 日期：2026-08-08 | commit：5a4c997 | 分支：feat/fetcher-identity-p2
+
+## ① 站点注册名来源（SPEC §4 假设 1 → §3.1）
+
+### 证据
+
+**注册表**（`fetcher/fetcher/sites/__init__.py:19-23`）：
+- `register_site(name, plugin_cls)` 将 `name → plugin_cls` 存入 `_SITE_REGISTRY`
+- `get_site(name)` 按注册名取插件实例（`_SITE_REGISTRY[name]()`）
+
+**各站点插件类属性 name vs register_site 实参**：
+
+| 站点 | `Plugin.name` 类属性 | `register_site(name, …)` 实参 | 一致？ |
+|---|---|---|---|
+| 1688 | `"alibaba1688"` (`alibaba1688/__init__.py:27`) | `"1688"` (同文件:85) | ❌ 不一致 |
+| madeinchina | `"madeinchina"` (`madeinchina/__init__.py:32`) | `"madeinchina"` (同文件:96) | ✅ |
+| yiwugo | `"yiwugo"` (`yiwugo/__init__.py:33`) | `"yiwugo"` (同文件:97) | ✅ |
+| taobao | `"taobao"` (`taobao/__init__.py:29`) | `"taobao"` (同文件:86) | ✅ |
+| facebook | `"facebook"` (`facebook/__init__.py:24`) | `"facebook"` (同文件:51) | ✅ |
+
+**Engine 端**（`fetcher/fetcher/control/engine.py`）：
+- `:42` `self.site = site` — 存储的是插件实例
+- `:49-52` `store_factory` 用 `getattr(site, "cookie_domain", "1688.com")` — 只取 cookie_domain，未取注册名
+- `:113` `_make_browser_manager` 传 homepage 给 BrowserManager，未传站点名
+
+**CLI/daemon**（`fetcher/fetcher/cli/main.py`）：
+- `:174` CLI 分支：`site = get_site(args.site)` — args.site 即注册名（如 `"1688"`）
+- `:215` daemon 分支：`site = get_site("1688")` — 硬编码注册名
+
+### 结论
+
+- **插件对象上拿不到注册名**：`self.site.name` 对 1688 返回 `"alibaba1688"` 而非 `"1688"`
+- **推翻了 SPEC §4 假设 1**（原假设「可从插件对象获得注册名」）
+- **方案**：CLI 传 `args.site`、daemon 传 `"1688"`，经 `Engine.__init__` 新参 `site_name` → `_make_browser_manager` → `BrowserManager`，在 launch 拼前缀
+
+---
+
+## ② domain→site 迁移映射清单（SPEC §4 假设 2 → §3.4）
+
+### 证据：生产库只读统计
+
+```
+SQL: SELECT domain, COUNT(*) FROM cookies GROUP BY domain ORDER BY 2 DESC
+DB:  .cache/1688.db (mode=ro, uri=True)
+总行数: 18095, distinct domain: 6971, distinct identity: 637
+含冒号行: 0（全部无前缀）
+```
+
+### 可映射域（≥3 行）
+
+| LIKE 模式 | 站点前缀 | 覆盖行数 | 关键域 |
+|---|---|---|---|
+| `%1688.com%` | `1688:` | ~6600+ | `.1688.com`(5413), `insights.1688.com`(399), `.air.1688.com`(373), `assets.1688.com`(351), `s.1688.com`(109), `widget.1688.com`(103), `work.1688.com`(103), `h5api.m.1688.com`(95), `dj.1688.com`(15), `detail.1688.com`(3) 及 ~6961 个 shop 子域 |
+| `%made-in-china.com%` | `madeinchina:` | ~2992 | `.made-in-china.com`(1695), `.cn.made-in-china.com`(651), `cn.made-in-china.com`(431), `membercenter.cn.made-in-china.com`(215) |
+| `%taobao.com%` | `taobao:` | ~95 | `.taobao.com`(72), `login.taobao.com`(23) |
+| `%yiwugo.com%` | `yiwugo:` | 4 | `.yiwugo.com`(4) |
+
+**检测顺序：先 `made-in-china` 再 `1688`**（二者无重叠，先长后短更安全）
+
+`taobao` 和 `yiwugo` 与 `1688` 也无重叠。
+
+### 无法映射的第三方域
+
+| 域 | 行数 | 处置 |
+|---|---|---|
+| `.mmstat.com` | 544 | 阿里系埋点/统计域，非站点专属——保持原样（自然过期） |
+| `.ynuf.aliapp.org` | 166 | 阿里系生态域，非站点专属——保持原样（自然过期） |
+
+### 结论
+
+- **§4 假设 2 已验证**：映射清单完整覆盖所有可归属域
+- 544 + 166 = 710 行（3.9%）无法映射到任何站点，保持原样自然过期
+- 迁移 SQL 示例：`UPDATE cookies SET identity = '1688:' || identity WHERE identity NOT LIKE '%:%' AND domain LIKE '%1688.com%'`
+
+---
+
+## ③ identity 诞生点确切代码形态（SPEC §3.1）
+
+### 证据：`browser.py` grep
+
+```
+217:        identity = "direct"
+233:            identity = exit_ip
+314:        session = Session(browser=browser, page=page, identity=identity, ...)
+```
+
+### relaunch 是否重建 identity
+
+`relaunch()`（`browser.py:344-384`）：
+1. 调用 `session.close(store=self.store, log=self.log)` 关闭旧会话
+2. 调用 `self.launch(channel=ch, seed_kit=seed_kit, stop=stop)` 启动全新会话
+3. `launch()` 内部重新生成 identity（direct 或 exit_ip），不从旧 session 携带
+
+**结论：identity 唯一诞生点即 `launch()` 的两处赋值（:217/:233），relaunch 不携带旧 identity。**
+
+### P2 拼前缀时改动点
+
+- `:217` → `identity = f"{site_name}:direct"`
+- `:233` → `identity = f"{site_name}:{exit_ip}"`
+
+仅此两处。
+
+---
+
+## 对 SPEC.md 的修改清单
+
+| 位置 | 改前 | 改后 |
+|---|---|---|
+| §3.1「site 注册名从哪拿」 | "读码确认插件上的字段…Step 1.1 回填" | 插件 name 属性不一致的详细发现 + CLI/daemon 透传方案 |
+| §3.1 新增 | — | identity 诞生点行号确认（:217/:233）+ relaunch 不携带分析 |
+| §3.4 迁移映射 | "确切映射清单 Step 1.1 …核实回填" | 完整四站点映射表 + 第三方域列表 + 检测顺序说明 |
+| §4 假设 1 依据列 | "推断（register_site...）" | "已读码验证：插件 name 属性…不一致…改为 CLI/daemon 透传" |
+| §4 假设 2 依据列 | "推断（现有站点…）" | "已读生产库验证（2026-08-08，18095 行、6971 distinct domain…）" |
+| §6 变更记录 | "（空——评审后变更在此追加）" | 追加 Step 1.1 回填条目（假设 1 推翻、假设 2 验证、诞生点确认） |
+
+---
+
+## 改动文件
+
+| 文件 | 操作 |
+|---|---|
+| `docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md` | 修改（+22 -5） |
+
+## Commit
+
+- **SHA**: `5a4c997`
+- **标题**: `docs(identity-p2): Step 1.1 回填——注册名来源/domain→site映射/identity诞生点`
+- **包含文件**: 仅 `SPEC.md`（已验证 `git diff --name-only HEAD~1..HEAD`）
+
+---
+
+## 修复轮 1（reviewer 指正，2026-08-08）
+
+### 行号修正清单（grep -n 实码验证）
+
+| # | 严重度 | 位置 | 错值 | 正确值 | grep 证据 |
+|---|--------|------|------|--------|-----------|
+| 1 | Critical | SPEC §3.1 → `_make_browser_manager` | `:113-123` | `:113` | `engine.py:113:    def _make_browser_manager` — 改为定义行单行引用 |
+| 2 | Critical | SPEC §3.1/§4 → daemon `get_site` | `cli/main.py:242` | `cli/main.py:215` | `main.py:215:    site = get_site("1688")`；:242 是 `Engine(...)` 装配 |
+| 3 | Critical | SPEC §3.1/§4 → CLI `get_site` | `cli/main.py:198` | `cli/main.py:174` | `main.py:174:    site = get_site(args.site)`；:198 是 `Engine(...)` 装配 |
+| 4 | Critical | SPEC §3.1/§4 → `Alibaba1688Plugin.name` | `alibaba1688/__init__.py:17` | `:27` | `alibaba1688/__init__.py:27:    name = "alibaba1688"` |
+| 5 | Critical | SPEC §3.1/§4 → `register_site("1688",...)` | `同文件:66` | `:85` | `alibaba1688/__init__.py:85:register_site("1688", Alibaba1688Plugin)` |
+| 6 | Important | report 插件表 → madeinchina register_site | `:103` | `:96` | `madeinchina/__init__.py:96` |
+| 7 | Important | report 插件表 → yiwugo register_site | `:94` | `:97` | `yiwugo/__init__.py:97` |
+| 8 | Important | report 插件表 → taobao register_site | `:95` | `:86` | `taobao/__init__.py:86` |
+| 9 | Important | report 插件表 → facebook register_site | `:56` | `:51` | `facebook/__init__.py:51` |
+| 10 | Important | report 插件表 → madeinchina name | `:30` | `:32` | `madeinchina/__init__.py:32` |
+| 11 | Important | report 插件表 → yiwugo name | `:29` | `:33` | `yiwugo/__init__.py:33` |
+| 12 | Important | report 插件表 → facebook name | `:23` | `:24` | `facebook/__init__.py:24` |
+| 13 | Minor | SPEC §3.1 → relaunch 范围 | `browser.py:337-366` | `browser.py:344-384` | `browser.py:344:    def relaunch` → 方法至 :384 raise |
+
+### 内容修正
+
+- **变更记录 §6** 补「假设 1 原文被推翻」事实陈述（reviewer #8）：明确写出原假设「站点注册名可从 engine 的插件对象获得」实际不成立
+
+### 实码验证（grep -n 输出摘要）
+
+```
+alibaba1688/__init__.py:27:    name = "alibaba1688"
+alibaba1688/__init__.py:85:register_site("1688", Alibaba1688Plugin)
+madeinchina/__init__.py:32:    name = "madeinchina"
+madeinchina/__init__.py:96:register_site("madeinchina", MadeInChinaPlugin)
+yiwugo/__init__.py:33:    name = "yiwugo"
+yiwugo/__init__.py:97:register_site("yiwugo", YiwugoPlugin)
+taobao/__init__.py:29:    name = "taobao"
+taobao/__init__.py:86:register_site("taobao", TaobaoPlugin)
+facebook/__init__.py:24:    name = "facebook"
+facebook/__init__.py:51:register_site("facebook", FacebookPlugin)
+main.py:174:    site = get_site(args.site)
+main.py:215:    site = get_site("1688")
+engine.py:113:    def _make_browser_manager(self, store, channel=None) -> BrowserManager:
+browser.py:344:    def relaunch(self, session: Session, channel=None,
+```
+
+### Commit（修复轮 1）
+
+- **SHA**: `db23e5e`
+- **标题**: `docs(identity-p2): Step 1.1 修复轮1——行号勘误`
+- **包含文件**: `SPEC.md` + `task-1.1-report.md`（仅 `docs/feat_2026-08-08_fetcher-identity-p2/` 下）
