# Step 1.1 brief — 读码回填（SPEC §4 假设 1、2）

> 来源：PLAN.md Phase 1 Step 1.1。本文本是你的需求唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699

## 内容

三项读码/读库确认，结论**回填 SPEC.md**（`docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md`）：

### ① 站点注册名从哪拿（SPEC §4 假设 1，回填 SPEC §3.1）

P2 要把 identity 键从「出口 IP」升级为 `f"{site}:{ip}"`，site 必须是站点**注册名**（与 `work_items.site` 同口径：1688 用 "1688" 不是 "alibaba1688"）。读以下代码，确认 engine 的插件对象（`self.site`）上能否拿到这个注册名，确切字段是什么：

- `fetcher/fetcher/sites/__init__.py`：`register_site(name, plugin_cls)` 注册表，注册名清单（1688 / madeinchina / yiwugo / taobao / facebook）。
- `fetcher/fetcher/sites/base.py`：SitePlugin 协议的字段定义（`name: str`）。
- 各站点插件 `fetcher/fetcher/sites/{alibaba1688,madeinchina,yiwugo,taobao,facebook}/__init__.py`：类属性 `name` 与 `register_site(...)` 实参的对应关系。**注意已知疑点：Alibaba1688Plugin 的类属性 name = "alibaba1688"，但注册名是 "1688"，两者不一致**——逐站核实并明确结论。
- `fetcher/fetcher/control/engine.py`：`Engine.__init__`（`self.site`，:42）、`_make_browser_manager`（:113-123，SPEC 说的注入点）、`store_factory`（:49-52，用了 `getattr(site, "cookie_domain", "1688.com")`）。
- `fetcher/fetcher/cli/main.py`：站点分支 `site = get_site(args.site)`（:198 附近）与 daemon 分支 `site = get_site("1688")`（:242 附近，硬编码）。

**结论要求**：明确写出「注册名的确切来源」。若插件对象上没有（1688 大概率拿不到 "1688"），给出可行方案并在 SPEC §3.1 回填：e.g. 由 CLI/daemon 把注册名（`args.site` / `"1688"`）经 Engine 新参透传给 BrowserManager。凡是与 SPEC 原文假设不符的，在 SPEC 文末「变更记录」追加一条（评审后变更在此追加），§4 假设 1 依据列改「已读码验证（附 file:line）」。

### ② cookies domain → site 迁移映射清单（SPEC §4 假设 2，回填 SPEC §3.4）

生产库**只读**统计（WAL 模式、活爬虫在写，**必须只读打开**，禁止任何写操作/禁止触发迁移/禁止建 -wal）：

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('file:.cache/1688.db?mode=ro', uri=True)
for row in conn.execute('SELECT domain, COUNT(*) FROM cookies GROUP BY domain ORDER BY 2 DESC'):
    print(row)
print('with-colon:', conn.execute(\"SELECT COUNT(*) FROM cookies WHERE identity LIKE '%:%'\").fetchone()[0])
print('no-colon  :', conn.execute(\"SELECT COUNT(*) FROM cookies WHERE identity NOT LIKE '%:%'\").fetchone()[0])
conn.close()
"
```

（已知参考：存量 18095 行全部无冒号、637 个 identity；域名大头 .1688.com 5413、.made-in-china.com 1695、.cn.made-in-china.com 651、.mmstat.com 544、cn.made-in-china.com 431、insights.1688.com 399 等。你自己跑一遍拿全量清单，不要用上面截断的。）

各站点 `cookie_domain`：alibaba1688→`1688.com`、madeinchina→`made-in-china.com`（注释说覆盖 cn.* 与 {sub}.cn.* 两级域）、yiwugo→`yiwugo.com`、taobao→`taobao.com`。

**结论要求**：在 SPEC §3.4 回填**确切** domain→site 前缀映射（逐条 LIKE 模式，如 `%1688.com% → 1688:`，覆盖全部 1688 子域；made-in-china 的 cn./membercenter.cn. 形态；taobao 的 login.taobao.com；yiwugo）。**无法归属到任何站点的第三方域**（如 .mmstat.com、.ynuf.aliapp.org 等）逐条列出，处置按 SPEC「保持原样（自然过期）」。§4 假设 2 依据列改「已读码验证（附 file:line 或 SQL）」、映射清单完整写入 §3.4。

### ③ identity 诞生点确切代码形态（回填 SPEC §3.1 行号）

读 `fetcher/fetcher/net/browser.py` 的 `launch()`：确认 `identity = "direct"` 默认值行号、use_proxy 分支 `identity = exit_ip` 的确切行号（SPEC 写 :233 一带，核实），以及 launch/relaunch 里 identity 的所有赋值点（含 relaunch 是否重建 Session——如果 relaunch 重建 Session 但 identity 从旧 session 带过来，说明只有 launch 一处诞生点，回填确认）。**不改代码**，只记录行号与形态。

## 背景

P2 目标：identity 键升级为 `f"{site}:{ip}"`，拼前缀**只许出现在 identity 诞生点一处**（browser.py launch）。后续 Step 1.2/1.3 会按你回填的结论实现，你写错一行后面全错。

## 验收

- [ ] SPEC §4 假设 1、2 依据列改「已读码验证（附 file:line）」，结论明确无歧义
- [ ] §3.1 回填注册名确切来源 + identity 诞生点确切行号；§3.4 回填完整 domain→site 映射清单（含未覆盖域的逐条列出与处置）
- [ ] 与 SPEC 原文不符的假设在「变更记录」追加条目

## 约束

- **只读代码 + 只改 SPEC.md，不改任何 fetcher 代码，不动生产库**（只读 URI 打开）。
- **commit 纪律**：只 `git add docs/feat_2026-08-08_fetcher-identity-p2/SPEC.md`（scoped），提交信息 `docs(identity-p2): Step 1.1 回填…`。**禁止 `git add -A` / `git add .`**。工作区有另一功能的未提交改动（platform/ 多处、fetcher/vendor/wa-check/check.js、docs/feat_2026-08-07_apify-provider-pairing-login/、platform/server/tests/test_wa_pairing_login.py），一概不碰、不提交。
- 用 `git diff` 自查只改了 SPEC.md。

## 报告

完整报告写入 `docs/feat_2026-08-08_fetcher-identity-p2/task-1.1-report.md`：
- 三段的发现与证据（file:line 摘录、SQL 输出、结论）
- 对 SPEC.md 的每一处修改（改前/改后）
- 变更记录条目内容
- 改动的文件、commit（短 SHA + 标题）
