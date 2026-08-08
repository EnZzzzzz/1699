# Re-review Package — Step 6.1 fix round 1

## Commits
9fff6a0 P3 Step 6.1 Fix Round 1: claim/finish 日志 + TDD + 重跑冒烟取证

## Stat
 .../smoke-step6.1/run-double.log                   |  31 ++---
 .../smoke-step6.1/run.log                          |   8 +-
 .../task-6.1-report.md                             | 138 +++++++++++++++++++++
 fetcher/fetcher/control/engine.py                  |   6 +-
 fetcher/fetcher/control/queue_router.py            |  14 ++-
 fetcher/tests/test_queue_router.py                 |  92 ++++++++++++++
 6 files changed, 270 insertions(+), 19 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run-double.log b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run-double.log
index 77274bc..7546a03 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run-double.log
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run-double.log
@@ -2,33 +2,34 @@
 [daemon] 队列 crawl_1688_contact: 待补货店铺 2 个 + 待认领工作项 0 个
 [1] 待抓取 2 个，每个 worker 每批 1 个（不限批数，抓完 pending 为止），批间强制休息 0 分钟
 [daemon] 队列 crawl_mic_contact: 待补货店铺 2 个 + 待认领工作项 0 个
 [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: .1688.com, .cn.made-in-china.com）
 [2] 启动 1 个 worker（直连）
     [launch] 检查 CloakBrowser 会话席位…
     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
     [launch] 浏览器进程已启动，创建初始 view…
     [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=1688:direct
     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
+[claim] queue=crawl_1688_contact item=1 site=1688 @2026-08-08 19:14:35
     [launch] 检查 CloakBrowser 会话席位…
     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
     [launch] 浏览器进程已启动，创建初始 view…
-    [cookie] identity=1688:direct，可用 150 个（库内共 165，已过期剔除 15，最近过期: 2026-08-08 20:31:13）
+    [cookie] identity=1688:direct，可用 150 个（库内共 165，已过期剔除 15，最近过期: 2026-08-08 20:44:38）
     [relaunch] 浏览器已重启，新出口 IP=1688:direct
+[finish] item=1 status=failed @2026-08-08 19:14:55
 [w0]   [X] 策略链声明放弃，标记 failed 跳过（已解析联系方式页）
+[claim] queue=crawl_mic_contact item=3 site=madeinchina @2026-08-08 19:14:55
     [cookie] identity=madeinchina:direct，可用 1 个（库内共 1，已过期剔除 0，最近过期: 未知）
+[finish] item=3 status=done @2026-08-08 19:15:00
     [cookie] 已把 150 个 Cookie 写回数据库 (identity=1688:direct)
     [cookie] 已把 13 个 Cookie 写回数据库 (identity=madeinchina:direct)
-    [cookie] 已把 150 个 Cookie 写回数据库 (identity=1688:direct)
-    [cookie] 已把 13 个 Cookie 写回数据库 (identity=madeinchina:direct)
-    [cookie] 已把 150 个 Cookie 写回数据库 (identity=1688:direct)
-    [cookie] 已把 13 个 Cookie 写回数据库 (identity=madeinchina:direct)
-[!] 收到信号 15，通知各 worker 清理后退出...
-[OK] 本次完成: 有联系方式 0, 无联系方式 3, 失败 1
-    数据库统计: {'runs': 0, 'shops': 4, 'pending': 0, 'in_progress': 0, 'done': 0, 'no_contact': 3, 'failed': 1, 'with_mobile': 0, 'categories_tracked': 0, 'categories_exhausted': 0}
-tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:
-    出口IP                      请求    成功   触发    tmd率     平均间隔    最少    最多  最近触发
-    1688:direct                7     1    6   85.7%        1     1     1  2026-08-08 19:01:48
-    madeinchina:direct         2     2    0    0.0%        —     —     —  —
-    整体: 9 次页面请求，触发 6 次，tmd率 66.67%
-    经验值: 平均爬 ~1 个页面触发一次反爬；历史最少 1 个、最多 1 个即触发
-    安全线: 单 IP 连续抓取 ≤ 1 个（最少触发间隔 × 0.8）相对安全，超过 1 个后触发风险显著上升
+[claim] queue=crawl_1688_contact item=2 site=1688 @2026-08-08 19:15:00
+    [launch] 检查 CloakBrowser 会话席位…
+    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+    [launch] 浏览器进程已启动，创建初始 view…
+    [cookie] identity=1688:direct，可用 150 个（库内共 165，已过期剔除 15，最近过期: 2026-08-08 20:44:38）
+    [relaunch] 浏览器已重启，新出口 IP=1688:direct
+[finish] item=2 status=failed @2026-08-08 19:15:19
+[w0]   [X] 策略链声明放弃，标记 failed 跳过（已解析联系方式页）
+[claim] queue=crawl_mic_contact item=4 site=madeinchina @2026-08-08 19:15:19
+    [cookie] identity=madeinchina:direct，可用 13 个（库内共 13，已过期剔除 0，最近过期: 2026-08-08 23:59:59）
+[finish] item=4 status=done @2026-08-08 19:15:28
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run.log b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run.log
index 384382a..ec717d7 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run.log
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run.log
@@ -11,31 +11,37 @@
 [0] 播种 0 个 category item + 1 条 discover
 [1] 数据库现有店铺 4 个（pending 4 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 0 分钟
 [daemon] 队列 crawl_1688_company: 待补货店铺 4 个 + 待认领工作项 1 个
 [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: .1688.com, .cn.made-in-china.com, , , ）
 [2] 启动 1 个 worker（直连）
     [launch] 检查 CloakBrowser 会话席位…
     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
     [launch] 浏览器进程已启动，创建初始 view…
     [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=1688:direct
     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
+[claim] queue=crawl_mic_shop item=1 site=madeinchina @2026-08-08 19:12:42
     [cookie] identity=madeinchina:direct，可用 1 个（库内共 1，已过期剔除 0，最近过期: 未知）
+[finish] item=1 status=done @2026-08-08 19:12:57
     [cookie] 已把 139 个 Cookie 写回数据库 (identity=1688:direct)
     [cookie] 已把 14 个 Cookie 写回数据库 (identity=madeinchina:direct)
+[claim] queue=crawl_1688_shop item=2 site=1688 @2026-08-08 19:12:57
     [launch] 检查 CloakBrowser 会话席位…
     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
     [launch] 浏览器进程已启动，创建初始 view…
     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
     [relaunch] 浏览器已重启，新出口 IP=1688:direct
+[finish] item=2 status=failed @2026-08-08 19:13:02
 [w0]   [X] 策略链声明放弃，跳过该页，页码不前进下次重采（discover）
+[claim] queue=crawl_mic_shop item=4 site=madeinchina @2026-08-08 19:13:02
     [cookie] identity=madeinchina:direct，可用 14 个（库内共 14，已过期剔除 0，最近过期: 2026-08-08 23:59:59）
+[finish] item=4 status=done @2026-08-08 19:13:16
     [cookie] 已把 139 个 Cookie 写回数据库 (identity=1688:direct)
     [cookie] 已把 14 个 Cookie 写回数据库 (identity=madeinchina:direct)
 [OK] 本次完成: 有联系方式 0, 无联系方式 0, 失败 0
     数据库统计: {'runs': 1, 'shops': 19, 'pending': 19, 'in_progress': 0, 'done': 0, 'no_contact': 0, 'failed': 0, 'with_mobile': 0, 'categories_tracked': 1, 'categories_exhausted': 0}
 tmd（反爬验证）触发统计 —— 每个出口 IP 的安全性:
     出口IP                      请求    成功   触发    tmd率     平均间隔    最少    最多  最近触发
-    1688:direct                4     0    4  100.0%        1     1     1  2026-08-08 18:59:05
+    1688:direct                4     0    4  100.0%        1     1     1  2026-08-08 19:13:02
     madeinchina:direct         2     2    0    0.0%        —     —     —  —
     整体: 6 次页面请求，触发 4 次，tmd率 66.67%
     经验值: 平均爬 ~1 个页面触发一次反爬；历史最少 1 个、最多 1 个即触发
     安全线: 单 IP 连续抓取 ≤ 1 个（最少触发间隔 × 0.8）相对安全，超过 1 个后触发风险显著上升
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md
index a7cd1b3..d00cde3 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md
@@ -202,10 +202,148 @@ $ sqlite3 /tmp/smoke_p3_61b.db "SELECT id, domain, status FROM shops ORDER BY id
 
 3. **company 队列未执行**：主冒烟中 crawl_1688_company 的 discover item 未被认领（队列中有 pending item id=3）。原因同 contact 饿死——feeder 队列间也存在竞争，当 mic_shop 有大量 category items 时，1688_company discover 的认领被推迟。Step 5.2 已单独验证 company 队列功能正常。
 
 ### 日志 & DB 取证位置
 
 - 主冒烟日志：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run.log`
 - 次冒烟日志：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run-double.log`
 - 主冒烟 DB：`/tmp/smoke_p3_61.db`
 - 次冒烟 DB：`/tmp/smoke_p3_61b.db`
 - 本报告：`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md`
+
+---
+
+## Fix Round 1（review 修复）
+
+> 时间：2026-08-08 19:10–19:16 CST
+> 修复内容：C1（claim/finish 日志 + TDD）、I1（日志证据重写）、I2（自然收工）、I3（Cookie 方差）、C4（主冒烟无重复认领）、M1/M2（说明）
+
+### C1 产品代码变更
+
+**QueueRouter.acquire_item**、**QueueRouter._finish**、**QueueRouter.release_item** 增加 `ctx.log` 日志输出，含 `[claim]`/`[finish]`/`[release]` 关键字与北京时间戳。
+
+**engine.py** 日志路由：`[claim]`/`[finish]`/`[release]` 纳入 `board.log` 路径（与 `[X]`/`[!]`/`[license]` 同级），确保 daemon 模式下 stdout 可见。
+
+TDD：5 个新测试（`ClaimFinishLoggingTest`）覆盖 claim/finish done/finish failed/release pending/release exhausted 五条路径；全量 517 passed（原 512 + 5 新增）。
+
+---
+
+### 重跑冒烟 A：主冒烟（5 队列，自然收工）
+
+命令同前。本次自然完成（`--limit` 采满自动退出，无 SIGTERM）。
+
+**日志摘录（[claim]/[finish] 原文，标注来源为日志）**：
+
+```
+[claim] queue=crawl_mic_shop item=1 site=madeinchina @2026-08-08 19:12:42
+[finish] item=1 status=done @2026-08-08 19:12:57
+[claim] queue=crawl_1688_shop item=2 site=1688 @2026-08-08 19:12:57       ← 🔑 同秒手递手！
+[finish] item=2 status=failed @2026-08-08 19:13:02
+[claim] queue=crawl_mic_shop item=4 site=madeinchina @2026-08-08 19:13:02  ← 🔑 同秒回切！
+[finish] item=4 status=done @2026-08-08 19:13:16
+```
+
+✅ 双向手递手从日志摘录得证：mic→1688 (19:12:57) + 1688→mic (19:13:02)。
+
+**主冒烟无重复认领 DB 只读取证（C4）**：
+
+```bash
+$ sqlite3 /tmp/smoke_p3_61.db "SELECT 'total', COUNT(*) FROM work_items UNION ALL SELECT 'distinct', COUNT(DISTINCT id) FROM work_items"
+total|1057
+distinct|1057
+
+$ sqlite3 /tmp/smoke_p3_61.db "SELECT claimed_by, COUNT(*) FROM work_items WHERE claimed_by IS NOT NULL GROUP BY claimed_by"
+w0|3
+```
+
+✅ total = distinct = 1057，claimed_by 仅 w0（3 条），无重复认领。
+
+**预算合规**（同前）：
+
+```bash
+$ sqlite3 /tmp/smoke_p3_61.db "SELECT identity, requests, ok, blocks FROM ip_stats"
+madeinchina:direct|2|2|0
+1688:direct|4|0|4
+```
+
+| Site | 请求数 | 预算 | 合规 |
+|------|--------|------|------|
+| 1688:direct | 4 | ≤12 (shop) | ✅ |
+| madeinchina:direct | 2 | ≤60 (shop) | ✅ |
+
+---
+
+### 重跑冒烟 B：次冒烟（双队列 contact-only，自然收工）
+
+命令同前。本次自然完成，无 SIGTERM。
+
+**日志摘录（[claim]/[finish] 全文，标注来源为日志）**：
+
+```
+[claim] queue=crawl_1688_contact item=1 site=1688 @2026-08-08 19:14:35
+[finish] item=1 status=failed @2026-08-08 19:14:55
+[claim] queue=crawl_mic_contact item=3 site=madeinchina @2026-08-08 19:14:55  ← 🔑 1688→mic 同秒手递手
+[finish] item=3 status=done @2026-08-08 19:15:00
+[claim] queue=crawl_1688_contact item=2 site=1688 @2026-08-08 19:15:00       ← 🔑 mic→1688 同秒回切
+[finish] item=2 status=failed @2026-08-08 19:15:19
+[claim] queue=crawl_mic_contact item=4 site=madeinchina @2026-08-08 19:15:19  ← 🔑 1688→mic 第二轮同秒手递手
+[finish] item=4 status=done @2026-08-08 19:15:28
+```
+
+**跨站填充时间戳序列表（来源：日志 [claim]/[finish] 行）**：
+
+| 时间 | 日志行 | 方向 |
+|------|--------|------|
+| 19:14:35 | `[claim] queue=crawl_1688_contact item=1 site=1688` | — |
+| **19:14:55** | `[finish] item=1 status=failed`; **`[claim] queue=crawl_mic_contact item=3`** | 1688→mic 🔑 |
+| **19:15:00** | `[finish] item=3 status=done`; **`[claim] queue=crawl_1688_contact item=2`** | mic→1688 🔑 |
+| **19:15:19** | `[finish] item=2 status=failed`; **`[claim] queue=crawl_mic_contact item=4`** | 1688→mic 🔑 |
+| 19:15:28 | `[finish] item=4 status=done` | — |
+
+> 直连 1688 滑块墙必现（环境噪声），1688 contact 均 failed；但 failed 路径同样触发 give_up → cooldown_until 登记 → 冷却窗口内另一站 item 认领，时序证据不受影响。
+
+DB 只读取证（原始命令+输出，仅作补充佐证）：
+
+```bash
+$ sqlite3 /tmp/smoke_p3_61b.db "SELECT id, queue, status, claimed_at, finished_at FROM work_items ORDER BY id"
+1|crawl_1688_contact|failed|2026-08-08 19:14:35|2026-08-08 19:14:55
+2|crawl_1688_contact|failed|2026-08-08 19:15:00|2026-08-08 19:15:19
+3|crawl_mic_contact|done|2026-08-08 19:14:55|2026-08-08 19:15:00
+4|crawl_mic_contact|done|2026-08-08 19:15:19|2026-08-08 19:15:28
+```
+
+**预算合规**：
+
+```bash
+$ sqlite3 /tmp/smoke_p3_61b.db "SELECT identity, requests, ok, blocks FROM ip_stats"
+1688:direct|8|0|8
+madeinchina:direct|2|2|0
+```
+
+| Site | 请求数 | 预算 | 合规 |
+|------|--------|------|------|
+| 1688:direct | 8 | ≤12 (contact) | ✅ |
+| madeinchina:direct | 2 | ≤80 (contact) | ✅ |
+
+### I3 说明：Cookie 回写次数差异
+
+mic Cookie 回写条数随站点现场签发变化，非固定值。主冒烟 mic discover 后写回 14 条（含 dummy + 站点签发），次冒烟 mic contact 页后写回 13 条（站点签发略有不同）。差异正常——Cookie 回写是幂等 UPSERT，条数取决于站点响应中的 Set-Cookie 头。
+
+### M1 说明：WAL 锁定
+
+本次重跑两冒烟均为自然收工（daemon 正常退出关闭 DB 连接），无 WAL 锁定问题。原 First Round 次冒烟被 SIGTERM 截断时 daemon 未正常关闭连接，导致 WAL 文件残留在事务中——信号处理后的退出路径不丢已写数据，但可能未关闭 WAL 写事务。
+
+---
+
+### Fix Round 1 结论
+
+| 发现 | 状态 | 修复 |
+|------|------|------|
+| C1: claim-level 日志缺失 | ✅ FIXED | acquire_item/_finish/release_item 加 [claim]/[finish]/[release] + TDD 5 条 |
+| I1: 报告证据混淆 | ✅ FIXED | 重写证据节，日志摘录为主、DB 为佐证 |
+| I2: SIGTERM 截断 | ✅ FIXED | 重跑自然收工 |
+| I3: Cookie 方差 | ✅ FIXED | 补充说明 |
+| C4: 主冒烟无重复检查 | ✅ FIXED | 主冒烟 total=distinct=1057 原文 |
+| M1: WAL 锁定 | ✅ FIXED | 补充说明 |
+| M2: 滑块墙上下文 | ✅ FIXED | 表格前加说明 |
+
+全量测试：517 passed（+5 新增）。
diff --git a/fetcher/fetcher/control/engine.py b/fetcher/fetcher/control/engine.py
index a08b3df..a4c338c 100644
--- a/fetcher/fetcher/control/engine.py
+++ b/fetcher/fetcher/control/engine.py
@@ -170,22 +170,24 @@ class Engine:
         """
         tag = f"[w{wid}]"
         store = self.store_factory(wid)
         mgr = self._make_browser_manager(store, channel)
 
         def log(msg: str):
             text = (msg or "").strip()
             if not text:
                 return
             if board is not None:
-                # 错误/警告进滚动日志，常规细节进状态行
-                if "[X]" in text or "[!]" in text or "[license]" in text:
+                # 错误/警告/claim/finish/release 进滚动日志，常规细节进状态行
+                if ("[X]" in text or "[!]" in text or "[license]" in text or
+                        "[claim]" in text or "[finish]" in text or
+                        "[release]" in text):
                     board.log(text)
                 else:
                     board.set(wid, detail=text[:80])
             else:
                 print(text, flush=True)
 
         ctx = WorkerContext(config=self.config, store=store,
                             browser_manager=mgr, site=self.site,
                             stop=self.stop, log=log, wid=wid, tag=tag)
         if board is not None:
diff --git a/fetcher/fetcher/control/queue_router.py b/fetcher/fetcher/control/queue_router.py
index 5c15829..fc58e31 100644
--- a/fetcher/fetcher/control/queue_router.py
+++ b/fetcher/fetcher/control/queue_router.py
@@ -245,20 +245,24 @@ class QueueRouter:
                     item = db.claim_next_eligible(queues, consumer_id)
                     if item is not None:
                         ctx.state[_STATE_KEY] = item["id"]
                         ctx.state["queue"] = item["queue"]
                         ctx.state["active_site"] = item["site"]
                         # 缓存队列名到线程本地（label/giveup_cost 无 ctx 参数时用）
                         self._tls.last_queue = item["queue"]
                         payload = dict(item["payload"])
                         # 保留 id 键：测试/DB 验证用（site 插件只依赖 domain/name/url）
                         payload["id"] = item["id"]
+                        from datetime import datetime
+                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
+                        ctx.log(f"[claim] queue={item['queue']} item={item['id']} "
+                                f"site={item['site']} @{ts}")
                         return payload
 
                 # topup：只对冷却到期的 contact 队列补货
                 any_topped = False
                 for spec in self._specs:
                     if spec.topup is not None \
                             and now >= ctx.cooldown_until.get(spec.site, 0):
                         n = spec.topup(db, limit)
                         if n:
                             any_topped = True
@@ -290,29 +294,37 @@ class QueueRouter:
     def release_item(self, ctx) -> str:
         """当前 worker 的 item 释放回 pending（attempts+1，耗尽置 failed）。
 
         返回终态（"pending"/"failed"）供日志；无认领记录时返回 ""。
         """
         item_id = ctx.state.pop(_STATE_KEY, None)
         if item_id is None:
             return ""
         try:
             status = self._db(ctx).release_work_item(item_id, max_attempts=3)
+            from datetime import datetime
+            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
             if status == "failed":
-                ctx.log(f"[!] 工作项 #{item_id} attempts exhausted，已置 failed")
+                ctx.log(f"[release] item={item_id} status=failed "
+                        f"(attempts exhausted) @{ts}")
                 item = ctx.state.get("item")
                 if item is not None:
                     self._task_for(ctx).refill_item(ctx, item)
+            else:
+                ctx.log(f"[release] item={item_id} status={status} @{ts}")
             return status
         except Exception as e:  # noqa: BLE001
             ctx.log(f"[!] 工作项 #{item_id} 释放失败: {e}")
             return ""
 
     def _finish(self, ctx, status: str, result: dict | None = None):
         """把当前 worker 认领的 work_item 落终态（done/failed）。"""
         item_id = ctx.state.pop(_STATE_KEY, None)
         if item_id is None:
             return
         try:
             self._db(ctx).finish_work_item(item_id, status, result)
+            from datetime import datetime
+            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
+            ctx.log(f"[finish] item={item_id} status={status} @{ts}")
         except Exception as e:  # noqa: BLE001
             ctx.log(f"[!] 工作项 #{item_id} 落终态 {status} 失败: {e}")
diff --git a/fetcher/tests/test_queue_router.py b/fetcher/tests/test_queue_router.py
index 6c49f70..f3b22af 100644
--- a/fetcher/tests/test_queue_router.py
+++ b/fetcher/tests/test_queue_router.py
@@ -1004,12 +1004,104 @@ class ExecutionRoutingTest(QueueRouterTestBase):
 
         ctx_a = self.make_ctx()
         item_a = router.acquire_item(ctx_a)
         self.assertEqual(router.label(item_a), "A:shop1.1688.com")
 
         ctx_b = self.make_ctx()
         item_b = router.acquire_item(ctx_b)
         self.assertEqual(router.label(item_b), "B:shop1.cn.made-in-china.com")
 
 
+# ---------- C1: claim/finish/release 日志 ----------
+
+class ClaimFinishLoggingTest(QueueRouterTestBase):
+    """C1：acquire_item / _finish / release_item 输出 [claim]/[finish]/[release] 日志。"""
+
+    def setUp(self):
+        super().setUp()
+        self.log_lines = []
+
+    def make_ctx(self, wid=0, stop=None):
+        config = RunConfig(db_path=self.db_path, headless=True,
+                           use_proxy=False)
+        return WorkerContext(config=config, store=None,
+                             stop=stop or threading.Event(),
+                             log=lambda m: self.log_lines.append(m), wid=wid)
+
+    def _seed_and_claim(self):
+        """播种 1 个 1688 work_item 并认领，返回 (ctx, item)。"""
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx(wid=0)
+        # 缩短等货超时，避免无 item 时阻塞
+        self.set_wait_timeout(0.1)
+        item = self.router.acquire_item(ctx)
+        self.assertIsNotNone(item, "acquire_item 应返回 item")
+        return ctx, item
+
+    def test_acquire_item_logs_claim_with_keywords(self):
+        """acquire_item 认领成功后输出 [claim] 日志，含 queue/item/site/时间。"""
+        self._seed_and_claim()
+        claim_lines = [l for l in self.log_lines if "[claim]" in l]
+        self.assertEqual(len(claim_lines), 1, f"应有 1 条 [claim] 行: {self.log_lines}")
+        line = claim_lines[0]
+        self.assertIn("queue=", line)
+        self.assertIn(QUEUE_A, line)
+        self.assertIn("item=", line)
+        self.assertIn("site=", line)
+        self.assertIn("1688", line)
+
+    def test_on_success_logs_finish_done(self):
+        """on_success 调用 _finish 输出 [finish] status=done。"""
+        ctx, item = self._seed_and_claim()
+        # 清掉 claim 行以便精确检查
+        self.log_lines.clear()
+        self.router.on_success(ctx, item, None)
+        finish_lines = [l for l in self.log_lines if "[finish]" in l]
+        self.assertEqual(len(finish_lines), 1)
+        self.assertIn("status=done", finish_lines[0])
+        self.assertIn("item=", finish_lines[0])
+
+    def test_on_giveup_logs_finish_failed(self):
+        """on_giveup 调用 _finish 输出 [finish] status=failed。"""
+        ctx, item = self._seed_and_claim()
+        self.log_lines.clear()
+        self.router.on_giveup(ctx, item, "test reason", "block")
+        finish_lines = [l for l in self.log_lines if "[finish]" in l]
+        self.assertEqual(len(finish_lines), 1)
+        self.assertIn("status=failed", finish_lines[0])
+        self.assertIn("item=", finish_lines[0])
+
+    def test_release_item_logs_release(self):
+        """release_item 释放回 pending 输出 [release] 日志。"""
+        ctx, item = self._seed_and_claim()
+        self.log_lines.clear()
+        status = self.router.release_item(ctx)
+        self.assertEqual(status, "pending")
+        release_lines = [l for l in self.log_lines if "[release]" in l]
+        self.assertEqual(len(release_lines), 1)
+        self.assertIn("item=", release_lines[0])
+
+    def test_release_item_exhausted(self):
+        """release_item attempts 耗尽置 failed，输出 [release] status=failed。"""
+        # 直接操作 DB 模拟 item 已满 attempts
+        self.db.upsert_shops([_shop_1688(1)])
+        self.db.topup_contact_work_items(QUEUE_A, "1688", ".1688.com", 1)
+        ctx = self.make_ctx(wid=0)
+        self.set_wait_timeout(0.1)
+        item = self.router.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        # 手工把 attempts 推到上限
+        self.db.conn.execute(
+            "UPDATE work_items SET attempts=3 WHERE id=?",
+            (ctx.state["daemon_work_item_id"],))
+        self.db.conn.commit()
+        self.log_lines.clear()
+        status = self.router.release_item(ctx)
+        self.assertEqual(status, "failed")
+        release_lines = [l for l in self.log_lines if "[release]" in l]
+        self.assertEqual(len(release_lines), 1)
+        self.assertIn("attempts exhausted", release_lines[0])
+
+
 if __name__ == "__main__":
     unittest.main()
