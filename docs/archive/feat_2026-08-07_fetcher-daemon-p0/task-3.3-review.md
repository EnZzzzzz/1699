=== git log ===
5a54987 fix(fetcher): 终审修复 daemon docstring 示例与 README --limit 口径（Step 3.3）

=== diff --stat ===
 .../task-3.3-report.md                             | 51 ++++++++++++++++++++++
 fetcher/README.md                                  |  2 +-
 fetcher/fetcher/control/daemon_task.py             |  4 +-
 3 files changed, 54 insertions(+), 3 deletions(-)

=== diff -U10 ===
diff --git a/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.3-report.md b/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.3-report.md
new file mode 100644
index 0000000..7e85636
--- /dev/null
+++ b/docs/feat_2026-08-07_fetcher-daemon-p0/task-3.3-report.md
@@ -0,0 +1,51 @@
+# Task 3.3 终审修复轮报告（docs 级 2 处）
+
+> 终审（final-review.md）结论「通过，附修复项」，本报告记录 2 处合并前必修的一行级文档修复。
+> 终审清单第 1 条提到的两处行号（约 :36 与 :847-848）经全文检索确认：`daemon_task.py` 仅 195 行，
+> `domain_suffix="1688.com"` / `queue="contact"` 错误写法只存在于模块 docstring 示例一处
+> （`cli/main.py:218` 实际装配代码本就是 `.1688.com` / `args.queue`，无第二处需改）。
+
+## 修复 1：`fetcher/fetcher/control/daemon_task.py` 模块 docstring 示例（:35-36）
+
+**前：**
+
+```
+        task = DaemonTaskProxy(inner=ContactTask(), queue="contact",
+                               site="1688", domain_suffix="1688.com")
+```
+
+**后：**
+
+```
+        task = DaemonTaskProxy(inner=ContactTask(), queue="crawl_1688_contact",
+                               site="1688", domain_suffix=".1688.com")
+```
+
+理由：`domain_suffix` 为 substr 后缀匹配，少前导点会误匹配 `evil1688.com` 类域名；
+`"contact"` 非真实队列名，P0 唯一队列是 `crawl_1688_contact`。
+
+## 修复 2：`fetcher/README.md` daemon 说明段（:44-45）
+
+**前：**
+
+```
+`--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
+跑完 N 个后退出，作冒烟/联调的收工手段。
+```
+
+**后：**
+
+```
+`--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
+每个 worker 跑完 N 个后退出，作冒烟/联调的收工手段。
+```
+
+理由：`--limit` 是 per-worker 口径（`cli/main.py:56-57` help 原文「每个 worker 本次最多采集量」），
+README 旧表述易被误读为全局总量。
+
+## 测试验证
+
+```
+$ cd fetcher && python -m pytest tests -x -q
+231 passed, 2 subtests passed in 8.94s
+```
diff --git a/fetcher/README.md b/fetcher/README.md
index 1e59689..c690791 100644
--- a/fetcher/README.md
+++ b/fetcher/README.md
@@ -35,21 +35,21 @@ python -m fetcher 1688 company --proxy --limit 300
 python -m fetcher 1688 contact --tmd-report     # 只出 tmd 报表
 python -m fetcher taobao search --proxy -n 30   # 第二个站点：淘宝商品搜索
 python -m fetcher daemon --proxy                # 常驻模式：1688 contact 从 work_items 队列持续消费
 # 站点/任务子命令由 sites 注册表自动发现生成，加目录即接入
 ```
 
 `daemon` 子命令 = 1688 contact 常驻模式：消费者从 `work_items` 表认领工作项，
 shops 表 pending 行自动补货入队，队列取空后挂起等货而非退出。支持全部共享
 网络层参数（`--proxy` / `--workers` / `--headed` 等，同各任务子命令），另有
 `--queue`（P0 仅默认值 `crawl_1688_contact`，不开放其他选择）；`--limit N`
-跑完 N 个后退出，作冒烟/联调的收工手段。
+每个 worker 跑完 N 个后退出，作冒烟/联调的收工手段。
 **daemon 与旧 CLI `1688 contact` 同站互斥**：两边启动都会把 shops 的
 in_progress 重置为 pending（daemon 另回收 work_items 的 claimed 残留），
 同站同跑会互相重置，同一时刻只跑一个。
 
 ```python
 # 库用法（CLI 即以下装配的薄壳）
 from fetcher import RunConfig, Alibaba1688Plugin, Policy
 from fetcher.net.proxy import QingGuoProvider
 from fetcher.control import Engine
 
diff --git a/fetcher/fetcher/control/daemon_task.py b/fetcher/fetcher/control/daemon_task.py
index 629b52c..27996a1 100644
--- a/fetcher/fetcher/control/daemon_task.py
+++ b/fetcher/fetcher/control/daemon_task.py
@@ -25,22 +25,22 @@ from fetcher.db import ShopDB
 _WAIT_TIMEOUT = 30.0
 
 # ctx.state 上记录当前 worker 认领的 work_item id 的键
 _STATE_KEY = "daemon_work_item_id"
 
 
 class DaemonTaskProxy:
     """Task 协议代理：工作项来源切换为 work_items 表（daemon 常驻等货）。
 
     用法：
-        task = DaemonTaskProxy(inner=ContactTask(), queue="contact",
-                               site="1688", domain_suffix="1688.com")
+        task = DaemonTaskProxy(inner=ContactTask(), queue="crawl_1688_contact",
+                               site="1688", domain_suffix=".1688.com")
         engine = Engine(cfg, task=task, ...)
     """
 
     def __init__(self, inner, queue: str, site: str, domain_suffix: str,
                  db_factory=None):
         self._inner = inner
         self._queue = queue
         self._site = site
         self._domain_suffix = domain_suffix
         # 测试注入用 DB 工厂（无参可调）；None=按 ctx 取（见 _db）
