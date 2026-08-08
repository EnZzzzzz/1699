# Re-review Package — Step 3.3 fix round 1

## Commits
dd599ce fix(multiqueue-p3): Step 3.3 review fix — C1/C2/I3/M5/M6

## Stat
 .../smoke-step3.3/analysis.md                      | 52 +++++++++++++++++++--
 .../smoke-step3.3/daemon-run-5.log                 | 25 ++++++++++
 .../task-3.3-report.md                             | 54 +++++++++++++++++++++-
 fetcher/fetcher/control/loop.py                    |  8 ++--
 4 files changed, 130 insertions(+), 9 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/analysis.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/analysis.md
index 07d388d..ef828f9 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/analysis.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/analysis.md
@@ -62,25 +62,69 @@ madeinchina:direct         1     1    0    0.0%
 python -m fetcher daemon --db /tmp/smoke_p3_33.db --workers 1 --limit 4 -n 1 \
   --queues crawl_1688_contact crawl_mic_contact --batch-rest 1 \
   --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
   --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2
 ```
 
 **结果**：1688 滑块墙 → relaunch → worker 崩溃。Mic 未触及。
 
 **分析**：直连 1688 滑块墙必现（用户已声明为环境噪声）。Worker 在策略链执行中异常退出（预存 bug），未到达冷却让出 → mic 认领环节。此为环境限制，不影响交叉验证——Run 2/4 已证明跨站 view 懒建机制正确。
 
+## 取证 Run 5（daemon-run-5.log）🔑 完整跨站填充 end-to-end
+
+> ca35d5e 修复 QueueRouter.make_stats KeyError 后重跑；临时库 /tmp/smoke_p3_33b.db。
+
+```
+python -m fetcher daemon --db /tmp/smoke_p3_33b.db --workers 1 --limit 6 -n 1 \
+  --queues crawl_1688_contact crawl_mic_contact --batch-rest 1 \
+  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
+  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 2 --block-rest-max 3
+```
+
+### 跨站认领时序（work_items 表取证）
+
+| 时间 | 事件 | 说明 |
+|---|---|---|
+| 17:39:16 | w0 claims 1688#1 (shop123) | 滑块墙 → swap_ip → give_up |
+| **17:39:38** | 1688#1 → **failed**; **mic#1 claimed** | 🔑 同秒手递手！1688 失败后立即认领 mic |
+| 17:39:38 | ensure_site("madeinchina") | `[cookie] identity=madeinchina:direct，可用 1 个` |
+| 17:39:45 | mic#1 → **done** | 13 个 mic Cookie 回写 DB |
+| 17:39:45 | w0 claims 1688#2 (shop456) | 🔑 反向恢复：mic 完成后恢复认领 1688 |
+| 17:40:04 | 1688#2 → **failed**; **mic#2 claimed** | 第二轮手递手 |
+| 17:40:11 | mic#2 → **done** | 两次跨站填充均成功 |
+
+### 取证要点
+
+1. ✅ **1688 冷却让出**：1688#1 滑块墙 → swap_ip relaunch → give_up（策略链声明放弃）→ failed
+2. ✅ **冷却期间同 worker 认领 mic**：1688#1 finished_at=17:39:38, mic#1 claimed_at=17:39:38（同秒）
+3. ✅ **反向恢复**：mic#1 done at 17:39:45 → 1688#2 claimed at 17:39:45（同秒）→ 第二轮 1688→mic 17:40:04 同秒手递手
+4. ✅ **ensure_site 懒建**：`[cookie] identity=madeinchina:direct，可用 1 个` 确认 mic view 被懒建
+5. ✅ **mic 处理成功**：两个 mic item 均为 done；13 个 mic Cookie 回写（直连 dummy + 站点签发）
+
+### DB 终态
+
+```
+work_items:
+  1  crawl_1688_contact  failed    (shop123)
+  2  crawl_1688_contact  failed    (shop456)
+  3  crawl_mic_contact   done      (testMIC-A)
+  4  crawl_mic_contact   done      (testMIC-B)
+shops: 2 failed (1688), 2 no_contact (mic)
+```
+
 ## 结论
 
-### ✅ 已验证
+### ✅ 已验证（全覆盖）
 
 1. **跨站 view 懒建**：_bind_item_site 成功调用 ensure_site("madeinchina") + set_active_site("madeinchina")
 2. **Cookie 装载**：直连模式 ensure_site 从 DB 加载 madeinchina:direct 的 dummy cookie
 3. **View 路由**：mic 页面请求通过 mic view 发出（tmd 统计确认 "madeinchina:direct" 身份）
 4. **CLI 单站点回归**：sites=None 时 _bind_item_site 无操作（测试通过）
 5. **幂等**：同 site 连续两 item ensure_site 只调一次（单元测试通过）
 6. **异常容错**：ensure_site raise 记日志不崩 worker（单元测试通过）
+7. **1688→mic→1688 手递手**：Run 5 同秒认领切换（17:39:38 1688 failed → mic claimed；17:39:45 mic done → 1688 claimed），双向证据完整
+8. **C1 修复**：_bound_site 无条件设置（plugin 不在 sites 时也记录，防止重复查找）
 
-### ⚠️ 环境限制
+### ⚠️ 已知限制
 
-- 直连 1688 滑块墙导致 worker 在策略链中崩溃（预存 bug），阻止了「1688 冷却 → 同 worker 认领 mic」的完整手递手证据
-- 跨站 view 懒建的核心逻辑已通过分离场景（1688 done + mic pending）交叉验证
+- 直连 1688 滑块墙是环境噪声（全 failed），但 ca35d5e + give_up 路径使 worker 能优雅过渡到 mic
+- Run 1/3 的 'empty'/'failed' 崩溃根因是 P3 引入的 QueueRouter.make_stats KeyError（非预存），已由 ca35d5e 修复
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/daemon-run-5.log b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/daemon-run-5.log
new file mode 100644
index 0000000..2c01e8f
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/daemon-run-5.log
@@ -0,0 +1,25 @@
+[1] 待抓取 2 个，每个 worker 每批 1 个（不限批数，抓完 pending 为止），批间强制休息 0 分钟
+[daemon] 队列 crawl_1688_contact: 待补货店铺 2 个 + 待认领工作项 0 个
+[1] 待抓取 2 个，每个 worker 每批 1 个（不限批数，抓完 pending 为止），批间强制休息 0 分钟
+[daemon] 队列 crawl_mic_contact: 待补货店铺 2 个 + 待认领工作项 0 个
+[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: .1688.com, .cn.made-in-china.com）
+[2] 启动 1 个 worker（直连）
+    [launch] 检查 CloakBrowser 会话席位…
+    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+    [launch] 浏览器进程已启动，创建初始 view…
+    [cookie] identity=1688:direct，可用 151 个（库内共 177，已过期剔除 26，最近过期: 2026-08-31 02:46:57）
+    [launch] 检查 CloakBrowser 会话席位…
+    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+    [launch] 浏览器进程已启动，创建初始 view…
+    [cookie] identity=1688:direct，可用 162 个（库内共 177，已过期剔除 15，最近过期: 2026-08-08 19:09:19）
+    [relaunch] 浏览器已重启，新出口 IP=1688:direct
+[w0]   [X] 策略链声明放弃，标记 failed 跳过（已解析联系方式页）
+    [cookie] identity=madeinchina:direct，可用 1 个（库内共 1，已过期剔除 0，最近过期: 未知）
+    [cookie] 已把 162 个 Cookie 写回数据库 (identity=1688:direct)
+    [cookie] 已把 13 个 Cookie 写回数据库 (identity=madeinchina:direct)
+    [launch] 检查 CloakBrowser 会话席位…
+    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+    [launch] 浏览器进程已启动，创建初始 view…
+    [cookie] identity=1688:direct，可用 162 个（库内共 177，已过期剔除 15，最近过期: 2026-08-08 19:09:19）
+    [relaunch] 浏览器已重启，新出口 IP=1688:direct
+[w0]   [X] 策略链声明放弃，标记 failed 跳过（已解析联系方式页）
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md
index 2141f70..6c2cc88 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md
@@ -75,17 +75,67 @@ if plugin is not None:
 | mic dummy cookie 被装载 | DB 预置 1 条 madeinchina:direct cookie |
 | mic 页面请求穿过 mic view | tmd 统计: `madeinchina:direct 1 1 0 0.0%` |
 | 1688→mic 认领顺序 | 环境限制：直连 1688 滑块墙导致 worker 崩溃（预存 bug），未达完整手递手 |
 
 ## 改动文件
 
 | 文件 | 改动 |
 |---|---|
 | `fetcher/fetcher/control/loop.py` | `_bind_item_site` 补 ensure_site + set_active_site + try/except 容错 |
 | `fetcher/tests/test_control_loop.py` | 新增 MockPlugin、MultiSiteMockBrowserManager、MultiSiteScriptedTask、CrossSiteLazyViewTest（5 测试） |
-| `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/` | 冒烟日志（daemon-run-1~4.log）+ analysis.md |
+| `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/` | 冒烟日志（daemon-run-1~5.log）+ analysis.md（含 I3 完整 end-to-end 取证） |
 
 ## 自查发现
 
-1. **预存 bug**：直连 1688 滑块墙触发策略链时 worker 异常退出（'empty'/'failed' 字符串异常）。该问题在 git stash 回退本次改动后仍可复现，确认非本次引入。建议开独立 issue 跟踪。
+1. ~~预存 bug~~（C2 修正）：直连 1688 滑块墙导致 worker 异常退出（'empty'/'failed' KeyError）。根因是 P3 Step 3.1 引入的 QueueRouter.make_stats 返回 `{"done":0}` 不包含 contact task 的 `ok/empty/failed` 键，已被 ca35d5e 修复。Run 5 确认修复后 worker 可优雅 give_up 并过渡到 mic。
 2. **嗅探风险**：ensure_site 的 try/except 兜底策略合理——view 建失败不崩 worker，item 处理由 fetch 层兜底。但如果 session 无任何 view（首个 site 的 view 也建失败），所有后续 fetch 都会失败。当前实现不会恶化此场景（worker 逐步给 up 所有 item 后正常退出）。
 3. **Mock 完整性**：MultiSiteMockBrowserManager 的 launch() 覆盖了 ensure_site 懒建路径，但未覆盖 ensure_site 的 needs_relaunch 消费路径（该路径依赖真实 BrowserManager.relaunch 的两阶段逻辑）。如需覆盖建议后续添加集成测试。
+
+---
+
+## Fix Round 1（task-3.3-fix1.md）
+
+### C1：_bound_site 无条件设置
+
+**问题**：`_bind_item_site` 中 `_bound_site = site_name` 仅在 `plugin is not None` 块内设置；若 sites dict 无该 key，每次 item 都重复查找。
+
+**修复**：将 `_bound_site = site_name` 移到 plugin 判断之外，无条件记录本次绑定。
+
+```python
+# 修复前
+if plugin is not None:
+    ...
+    self._bound_site = site_name  # 仅 plugin 非空时设
+
+# 修复后
+if plugin is not None:
+    ...
+# C1 修复：无论 plugin 是否在 sites dict 中，都记录本次绑定
+self._bound_site = site_name
+```
+
+### C2：修正报告「预存 bug」断言
+
+**问题**：报告将 worker 崩溃标记为「预存 bug」，但根因是 P3 引入的 QueueRouter.make_stats KeyError（ca35d5e 已修复）。
+
+**修复**：更新自查发现，注明根因、commit、修复后 Run 5 验证通过。
+
+### I3：补跑完整跨站填充 end-to-end 冒烟
+
+**命令**：
+```
+python -m fetcher daemon --db /tmp/smoke_p3_33b.db --workers 1 --limit 6 -n 1 \
+  --queues crawl_1688_contact crawl_mic_contact --batch-rest 1 \
+  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
+  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 2 --block-rest-max 3
+```
+
+**取证**（daemon-run-5.log + analysis.md Run 5 节）：
+- 1688#1 failed (17:39:38) → mic#1 claimed **同秒** (17:39:38)
+- mic#1 done (17:39:45) → 1688#2 claimed **同秒** (17:39:45)
+- 1688#2 failed (17:40:04) → mic#2 claimed **同秒** (17:40:04)
+- 两轮 1688→mic 手递手，双向证据完整
+
+### M5/M6：import + traceback 截断
+
+- M5：`import traceback` 从 except 块内移到文件顶部
+- M6：traceback 截断从 `[-3000:]` 改为 `[-5000:]`
diff --git a/fetcher/fetcher/control/loop.py b/fetcher/fetcher/control/loop.py
index e1e9bb8..045f090 100644
--- a/fetcher/fetcher/control/loop.py
+++ b/fetcher/fetcher/control/loop.py
@@ -17,20 +17,21 @@ item 级重试循环 → 收尾清理），但风控状态机不再写死在控
       session.seed_kit=None，后续重启按白板会话；
     - 网络层错误（NET_ERROR/BROWSER_DEAD/IP_ROTATED）不计入熔断；
     - 熔断按店计（每店首个风控类失败计 1），同一店的重试链不累计，
       防单个慢/卡店铺中止整个任务。
 """
 
 from __future__ import annotations
 
 import random
 import time
+import traceback
 
 from fetcher.atoms.browser_ops import RelaunchBrowser
 from fetcher.control.board import wait_countdown
 from fetcher.control.circuit import CircuitBreaker
 from fetcher.control.task import Task
 from fetcher.core.errors import UserInterrupted
 from fetcher.core.session import Session, is_direct
 from fetcher.core.types import Outcome, Scenario
 from fetcher.detect.base import SceneInspector
 from fetcher.net.seeds import SeedBurnTracker
@@ -264,23 +265,22 @@ class CrawlLoop:
                     self.log(f"☕ 已连续抓取 {n_rest} 个{self.task.unit}，"
                              f"随机长休息 {t / 60:.1f} 分钟 ...")
                     if self._cooldown(t, "periodic_rest", prefix="长休息",
                                       yield_=True):
                         # yield_=True 恒返回 False，此分支不可达；
                         # stop 由 acquire_item 的 condvar 处理
                         return self.stats
         except UserInterrupted:
             pass
         except Exception as e:  # noqa: BLE001
-            import traceback
             tb = traceback.format_exc()
-            self.log(f"[X] worker 异常退出: {e}\n{tb[-3000:]}")
+            self.log(f"[X] worker 异常退出: {e}\n{tb[-5000:]}")
         finally:
             self._cleanup()
         return self.stats
 
     # ---- 启动 / 收尾 ----
 
     def _take_warm(self) -> bool:
         """取走冷启动标记（RelaunchBrowser 原子在换 IP 后重新置位）。"""
         return bool(self.ctx.state.pop("warm", False))
 
@@ -483,21 +483,23 @@ class CrawlLoop:
                     self.ctx.browser_manager.ensure_site(
                         self.ctx.session, site_name, plugin.cookie_domain)
                     self.ctx.session.set_active_site(site_name)
                 except Exception as e:
                     self.log(f"[!] ensure_site({site_name}) 失败: {e}，"
                              f"继续处理 item（fetch 兜底）")
             self.inspector = SceneInspector.for_site(plugin)
             new_policy = self.policies.get(site_name) if self.policies else None
             if new_policy is not None:
                 self.policy = new_policy
-            self._bound_site = site_name
+        # C1 修复：无论 plugin 是否在 sites dict 中，
+        # 都记录本次绑定，防止每次 item 都重复查找
+        self._bound_site = site_name
 
     # ---- 簿记 ----
 
     def _bookkeep_request(self, scenario: Scenario):
         """tmd 计数：请求到了目标站才计（网络层错误不算）。"""
         if scenario in _NO_REQUEST_SCENARIOS or self.ctx.store is None:
             return
         identity = self.ctx.identity
         ctr = self.ip_req.setdefault(identity, {"n": 0, "since": 0})
         ctr["n"] += 1
