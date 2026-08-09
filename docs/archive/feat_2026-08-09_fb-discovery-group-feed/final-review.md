# 全分支终审审查包（fb-discovery-group-feed，feature 范围 dbab0da..HEAD）

## 说明：feature 起点 = dbab0da（daemon-headed-queues 独立提交）之后的全部 49 个 commit。
## 全分支范围 main..HEAD = 66 个 commit（含此前已验收的 fb 一期/二期等工作线）。

## Commits (dbab0da..HEAD)
cc45f32 docs(fb): Step 5.3 完成——PLAN checkbox 勾选 + ledger 执行记录
252b24c docs(fb): Step 5.3 同步 AGENTS.md 队列 9 条与批次模型、渠道文档发现层已落地
b1d964e docs(fb): Step 5.2 完成——PLAN checkbox 勾选 + ledger 执行记录
b7191d8 docs(fb): Step 5.2 全量回归——三组全绿（fetcher 740 / 平台 72 / tsc 0 错），验收 6 满足
73a63f0 docs(fb): Step 5.1 完成——端到端五项验收全满足 + ledger 执行记录与发现
2d8eb86 docs(fb): Step 5.1 收尾——恢复 daemon local 消费者 + 验收 4 补验（wa_check 入队链观测）满足，五项验收全 DONE
ebf88d7 Step 5.1: 端到端闭环冒烟 — BLOCKED (daemon 本地消费者停滞)
05276a1 docs(fb): Phase 4 完成——Step 4.5 冒烟勾选 + Phase 4 状态 done
6415e0b docs(fb): Step 4.5 前端冒烟完成——18/18 断言通过（表单默认值/hint/摘要/进度列/编辑回填）+ report
c5635b6 docs(fb): Step 4.4 完成——PLAN checkbox 勾选 + ledger 执行记录
e4a6866 feat(fb): Step 4.4 BATCH_TYPE_NAMES 追加 fb_discover/fb_group（批次进度渲染）
211927a docs(fb): Step 4.3 完成——PLAN checkbox 勾选 + ledger 执行记录
95ff95f fix(fb): Step 4.3 review 第1轮修复——validate() 补 keywords 空 warning + provider 防御校验
8d0f528 feat(fb): Step 4.3 TaskFormDialog 两独立表单分支 (fb_discover/fb_group)
5735a78 docs(fb): Step 4.2 完成——PLAN checkbox 勾选 + ledger 执行记录
9c20140 feat(fb): Step 4.2 task-ui.tsx 追加 fb_discover/fb_group 类型标签与参数摘要
15a0d90 docs(fb): Step 4.1 完成——PLAN checkbox 勾选 + ledger 执行记录
a8edfe3 feat(fb): Step 4.1 前端 api.ts 追加 fb_discover/fb_group 类型
95fd521 docs(fb): Phase 3 完成——Step 3.4 冒烟勾选 + Phase 3 状态 done
c91830e feat(fb): Step 3.4 平台冒烟——start.sh pass-through key（SPEC §6.5）+ 两类型任务创建/启动/停止验收 + ledger/PLAN 记录
e5c5e09 docs(fb): Step 3.3 完成——PLAN checkbox 勾选 + ledger 执行记录
d90e01f feat(fb): Step 3.3 TaskParams 追加 keywords/pages/provider/posts_per_group（TDD）
fd29bf1 docs(fb): Step 3.2 完成——PLAN checkbox 勾选 + ledger 执行记录
6896454 feat(fb): Step 3.2 enqueue_fb_discover/group_batch 真实实现（TDD）+ runner 懒导入收尾
dc717aa docs(fb): Step 3.1 完成——PLAN checkbox 勾选 + ledger 执行记录
61f36e2 style(fb): Step 3.1 fix1 BATCH_TYPES 新条目改为多行 dict 格式（纯格式）
acf205a feat(fb): Step 3.1 runner BATCH_TYPES 注册 fb_discover/fb_group + enqueue 分派（TDD）
966120b docs(fb): Phase 2 完成——Step 2.4 冒烟勾选 + Phase 2 状态 done
de4dd6d docs(fb): Step 2.4 冒烟记录——缺 key FATAL→群 failed 真实链路 + mock done 链路 fb_contacts 落号
3e0e8fe docs(fb): Step 2.3 完成——PLAN checkbox 勾选 + ledger 执行记录
8c58e4e feat(fb): Step 2.3 FbPostTask.on_success 群 upsert 补位——每抓一帖发现一群（TDD）
1f6d100 docs(fb): Step 2.2 完成——PLAN checkbox 勾选 + ledger 执行记录
b9c6ad5 feat(fb): Step 2.2 crawl_fb_group 队列注册——_build_registry 追加 local QueueSpec（TDD）
cb3e02b docs(fb): Step 2.1 完成——PLAN checkbox 勾选 + ledger 执行记录
40e3de9 fix(fb): Step 2.1 review 修复——提取共享 group_id 解析（urls.py）+ on_success 逐帖口径 stats
7a09836 feat(fb): Step 2.1 FbGroupTask——crawl_fb_group local 消费者（TDD）
5e9dce7 docs(fb): Phase 1 完成——Step 1.5 冒烟勾选 + Phase 1 状态 done + ledger 非阻塞发现
715d08d docs(fb): Step 1.5 冒烟 DONE——真实 DDG 抓取落库 1 帖 + 18 群，间隔 62s 达标，ledger 记录
d2507ca docs(fb): Step 1.5 冒烟 BLOCKED——FETCHER_DB_PATH 对 daemon 无效直连生产库，ledger 记录证据
3fabf54 docs(fb): Step 1.4 完成——PLAN checkbox 勾选 + ledger 执行记录
59812e1 feat(fb): Step 1.4 discover_fb 队列注册——_build_registry 追加 local QueueSpec（TDD）
d85f774 docs(fb): Step 1.3 完成——PLAN checkbox 勾选 + ledger 执行记录
5dff797 feat(fb): Step 1.3 FbDiscoverTask——discover_fb 队列 local 消费者（DDG 查询→分流落库，TDD）
ab27fab docs(fb): Step 1.2 完成——PLAN checkbox 勾选 + ledger 执行记录
83c75e2 fix(fb): Step 1.2 review——参数缺省改显式 None 判断（or 反模式吞掉显式 0）
274a409 feat(fb): Step 1.2 FetchDdgSerp 原子 + parse/classify 纯函数（TDD）
4600ca1 docs(fb): Step 1.1 完成——PLAN checkbox 勾选 + ledger 执行记录
96129f8 fix(fb): Step 1.1 review——upsert_fb_groups source 缺省语义收窄 + schema 契约固化测试
b401560 feat(fb): Step 1.1 DB 前置——fb_groups 建表 + save_fb_posts/upsert_fb_groups（TDD）

## Stat
 AGENTS.md                                          |   8 +-
 docs/channel-research/facebook-groups.md           |  20 +-
 .../PLAN.md                                        | 380 ++++++++++++++
 .../SPEC.md                                        | 558 +++++++++++++++++++++
 .../ledger.md                                      | 430 ++++++++++++++++
 .../task-1.1-brief.md                              |  99 ++++
 .../task-1.1-report.md                             | 121 +++++
 .../task-1.2-brief.md                              | 117 +++++
 .../task-1.2-report.md                             | 161 ++++++
 .../task-1.3-brief.md                              | 100 ++++
 .../task-1.3-report.md                             |  80 +++
 .../task-1.4-brief.md                              |  63 +++
 .../task-1.4-report.md                             |  86 ++++
 .../task-1.5-report.md                             | 121 +++++
 .../task-2.1-brief.md                              | 109 ++++
 .../task-2.1-report.md                             | 217 ++++++++
 .../task-2.2-brief.md                              |  57 +++
 .../task-2.2-report.md                             |  99 ++++
 .../task-2.3-brief.md                              |  73 +++
 .../task-2.3-report.md                             |  99 ++++
 .../task-3.1-brief.md                              |  82 +++
 .../task-3.1-report.md                             | 204 ++++++++
 .../task-3.2-brief.md                              |  87 ++++
 .../task-3.2-report.md                             | 115 +++++
 .../task-3.3-brief.md                              |  57 +++
 .../task-3.3-report.md                             |  84 ++++
 .../task-3.4-brief.md                              | 116 +++++
 .../task-3.4-report.md                             | 216 ++++++++
 .../task-4.1-brief.md                              |  39 ++
 .../task-4.1-report.md                             |  41 ++
 .../task-4.2-brief.md                              |  62 +++
 .../task-4.2-report.md                             |  67 +++
 .../task-4.3-brief.md                              | 121 +++++
 .../task-4.3-report.md                             | 170 +++++++
 .../task-4.4-brief.md                              |  30 ++
 .../task-4.4-report.md                             |  39 ++
 .../task-4.5-report.md                             | 135 +++++
 .../task-5.1-report.md                             | 242 +++++++++
 .../task-5.1b-report.md                            | 190 +++++++
 .../task-5.2-report.md                             | 115 +++++
 .../task-5.3-brief.md                              |  66 +++
 .../task-5.3-report.md                             |  36 ++
 fetcher/fetcher/atoms/facebook_discover.py         | 202 ++++++++
 fetcher/fetcher/cli/main.py                        |  25 +
 fetcher/fetcher/db.py                              |  90 ++++
 fetcher/fetcher/sites/facebook/discover_task.py    | 157 ++++++
 fetcher/fetcher/sites/facebook/group_task.py       | 168 +++++++
 fetcher/fetcher/sites/facebook/post_task.py        |  23 +-
 fetcher/fetcher/sites/facebook/urls.py             |  19 +
 fetcher/tests/test_cli_fb.py                       |  34 +-
 fetcher/tests/test_db_fb_groups.py                 | 147 ++++++
 fetcher/tests/test_facebook_discover.py            | 418 +++++++++++++++
 fetcher/tests/test_fb_discover_task.py             | 302 +++++++++++
 fetcher/tests/test_fb_group_task.py                | 270 ++++++++++
 fetcher/tests/test_fb_post_task.py                 |  63 ++-
 platform/server/app/api/tasks.py                   |   5 +
 platform/server/app/db.py                          |  96 ++++
 platform/server/app/runner.py                      |  21 +-
 platform/server/tests/test_batch_tasks.py          | 199 ++++++++
 platform/start.sh                                  |   6 +
 platform/web/src/lib/api.ts                        |   7 +
 platform/web/src/pages/Tasks.tsx                   |   2 +-
 platform/web/src/pages/tasks/TaskFormDialog.tsx    | 190 ++++++-
 platform/web/src/pages/tasks/task-ui.tsx           |  30 ++
 64 files changed, 7752 insertions(+), 34 deletions(-)

## 代码文件 Full diff (-U10)
diff --git a/fetcher/fetcher/atoms/facebook_discover.py b/fetcher/fetcher/atoms/facebook_discover.py
new file mode 100644
index 0000000..5c58ed0
--- /dev/null
+++ b/fetcher/fetcher/atoms/facebook_discover.py
@@ -0,0 +1,202 @@
+# -*- coding: utf-8 -*-
+"""FetchDdgSerp 原子：DDG html 端点裸抓 FB 群帖 SERP + parse/classify 纯函数。
+
+背景（docs/feat_2026-08-09_fb-discovery-group-feed/SPEC.md §8.1）：DDG
+html 端点 GET + 浏览器 UA + gzip 可裸抓、无验证码；Bing 恒 challenge 不可用。
+限流形态为约 2 连查后第 3 次 HTTP 202（anomaly 页），恢复窗口约 4 分钟——
+本原子据此强制查询间节奏 ≥ 60s、202 退避 uniform(180,240)s。spike 实测样本
+存 docs/feat_2026-08-09_fb-discovery-group-feed/spike/ddg_sample_1.html。
+
+契约：
+    params = {
+        "query":      str   必填，查询词（默认矩阵带 site:facebook.com/groups 前缀）
+        "page":       int   可选，页码（1 起，offset=(page-1)*10，缺省 1）
+        "sample_min": float 可选，查询间节奏下限秒（task 从 ctx.config 透传；
+                             原子强制下限 MIN_SAMPLE_FLOOR=60，spike 依据见上）
+        "sample_max": float 可选，查询间节奏上限秒
+        "timeout":    int   可选，HTTP 超时（缺省 30）
+    }
+
+返回：
+    OK        data = {"engine":"ddg","query","page","results":[{"url","title",
+              "kind","group_id","group_url"}...]}——全部有机结果不过滤，非 FB 的
+              kind/group_id/group_url 为 None，分流交给上层任务（SPEC §5.2）
+    EMPTY     200 但 0 条有机结果
+    BLOCKED   HTTP 202（anomaly 限流，先退避 uniform(180,240)）/ 403 / 429
+    NET_ERROR 传输错误 / 5xx / 超时
+    FATAL     参数校验失败（query 缺失/非 str、page < 1）
+    SKIPPED   被停止信号中断（请求前检查或等待期间置位）
+
+依赖说明：只用标准库 urllib（符合包分层不引重依赖的约束）。
+"""
+
+from __future__ import annotations
+
+import gzip
+import html as html_mod
+import random
+import re
+import urllib.error
+import urllib.parse
+import urllib.request
+
+from fetcher.core.types import ActionResult
+
+DDG_HTML = "https://html.duckduckgo.com/html/"
+UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
+      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
+
+# DDG 突发限流 spike 实测（SPEC §8.1）：约 2 连查后第 3 次即 202（anomaly 页），
+# 202 触发到恢复的窗口实测约 4 分钟。查询间节奏下限 60s（~1 查询/分钟，低于
+# 2 连查即封的突发阈值，留安全余量）。
+MIN_SAMPLE_FLOOR = 60.0
+# 202（anomaly 限流）退避：uniform(180, 240) 覆盖实测 ~4 分钟封禁窗口。
+BLOCK_BACKOFF_MIN = 180.0
+BLOCK_BACKOFF_MAX = 240.0
+
+# SERP 有机结果锚点（spike 样本核实）：<a rel="nofollow" class="result__a"
+# href="//duckduckgo.com/l/?uddg=<enc>&amp;rut=...">标题</a>
+RESULT_A_RE = re.compile(
+    r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', re.S)
+UDDG_RE = re.compile(r"[?&]uddg=([^&]+)")
+TAG_RE = re.compile(r"<[^>]+>")
+
+# FB 帖 permalink：groups/<群id>/posts|permalink/<帖id（数字）>
+POST_RE = re.compile(r"facebook\.com/groups/([^/]+)/(?:posts|permalink)/(\d+)")
+# FB 群主页：groups/<群id>
+GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
+
+
+def _http_get(url: str, timeout: float = 30) -> tuple[int, str]:
+    """裸 GET，返回 (status, html)。传输层异常（URLError/socket.timeout）
+    原样上抛；HTTPError（403/429/5xx 等）返回 (code, "") 由原子映射。
+    独立成模块级函数：单测 monkeypatch 即可覆盖全部 HTTP 路径。"""
+    req = urllib.request.Request(url, headers={
+        "User-Agent": UA,
+        "Accept-Language": "zh-CN",
+        "Accept-Encoding": "gzip",
+    })
+    try:
+        with urllib.request.urlopen(req, timeout=timeout) as resp:
+            body = resp.read()
+            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
+                body = gzip.decompress(body)
+            return resp.status, body.decode("utf-8", "replace")
+    except urllib.error.HTTPError as e:
+        # 4xx/5xx 状态码 → (code, "") 由原子映射（对齐 _http_json 模式）；
+        # 其余传输异常不在此 catch，原样上抛。
+        return e.code, ""
+
+
+def parse_serp_results(html: str) -> list[dict]:
+    """抽全部有机结果锚点 → uddg 参数 URL 解码 → 标题净化（去标签 + HTML 实体）。
+
+    返回 [{"url","title"}...]，不过滤（FB 判定在 classify_fb_url）；
+    无锚点/坏 HTML → []。
+    """
+    results = []
+    for href, title in RESULT_A_RE.findall(html):
+        href = html_mod.unescape(href)          # &amp; → &
+        m = UDDG_RE.search(href)
+        if not m:
+            continue                            # 非 redirect 形态，跳过
+        url = urllib.parse.unquote(m.group(1))
+        title = html_mod.unescape(TAG_RE.sub("", title)).strip()
+        results.append({"url": url, "title": title})
+    return results
+
+
+def classify_fb_url(url: str) -> tuple[str, str, str] | None:
+    """分类 FB 群帖 URL：(kind, group_id, group_url) | None。
+
+    kind="post"（帖 permalink）→ group_url 为派生的群主页；
+    kind="group"（群主页）→ group_url 归一化到
+    https://www.facebook.com/groups/{gid}（去尾部斜杠/协议差异）；
+    其余（FB 视频/用户主页/广告页/非 FB）→ None。
+    """
+    m = POST_RE.search(url)
+    if m:
+        gid = m.group(1)
+        return "post", gid, f"https://www.facebook.com/groups/{gid}"
+    m = GROUP_RE.search(url)
+    if m:
+        gid = m.group(1)
+        return "group", gid, f"https://www.facebook.com/groups/{gid}"
+    return None
+
+
+class FetchDdgSerp:
+    """DDG html 端点裸抓 FB 群帖 SERP（查询 → 解析 → 分类）。"""
+
+    name = "fetch_ddg_serp"
+    title = "DDG抓FB群帖SERP"
+
+    def run(self, ctx, params: dict) -> ActionResult:
+        if ctx.stopped():
+            return ActionResult.skipped("被停止信号中断")
+        params = params or {}
+        query = params.get("query")
+        if not isinstance(query, str) or not query.strip():
+            return ActionResult.fatal("缺少必填参数 query（查询词，str）")
+        query = query.strip()
+        raw_page = params.get("page")
+        try:
+            page = int(raw_page) if raw_page is not None else 1
+        except (TypeError, ValueError):
+            return ActionResult.fatal(f"page 参数无效: {raw_page!r}")
+        if page < 1:
+            return ActionResult.fatal(f"page 必须 ≥ 1（收到 {page}）")
+        raw_timeout = params.get("timeout")
+        timeout = int(raw_timeout) if raw_timeout is not None else 30
+        # 查询间节奏：task 从 ctx.config 透传 sample_min/max（缺省 13-20s），
+        # 原子强制下限 MIN_SAMPLE_FLOOR；上限低于地板时同样抬到地板，避免
+        # uniform(a>b) ValueError（对齐 §8.1 设计数字）。用显式 None 判断而非
+        # `or` 缺省（or 会吞掉显式 0）：sample_min=0 由地板抬到 60、
+        # sample_max=0 由 max(sample_max, sample_min) 抬到 60；timeout=0 原样
+        # 传给 _http_get（合法显式值，不转缺省 30）。
+        raw_min = params.get("sample_min")
+        sample_min = (float(raw_min) if raw_min is not None
+                      else MIN_SAMPLE_FLOOR)
+        sample_min = max(sample_min, MIN_SAMPLE_FLOOR)
+        raw_max = params.get("sample_max")
+        sample_max = (float(raw_max) if raw_max is not None
+                      else (sample_min + 20.0))
+        sample_max = max(sample_max, sample_min)
+
+        url = f"{DDG_HTML}?q={urllib.parse.quote(query)}&s={(page - 1) * 10}"
+        ctx.log(f"    ...DDG 查询「{query}」第 {page} 页")
+        try:
+            status, html = _http_get(url, timeout=timeout)
+        except (OSError, TimeoutError, ValueError) as e:
+            return ActionResult.net_error(f"DDG 请求失败: {e}")
+
+        # 202（anomaly 限流）：先退避覆盖实测 ~4 分钟封禁窗口，再返回 BLOCKED。
+        if status == 202:
+            if ctx.wait(random.uniform(BLOCK_BACKOFF_MIN, BLOCK_BACKOFF_MAX)):
+                return ActionResult.skipped("202 退避等待被停止信号中断")
+        # 请求后统一节奏等待（无论 outcome）。
+        if ctx.wait(random.uniform(sample_min, sample_max)):
+            return ActionResult.skipped("节奏等待被停止信号中断")
+
+        if status in (202, 403, 429):
+            return ActionResult.blocked(f"DDG 限流/拒绝（HTTP {status}）")
+        if status != 200:
+            return ActionResult.net_error(f"DDG 返回异常状态 HTTP {status}")
+
+        results = []
+        for r in parse_serp_results(html):
+            cls = classify_fb_url(r["url"])
+            if cls is None:
+                results.append({**r, "kind": None,
+                                "group_id": None, "group_url": None})
+            else:
+                kind, group_id, group_url = cls
+                results.append({"url": r["url"], "title": r["title"],
+                                "kind": kind, "group_id": group_id,
+                                "group_url": group_url})
+        if not results:
+            return ActionResult.empty("DDG 返回 0 条有机结果")
+
+        return ActionResult.success(
+            f"DDG 抓到 {len(results)} 条结果",
+            engine="ddg", query=query, page=page, results=results)
diff --git a/fetcher/fetcher/cli/main.py b/fetcher/fetcher/cli/main.py
index 29a53df..dfeb16e 100644
--- a/fetcher/fetcher/cli/main.py
+++ b/fetcher/fetcher/cli/main.py
@@ -305,20 +305,45 @@ def _build_registry(selected_queues: list[str] | None = None) -> list:
             site=None,
             task=WaCheckTask(),
             topup=wa_check_topup,
             domain_suffix="",
             requires={"local"},
         ))
     else:
         print("[daemon] [!] wa_check 未注册：vendor wa-check/check.js 或"
               " node 不可用（跳过本地队列）")
 
+    # discover_fb（FB discovery：本地队列，无 site、无浏览器，LocalLoop 消费；
+    # 货源=平台批次参数直接入 work_items，无自喂 → topup=None）
+    from fetcher.sites.facebook.discover_task import FbDiscoverTask  # 延迟导入
+    specs.append(QueueSpec(
+        queue="discover_fb",
+        site=None,
+        task=FbDiscoverTask(),
+        topup=None,
+        domain_suffix="",
+        requires={"local"},
+    ))
+
+    # crawl_fb_group（FB 群全量采集：本地队列，无 site、无浏览器，
+    # LocalLoop 消费；货源=平台批次参数（fb_groups pending）直接入
+    # work_items，无自喂 → topup=None）
+    from fetcher.sites.facebook.group_task import FbGroupTask  # 延迟导入
+    specs.append(QueueSpec(
+        queue="crawl_fb_group",
+        site=None,
+        task=FbGroupTask(),
+        topup=None,
+        domain_suffix="",
+        requires={"local"},
+    ))
+
     if selected_queues:
         specs = [s for s in specs if s.queue in selected_queues]
     return specs
 
 
 def reset_daemon_state(db, registry: list) -> tuple[int, int]:
     """daemon 启动崩溃恢复：全量回收 claimed + 逐有 topup 的队列重置
     in_progress（feeder 队列跳过——不产生 in_progress shops）。
 
     返回 (n_claimed_reset, n_in_progress_reset)。
diff --git a/fetcher/fetcher/db.py b/fetcher/fetcher/db.py
index 00bac92..8bf3c58 100644
--- a/fetcher/fetcher/db.py
+++ b/fetcher/fetcher/db.py
@@ -220,20 +220,38 @@ CREATE TABLE IF NOT EXISTS fb_contacts (
     number        TEXT NOT NULL UNIQUE,   -- 中国号裸 11 位；国际号纯数字带原国家码
     bucket        TEXT NOT NULL,          -- declared_wa / cn_uncertain / overseas
     wa_source     TEXT,                   -- 'declared'(自声明) / 'checked'(协议验证) / NULL
     wa_registered INTEGER,                -- 1/0/NULL（三态语义同 contacts）
     wa_checked_at TEXT,
     post_url      TEXT NOT NULL,          -- 来源帖
     group_id      TEXT,
     first_seen_at TEXT NOT NULL
 );
 
+-- FB 群表（发现层 SERP 群主页 + 帖派生群统一落这里，url UNIQUE 幂等）。
+-- 状态机对齐 fb_posts：pending → in_progress → done/failed；已存在行 status
+-- 不被 upsert 改动（保持采集进度）。post_count/has_contact 由 fb_group
+-- on_success 回写；source 缺省 'ddg'（FbDiscoverTask），帖派生传 'fb_post'。
+CREATE TABLE IF NOT EXISTS fb_groups (
+    id              INTEGER PRIMARY KEY AUTOINCREMENT,
+    url             TEXT NOT NULL UNIQUE,     -- 群 URL https://www.facebook.com/groups/{gid}
+    group_id        TEXT,                     -- 群 id（数字或 slug，URL 解析）
+    name            TEXT,                     -- 群名（发现层取自 SERP 标题，溯源用，近似值）
+    source          TEXT NOT NULL DEFAULT 'ddg',  -- 发现来源 ddg / fb_post（帖派生）
+    status          TEXT NOT NULL DEFAULT 'pending', -- pending/in_progress/done/failed
+    post_count      INTEGER,                  -- 已采帖数（fb_group on_success 回写）
+    has_contact     INTEGER,                  -- 是否提到联系方式（fb_group 回写）
+    first_seen_at   TEXT NOT NULL,            -- 北京时间字符串
+    last_crawled_at TEXT
+);
+CREATE INDEX IF NOT EXISTS idx_fb_groups_status ON fb_groups(status, id);
+
 -- daemon 消费者状态心跳表（P4 daemon 可观测）：写方 = fetcher daemon
 -- （claim/finish/release/冷却登记即时 + 10s 心跳 + 退出清空）；
 -- 读方 = 平台 dispatcher API（看板）。stale（updated_at 超 30s）由
 -- 读方判定离线，本表不存“存活”列。
 CREATE TABLE IF NOT EXISTS consumer_status (
     consumer_id TEXT PRIMARY KEY,     -- "w0".."wN" / "local0"..
     kind TEXT NOT NULL,               -- browser / local
     tunnel TEXT, exit_ip TEXT,
     current_queue TEXT, current_item_id INTEGER, current_batch_id INTEGER,
     cooldowns_json TEXT,              -- {"1688": 到期epoch, ...}
@@ -832,20 +850,92 @@ class ShopDB:
 
     def reset_fb_posts_in_progress(self) -> int:
         """fb_posts 的 in_progress 重置回 pending（进程中断残留的认领，
         FbPostTask.prepare 启动时调用——reset_daemon_state 只认
         domain_suffix 非空的 contact 队列，不覆盖 fb_posts）。"""
         cur = self.conn.execute(
             "UPDATE fb_posts SET status='pending' WHERE status='in_progress'")
         self.conn.commit()
         return cur.rowcount
 
+    def mark_fb_group_done(self, url: str, post_count: int,
+                           has_contact: bool) -> None:
+        """群采集完成：status=done + 回写 post_count/has_contact/
+        last_crawled_at（FbGroupTask.on_success 调用）。"""
+        self.conn.execute(
+            "UPDATE fb_groups SET status='done', post_count=?, has_contact=?, "
+            "last_crawled_at=? WHERE url=?",
+            (post_count, 1 if has_contact else 0, _now(), url))
+        self.conn.commit()
+
+    def mark_fb_group_failed(self, url: str) -> None:
+        """群采集失败：status=failed（402/429 额度/限流、网络错误、无帖
+        均置 failed；重跑由平台重开批次）。"""
+        self.conn.execute(
+            "UPDATE fb_groups SET status='failed' WHERE url=?", (url,))
+        self.conn.commit()
+
+    def reset_fb_groups_in_progress(self) -> int:
+        """fb_groups 的 in_progress 重置回 pending（进程中断残留的认领，
+        FbGroupTask.prepare 启动时调用——reset_daemon_state 只认
+        domain_suffix 非空的 contact 队列，不覆盖 fb_groups）。"""
+        cur = self.conn.execute(
+            "UPDATE fb_groups SET status='pending' WHERE status='in_progress'")
+        self.conn.commit()
+        return cur.rowcount
+
+    def save_fb_posts(self, keyword: str, source: str,
+                      posts: list[dict]) -> int:
+        """发现层结果落 fb_posts（INSERT OR IGNORE，url UNIQUE 去重；
+        同帖二次发现不覆盖 first_seen_at/keyword/source）。
+
+        keyword: 溯源查询词；source: 发现来源（'ddg' / 'fb_post'）；posts:
+        [{"url", "group_id", "group_name"}, ...]。返回本次实际新增行数。
+        """
+        now = _now()
+        inserted = 0
+        for p in posts:
+            url = (p.get("url") or "").strip()
+            if not url:
+                continue
+            cur = self.conn.execute(
+                "INSERT OR IGNORE INTO fb_posts (url, group_id, group_name,"
+                " keyword, source, first_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
+                (url, p.get("group_id"), p.get("group_name"),
+                 keyword, source, now))
+            inserted += cur.rowcount
+        self.conn.commit()
+        return inserted
+
+    def upsert_fb_groups(self, groups: list[dict]) -> int:
+        """发现/帖派生的群条目落 fb_groups（INSERT OR IGNORE，url UNIQUE
+        去重；已存在行不动 status/name，保持采集进度）。
+
+        groups: [{"url", "group_id", "name", "source"?}, ...]，source 仅在
+        key 不存在或 None 时缺省 'ddg'（FbDiscoverTask 不带 source 键；
+        FbPostTask 传 'fb_post'）。返回本次实际新增行数。
+        """
+        now = _now()
+        inserted = 0
+        for g in groups:
+            url = (g.get("url") or "").strip()
+            if not url:
+                continue
+            source = g.get("source") if g.get("source") is not None else "ddg"
+            cur = self.conn.execute(
+                "INSERT OR IGNORE INTO fb_groups (url, group_id, name,"
+                " source, first_seen_at) VALUES (?, ?, ?, ?, ?)",
+                (url, g.get("group_id"), g.get("name"), source, now))
+            inserted += cur.rowcount
+        self.conn.commit()
+        return inserted
+
     # ---------- category_progress ----------
     def get_category_progress(self, keyword: str) -> dict | None:
         """取类目分页进度（无记录返回 None）。"""
         row = self.conn.execute(
             "SELECT * FROM category_progress WHERE keyword=?",
             (keyword,)).fetchone()
         return dict(row) if row else None
 
     def advance_category_page(self, keyword: str, name: str = None,
                               shops_found: int = 0) -> int:
diff --git a/fetcher/fetcher/sites/facebook/discover_task.py b/fetcher/fetcher/sites/facebook/discover_task.py
new file mode 100644
index 0000000..93704ae
--- /dev/null
+++ b/fetcher/fetcher/sites/facebook/discover_task.py
@@ -0,0 +1,157 @@
+# -*- coding: utf-8 -*-
+"""FbDiscoverTask：discover_fb 队列的 local 消费者（SPEC §5.2）。
+
+消费 work_items(discover_fb) 的查询任务 → 调 FetchDdgSerp 原子（DDG 裸抓
+FB 群帖 SERP）→ 按 kind 分流落库：帖 permalink → fb_posts（save_fb_posts，
+keyword/source 溯源）；FB 群 URL（群主页 + 帖派生）→ fb_groups
+（upsert_fb_groups，name 去 " | Facebook"/" - Facebook" 后缀近似溯源）；
+kind=None 的非 FB 条目跳过。
+
+local 消费者（LocalLoop 驱动，无浏览器循环）：OK→on_success 落库；
+BLOCKED/NET_ERROR/EMPTY→on_giveup（不落库，仅日志短语 + stats failed）。
+节奏取 ctx.config.sample_min/max 透传原子（原子抬到 60s 地板）。
+"""
+
+from __future__ import annotations
+
+from fetcher.control.task import Task
+from fetcher.core.types import ActionResult
+
+QUEUE = "discover_fb"
+
+# SERP 标题站点后缀（近似溯源用；strip 后 endswith 匹配，去一次）
+_TITLE_SUFFIXES = (" | Facebook", " - Facebook")
+
+
+def _clean_title(title: str) -> str:
+    """SERP 标题净化：去 " | Facebook" / " - Facebook" 后缀（无则原样）。"""
+    t = (title or "").strip()
+    for suffix in _TITLE_SUFFIXES:
+        if t.endswith(suffix):
+            return t[:-len(suffix)].strip()
+    return t
+
+
+class FbDiscoverTask(Task):
+    """discover_fb 队列执行器：DDG 查询 → 分流落库（SPEC §5.2）。"""
+
+    name = "fb_discover"
+    unit = "查询"
+    batch_unit = ""
+
+    QUEUE = QUEUE
+
+    def __init__(self):
+        self._atom = None
+
+    def _make_atom(self):
+        from fetcher.atoms.facebook_discover import FetchDdgSerp  # 延迟导入
+        return FetchDdgSerp()
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """打印队列待处理数（discover 无源表状态机，无需崩溃恢复）。"""
+        from fetcher.db import ShopDB  # 延迟导入
+        db = ShopDB(config.resolved_db_path())
+        pending = db.conn.execute(
+            "SELECT COUNT(*) FROM work_items WHERE queue=? "
+            "AND status='pending'", (QUEUE,)).fetchone()[0]
+        print(f"[fb_discover] 队列待处理: {pending}")
+        db.close()
+        return True
+
+    def summary(self, all_stats: dict, db_path=None) -> str:
+        ok = sum(s.get("ok", 0) for s in all_stats.values())
+        empty = sum(s.get("empty", 0) for s in all_stats.values())
+        failed = sum(s.get("failed", 0) for s in all_stats.values())
+        return (f"fb_discover: 成功 {ok}，空 {empty}，失败 {failed}")
+
+    def make_stats(self) -> dict:
+        return {"ok": 0, "empty": 0, "failed": 0}
+
+    # ---- worker 循环 ----
+
+    def acquire_item(self, ctx):
+        """从 discover_fb 队列认领（LocalLoop 经 QueueRouter 路由时不用本
+        方法；保留实现供直接调用/测试）。"""
+        from fetcher.control.queue_router import consumer_id_for
+        item = ctx.store.db.claim_next_eligible([self.QUEUE],
+                                                consumer_id_for(ctx))
+        if item is None:
+            return None
+        payload = dict(item["payload"])
+        payload["id"] = item["id"]
+        return payload
+
+    def label(self, item) -> str:
+        return f"{item['query']} 第{item['page']}页"
+
+    def fetch(self, ctx, item) -> ActionResult:
+        """调 FetchDdgSerp 原子（params 透传 query/page/sample_min/max）。"""
+        atom = self._atom or self._make_atom()
+        return atom.run(ctx, {
+            "query": item["query"],
+            "page": int(item.get("page") or 1),
+            "sample_min": float(ctx.config.sample_min),
+            "sample_max": float(ctx.config.sample_max),
+        })
+
+    def on_success(self, ctx, item, result: ActionResult) -> int:
+        """results 分流落库：帖→fb_posts（含派生群→fb_groups）；群→fb_groups；
+        kind=None 跳过。返回新增帖数（计入批次配额）。"""
+        results = (result.data or {}).get("results") or []
+        if not results:
+            stats = self.wctx_stats(ctx)
+            stats["empty"] += 1
+            ctx.set_status(state="○ 无结果", n=sum(stats.values()),
+                           empty=stats["empty"])
+            return 0
+        posts: list[dict] = []
+        groups: list[dict] = []
+        for r in results:
+            kind = r.get("kind")
+            url = r.get("url") or ""
+            title = _clean_title(r.get("title"))
+            group_id = r.get("group_id")
+            if kind == "post":
+                posts.append({"url": url, "group_id": group_id,
+                              "group_name": title})
+                gurl = r.get("group_url") or ""
+                if gurl:
+                    groups.append({"url": gurl, "group_id": group_id,
+                                   "name": title})
+            elif kind == "group":
+                gurl = r.get("group_url") or url
+                groups.append({"url": gurl, "group_id": group_id,
+                               "name": title})
+            # kind=None 的非 FB 条目跳过
+        db = ctx.store.db
+        n_posts = db.save_fb_posts(keyword=item["query"], source="ddg",
+                                   posts=posts) if posts else 0
+        if groups:
+            db.upsert_fb_groups(groups)
+        stats = self.wctx_stats(ctx)
+        stats["ok"] += 1
+        state = f"✓ 新增 {n_posts} 帖（群 {len(groups)}）"
+        ctx.set_status(state=state, n=sum(stats.values()),
+                       ok=stats["ok"], empty=stats["empty"],
+                       failed=stats["failed"])
+        return n_posts
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        """BLOCKED/NET_ERROR/EMPTY：不落库，仅日志短语 + failed 计数。"""
+        ctx.log(f"[fb_discover] 放弃：{reason}")
+        stats = self.wctx_stats(ctx)
+        stats["failed"] += 1
+        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
+        return "标记 failed 跳过"
+
+    def empty_message(self) -> str:
+        return "discover_fb 队列空"
+
+    # ---- 内部 ----
+
+    @staticmethod
+    def wctx_stats(ctx) -> dict:
+        return ctx.state["task"]["stats"]
diff --git a/fetcher/fetcher/sites/facebook/group_task.py b/fetcher/fetcher/sites/facebook/group_task.py
new file mode 100644
index 0000000..75fd889
--- /dev/null
+++ b/fetcher/fetcher/sites/facebook/group_task.py
@@ -0,0 +1,168 @@
+# -*- coding: utf-8 -*-
+"""Facebook 群 feed 全量采集任务（daemon crawl_fb_group 队列的 local 消费者）。
+
+任务内容：消费 work_items(crawl_fb_group) 的群 URL → 调 FetchFbGroupPosts
+原子（Bright Data / Apify 第三方 API 拉群帖）→ 逐帖号码落 fb_contacts
+（正文全文已在手，直接落库，无需再走 crawl_fb_post）→ fb_groups 状态机
+done/failed 回写（post_count/has_contact/last_crawled_at）。
+
+FATAL 处置：缺 API key / 未知 provider → 原子返回 FATAL，Task 框架对
+FATAL 直接停止（on_giveup 不会被调），本 Task 不额外处理（SPEC §5.3）。
+
+分层：原子只做「拉 + 提取」，本 Task 做编排与落库（对齐 FbPostTask 模式）。
+"""
+
+from __future__ import annotations
+
+from fetcher.control.task import Task
+from fetcher.core.types import ActionResult
+from fetcher.sites.facebook.urls import group_id_from_url
+
+QUEUE = "crawl_fb_group"
+
+
+class FbGroupTask(Task):
+    """FB 群全量采集任务：认领 crawl_fb_group 队列的群工作项。"""
+
+    name = "fb_group"
+    unit = "群"
+    batch_unit = ""
+
+    QUEUE = QUEUE
+
+    def __init__(self):
+        self._atom = None
+
+    def _make_atom(self):
+        from fetcher.atoms.facebook_group import FetchFbGroupPosts  # 延迟导入
+        return FetchFbGroupPosts()
+
+    # ---- main 阶段 ----
+
+    def prepare(self, config) -> bool:
+        """崩溃恢复：fb_groups 的 in_progress 重置回 pending（进程中断残留）。
+
+        注意：reset_daemon_state 只认 domain_suffix 非空的 contact 队列，
+        不覆盖 fb_groups；重置放本 Task.prepare（router.prepare 每队列都会调），
+        与 FbPostTask.prepare 语义一致（SPEC §5.3）。
+        """
+        from fetcher.db import ShopDB  # 延迟导入
+        db = ShopDB(config.resolved_db_path())
+        n = db.reset_fb_groups_in_progress()
+        if n:
+            print(f"[0] 已把 {n} 个中断残留的 in_progress 群重置回 pending")
+        pending = db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups WHERE status='pending'"
+        ).fetchone()[0]
+        print(f"[1] fb_groups 待采集 {pending} 个（daemon 由 work_items 队列供货）")
+        db.close()
+        return True
+
+    def summary(self, all_stats: dict, db_path=None) -> str:
+        from fetcher.db import ShopDB  # 延迟导入
+        ok = sum(s.get("ok", 0) for s in all_stats.values())
+        empty = sum(s.get("empty", 0) for s in all_stats.values())
+        failed = sum(s.get("failed", 0) for s in all_stats.values())
+        db = ShopDB(db_path)
+        n_contacts = db.conn.execute(
+            "SELECT COUNT(*) FROM fb_contacts").fetchone()[0]
+        n_groups = db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
+        db.close()
+        return (f"本次完成: 有联系方式 {ok}, 无联系方式 {empty}, 失败 {failed}"
+                f"\n    fb_groups {n_groups} 行，fb_contacts {n_contacts} 个号码")
+
+    # ---- 状态板 ----
+
+    def compose(self, wid: int, f: dict) -> str:
+        return (f"[w{wid}] 群 {f.get('n', 0)}（✓{f.get('ok', 0)} "
+                f"○{f.get('empty', 0)} ✗{f.get('failed', 0)}）| "
+                f"{f.get('group', '-')} | {f.get('state', '初始化')}")
+
+    def make_stats(self) -> dict:
+        return {"ok": 0, "empty": 0, "failed": 0}
+
+    def rest_counter(self, stats: dict) -> int:
+        return sum(stats.values())
+
+    # ---- worker 循环 ----
+
+    def acquire_item(self, ctx):
+        """从 crawl_fb_group 队列认领（LocalLoop/直调场景用；daemon 经
+        QueueRouter 认领时不用本方法，保留实现供直接调用/测试）。"""
+        from fetcher.control.queue_router import consumer_id_for
+        item = ctx.store.db.claim_next_eligible([self.QUEUE],
+                                                consumer_id_for(ctx))
+        if item is None:
+            return None
+        payload = dict(item["payload"])
+        payload["id"] = item["id"]
+        return payload
+
+    def label(self, item) -> str:
+        return f"{item['url']}（{item.get('provider')}，≤{item.get('limit')}帖）"
+
+    def fetch(self, ctx, item) -> ActionResult:
+        """调 FetchFbGroupPosts 原子（params 透传 url/provider/limit）。"""
+        atom = self._atom or self._make_atom()
+        return atom.run(ctx, {
+            "url": item["url"],
+            "provider": item.get("provider"),
+            "limit": int(item.get("limit") or 10),
+        })
+
+    def on_success(self, ctx, item, result: ActionResult) -> int:
+        """逐帖号码落 fb_contacts + 群置 done 回写三字段 + stats。"""
+        data = result.data or {}
+        posts = data.get("posts") or []
+        group_id = group_id_from_url(item.get("url") or "")
+        db = ctx.store.db
+        # 逐帖落号：正文全文已在手，直接落库（无需再走 crawl_fb_post）
+        n_new = 0
+        for post in posts:
+            post_url = (post or {}).get("url") or ""
+            if not post_url:
+                continue
+            n_new += db.save_fb_contacts(post_url, group_id,
+                                         (post or {}).get("phones") or [])
+        # 逐帖口径：任一帖有号码 → has_contact / ok（不依赖原子顶级聚合字段）
+        phones = [ph for post in posts
+                  for ph in ((post or {}).get("phones") or [])]
+        has_contact = bool(phones)
+        db.mark_fb_group_done(item["url"], len(posts), has_contact)
+        stats = self.wctx_stats(ctx)
+        if phones:
+            stats["ok"] += 1
+            state = f"✓ {len(phones)} 个号码（新增 {n_new}）"
+        else:
+            stats["empty"] += 1
+            state = "○ 无联系方式"
+        ctx.set_status(state=state, n=sum(stats.values()),
+                       ok=stats["ok"], empty=stats["empty"],
+                       failed=stats["failed"])
+        return len(posts)  # 返回帖数（计入批次配额）
+
+    def on_giveup(self, ctx, item, reason: str, kind: str) -> str:
+        """402/429 额度/限流、网络错误、无帖均置 failed（重跑由平台重开批次）。"""
+        ctx.store.db.mark_fb_group_failed(item["url"])
+        stats = self.wctx_stats(ctx)
+        stats["failed"] += 1
+        ctx.set_status(n=sum(stats.values()), failed=stats["failed"])
+        return "标记 failed 跳过"
+
+    def on_abort(self, ctx, item) -> str:
+        return (f"群 {item['url']} 留在 in_progress，"
+                f"下次运行自动放回 pending")
+
+    def giveup_cost(self, item) -> int:
+        # 群处理完毕（含标记 failed），计入批次配额
+        return 1
+
+    def empty_message(self) -> str:
+        return "没有待采集的群了"
+
+    # ---- 内部 ----
+
+    @staticmethod
+    def wctx_stats(ctx) -> dict:
+        return ctx.state["task"]["stats"]
diff --git a/fetcher/fetcher/sites/facebook/post_task.py b/fetcher/fetcher/sites/facebook/post_task.py
index ae31395..2792f68 100644
--- a/fetcher/fetcher/sites/facebook/post_task.py
+++ b/fetcher/fetcher/sites/facebook/post_task.py
@@ -7,36 +7,26 @@ FetchFbPost 原子（匿名渲染抓 permalink + parse_post 四桶提取）→
 状态机 done/failed + has_contact 回写；微信/TG/邀请链接侧车随
 work_items.result_json 留存（观测用）。
 
 分层：原子只做「抓 + 提取」，本 Task 做编排与落库（SPEC §5.1 裁定：
 fetch 调 FetchFbPost 原子，不内联 page 操作）。匿名白板会话无需
 软着陆（cold_start 空实现）；warmup homepage 偏差接受（SPEC §7.3）。
 """
 
 from __future__ import annotations
 
-import re
-
 from fetcher.control.task import Task
 from fetcher.core.types import ActionResult
+from fetcher.sites.facebook.urls import group_id_from_url
 
 QUEUE = "crawl_fb_post"
 
-# 从群 URL 解析 group_id：facebook.com/groups/{gid}（payload.domain 是群 URL）
-_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
-
-
-def _group_id_from_url(url: str) -> str | None:
-    """群 URL → 群 id；无/非法返回 None。"""
-    m = _GROUP_RE.search(url or "")
-    return m.group(1) if m else None
-
 
 class FbPostTask(Task):
     """FB 群帖采集任务：认领 crawl_fb_post 队列的帖子工作项。"""
 
     name = "post"
     unit = "帖"
     batch_unit = ""
 
     # 匿名 permalink 抓取：参照 1688 contact 的保守预算
     ip_request_budget = 60
@@ -129,25 +119,34 @@ class FbPostTask(Task):
         """有效帖页判据：DOM 正文非空且长度 ≥ 100（FB 帖页含遮罩文案，
         纯遮罩约 200 字符，有效帖页远超此值——阈值按 SPEC §5.1）。"""
         data = result.data or {}
         text = data.get("text") or ""
         return bool(text.strip()) and len(text) >= 100
 
     def on_success(self, ctx, item, result: ActionResult) -> int:
         """号码落 fb_contacts + fb_posts 置 done + 侧车副产物留 result_json。"""
         data = result.data or {}
         phones = data.get("phones") or []
-        group_id = _group_id_from_url(item.get("domain") or "")
+        group_id = group_id_from_url(item.get("domain") or "")
         db = ctx.store.db
         n_new = db.save_fb_contacts(item["url"], group_id, phones)
         has_contact = bool(data.get("has_contact"))
         db.mark_fb_post_done(item["url"], has_contact)
+        # 每抓到一帖 = 发现一个群（种子路径②，SPEC §5.5）：INSERT OR IGNORE
+        # 幂等，不触碰既有群状态机；source 显式传 fb_post（缺省 ddg）
+        if group_id:
+            db.upsert_fb_groups([{
+                "url": f"https://www.facebook.com/groups/{group_id}",
+                "group_id": group_id,
+                "name": item.get("name") or "",
+                "source": "fb_post",
+            }])
         # 侧车副产物（微信/TG/邀请链接）：非空才设，QueueRouter._finish
         # 经 ctx.state["result_json"] 落 work_items.result_json（SPEC §8）
         sidecar = {}
         for key in ("wechat_ids", "tg_handles", "wa_group_invites"):
             vals = data.get(key) or []
             if vals:
                 sidecar[key] = vals
         if sidecar:
             ctx.state["result_json"] = sidecar
         stats = self.wctx_stats(ctx)
diff --git a/fetcher/fetcher/sites/facebook/urls.py b/fetcher/fetcher/sites/facebook/urls.py
new file mode 100644
index 0000000..915eda4
--- /dev/null
+++ b/fetcher/fetcher/sites/facebook/urls.py
@@ -0,0 +1,19 @@
+# -*- coding: utf-8 -*-
+"""Facebook URL 工具（group_task / post_task 共享）：群 URL → group_id 解析。
+
+单一来源：group_task.py（payload.url 是群 URL）与 post_task.py
+（payload.domain 是群 URL）都从这里取，改正则只需改一处。
+"""
+
+from __future__ import annotations
+
+import re
+
+# 从群 URL 解析 group_id：facebook.com/groups/{gid}
+_GROUP_RE = re.compile(r"facebook\.com/groups/([^/]+)")
+
+
+def group_id_from_url(url: str) -> str | None:
+    """群 URL → 群 id；无/非法返回 None。"""
+    m = _GROUP_RE.search(url or "")
+    return m.group(1) if m else None
diff --git a/fetcher/tests/test_cli_fb.py b/fetcher/tests/test_cli_fb.py
index 8df159c..379a282 100644
--- a/fetcher/tests/test_cli_fb.py
+++ b/fetcher/tests/test_cli_fb.py
@@ -1,25 +1,29 @@
 # -*- coding: utf-8 -*-
-"""Step 1.4: crawl_fb_post 队列注册测试。
+"""Step 1.4: crawl_fb_post / discover_fb 队列注册测试。
 
 覆盖：_build_registry 注册 crawl_fb_post QueueSpec（site/domain_suffix/
 requires/task 类型）、topup lambda 从 fb_posts 补货、--queues 动态校验
 包含 fb 队列、daemon prepare 经 FbPostTask.prepare 重置 fb_posts
-in_progress（reset_daemon_state 不覆盖 fb_posts 的缺口补位）。
+in_progress（reset_daemon_state 不覆盖 fb_posts 的缺口补位）；
+FB discovery 的 discover_fb 队列注册（site=None/topup=None/
+requires={"local"}，FbDiscoverTask 实例）。
 """
 
 import json
 import tempfile
 import unittest
 from pathlib import Path
 
 from fetcher import ShopDB
+from fetcher.sites.facebook.discover_task import FbDiscoverTask
+from fetcher.sites.facebook.group_task import FbGroupTask
 from fetcher.sites.facebook.post_task import FbPostTask
 
 POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
             "1437583168191347/")
 
 
 def _seed_posts(db, n=3):
     for i in range(n):
         db.conn.execute(
             "INSERT INTO fb_posts (url, group_id, group_name, keyword,"
@@ -46,20 +50,46 @@ class FbQueueRegistrationTest(unittest.TestCase):
     def test_crawl_fb_post_registered(self):
         reg = self._registry()
         self.assertIn("crawl_fb_post", reg)
         spec = reg["crawl_fb_post"]
         self.assertEqual(spec.site, "facebook")
         self.assertEqual(spec.domain_suffix, "")
         self.assertEqual(spec.requires, {"channel", "browser"})
         self.assertIsInstance(spec.task, FbPostTask)
         self.assertIsNotNone(spec.topup)
 
+    def test_discover_fb_registered(self):
+        """discover_fb：local 消费者注册（site=None、topup=None、
+        requires={"local"}），task 是 FbDiscoverTask 实例。"""
+        reg = self._registry()
+        self.assertIn("discover_fb", reg)
+        spec = reg["discover_fb"]
+        self.assertEqual(spec.queue, "discover_fb")
+        self.assertIsNone(spec.site)
+        self.assertEqual(spec.domain_suffix, "")
+        self.assertEqual(spec.requires, {"local"})
+        self.assertIsInstance(spec.task, FbDiscoverTask)
+        self.assertIsNone(spec.topup)
+
+    def test_crawl_fb_group_registered(self):
+        """crawl_fb_group：local 消费者注册（site=None、topup=None、
+        requires={"local"}），task 是 FbGroupTask 实例。"""
+        reg = self._registry()
+        self.assertIn("crawl_fb_group", reg)
+        spec = reg["crawl_fb_group"]
+        self.assertEqual(spec.queue, "crawl_fb_group")
+        self.assertIsNone(spec.site)
+        self.assertEqual(spec.domain_suffix, "")
+        self.assertEqual(spec.requires, {"local"})
+        self.assertIsInstance(spec.task, FbGroupTask)
+        self.assertIsNone(spec.topup)
+
     def test_fb_topup_feeds_work_items(self):
         """topup lambda：pending fb_posts → work_items，payload 键 url/domain/name。"""
         _seed_posts(self.db, 3)
         spec = self._registry()["crawl_fb_post"]
         n = spec.topup(self.db, 10)
         self.assertEqual(n, 3)
         items = self.db.conn.execute(
             "SELECT * FROM work_items WHERE queue='crawl_fb_post'"
         ).fetchall()
         self.assertEqual(len(items), 3)
diff --git a/fetcher/tests/test_db_fb_groups.py b/fetcher/tests/test_db_fb_groups.py
new file mode 100644
index 0000000..cf11dbe
--- /dev/null
+++ b/fetcher/tests/test_db_fb_groups.py
@@ -0,0 +1,147 @@
+# -*- coding: utf-8 -*-
+"""Step 1.1: fb_groups 建表 + save_fb_posts / upsert_fb_groups 数据面测试。
+
+覆盖：建表幂等（fb_groups 表 + idx_fb_groups_status 索引）、save_fb_posts
+URL 去重与 keyword/source/group_id/group_name 溯源落库、upsert_fb_groups URL
+去重与不动既有行 status、source 缺省 ddg / 显式 source 落库。
+"""
+
+import tempfile
+import unittest
+from pathlib import Path
+
+from fetcher import ShopDB
+
+GROUP_URL_1 = "https://www.facebook.com/groups/185879310028412"
+GROUP_URL_2 = "https://www.facebook.com/groups/1305282597018167"
+POST_URL_1 = "https://www.facebook.com/groups/185879310028412/posts/1437583168191347/"
+POST_URL_2 = "https://www.facebook.com/groups/1305282597018167/posts/1796051251274630/"
+
+
+class FbGroupsDataTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    # ---- 建表幂等 ----
+
+    def test_tables_created_and_idempotent(self):
+        """重复初始化不报错，fb_groups 表与 (status, id) 索引存在。"""
+        ShopDB(Path(self._tmp.name) / "t.db")  # 二次初始化
+        tables = {r[0] for r in self.db.conn.execute(
+            "SELECT name FROM sqlite_master WHERE type='table'")}
+        self.assertIn("fb_groups", tables)
+        idx = {r[0] for r in self.db.conn.execute(
+            "SELECT name FROM sqlite_master WHERE type='index'")}
+        self.assertIn("idx_fb_groups_status", idx)
+        # schema 契约固化：save_fb_posts 依赖 fb_posts.status 默认 pending，
+        # 防未来改 DEFAULT 静默破坏（status 列 dflt_value 须为 'pending'）。
+        cols = {r["name"]: r for r in self.db.conn.execute(
+            "PRAGMA table_info('fb_posts')").fetchall()}
+        self.assertEqual(cols["status"]["dflt_value"], "'pending'")
+
+    # ---- save_fb_posts ----
+
+    def test_save_posts_traceability_and_count(self):
+        posts = [
+            {"url": POST_URL_1, "group_id": "185879310028412",
+             "group_name": "Shenzhen Expats 2026"},
+            {"url": POST_URL_2, "group_id": "1305282597018167",
+             "group_name": "Group B"},
+        ]
+        n = self.db.save_fb_posts("外贸 whatsapp", "ddg", posts)
+        self.assertEqual(n, 2)
+        rows = {r["url"]: r for r in self.db.conn.execute(
+            "SELECT * FROM fb_posts").fetchall()}
+        self.assertEqual(rows[POST_URL_1]["keyword"], "外贸 whatsapp")
+        self.assertEqual(rows[POST_URL_1]["source"], "ddg")
+        self.assertEqual(rows[POST_URL_1]["group_id"], "185879310028412")
+        self.assertEqual(rows[POST_URL_1]["group_name"], "Shenzhen Expats 2026")
+        self.assertEqual(rows[POST_URL_1]["status"], "pending")
+        self.assertIsNotNone(rows[POST_URL_1]["first_seen_at"])
+
+    def test_save_posts_explicit_source(self):
+        posts = [{"url": POST_URL_1, "group_id": "g1", "group_name": "G1"}]
+        n = self.db.save_fb_posts("kw", "fb_post", posts)
+        self.assertEqual(n, 1)
+        row = self.db.conn.execute(
+            "SELECT source FROM fb_posts WHERE url=?", (POST_URL_1,)).fetchone()
+        self.assertEqual(row[0], "fb_post")
+
+    def test_save_posts_dedup_same_url_returns_zero(self):
+        posts = [{"url": POST_URL_1, "group_id": "g1", "group_name": "G1"}]
+        n1 = self.db.save_fb_posts("kw", "ddg", posts)
+        n2 = self.db.save_fb_posts("kw2", "ddg", posts)  # 同 url 二次插入
+        self.assertEqual(n1, 1)
+        self.assertEqual(n2, 0)  # url UNIQUE IGNORE
+        rows = self.db.conn.execute(
+            "SELECT * FROM fb_posts WHERE url=?", (POST_URL_1,)).fetchall()
+        self.assertEqual(len(rows), 1)
+        self.assertEqual(rows[0]["keyword"], "kw")  # 首见不覆盖
+
+    # ---- upsert_fb_groups ----
+
+    def test_upsert_groups_default_source_and_count(self):
+        groups = [
+            {"url": GROUP_URL_1, "group_id": "185879310028412",
+             "name": "Shenzhen Expats 2026"},
+            {"url": GROUP_URL_2, "group_id": "1305282597018167",
+             "name": "Group B"},
+        ]
+        n = self.db.upsert_fb_groups(groups)
+        self.assertEqual(n, 2)
+        rows = {r["url"]: r for r in self.db.conn.execute(
+            "SELECT * FROM fb_groups").fetchall()}
+        self.assertEqual(rows[GROUP_URL_1]["source"], "ddg")  # 缺省 ddg
+        self.assertEqual(rows[GROUP_URL_1]["status"], "pending")
+        self.assertEqual(rows[GROUP_URL_1]["name"], "Shenzhen Expats 2026")
+        self.assertEqual(rows[GROUP_URL_1]["group_id"], "185879310028412")
+        self.assertIsNotNone(rows[GROUP_URL_1]["first_seen_at"])
+
+    def test_upsert_groups_explicit_source(self):
+        groups = [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1",
+                   "source": "fb_post"}]
+        n = self.db.upsert_fb_groups(groups)
+        self.assertEqual(n, 1)
+        row = self.db.conn.execute(
+            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchone()
+        self.assertEqual(row["source"], "fb_post")
+
+    def test_upsert_groups_explicit_empty_source_kept(self):
+        """协调者裁定：source 仅在 key 不存在或 None 时缺省 'ddg'；
+        显式传空字符串 '' 是合法显式值，必须原样落库不被吞成 'ddg'。"""
+        groups = [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1",
+                   "source": ""}]
+        n = self.db.upsert_fb_groups(groups)
+        self.assertEqual(n, 1)
+        row = self.db.conn.execute(
+            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchone()
+        self.assertEqual(row["source"], "")
+
+    def test_upsert_groups_dedup_keeps_status_and_name(self):
+        """先落 pending 行并置 in_progress（模拟采集进行中），再同 url
+        不同 name/source 的 upsert → 0 行且 status/name 保持原值。"""
+        self.db.upsert_fb_groups(
+            [{"url": GROUP_URL_1, "group_id": "g1", "name": "G1"}])
+        self.db.conn.execute(
+            "UPDATE fb_groups SET status='in_progress' WHERE url=?",
+            (GROUP_URL_1,))
+        self.db.conn.commit()
+        n = self.db.upsert_fb_groups(
+            [{"url": GROUP_URL_1, "group_id": "g1",
+              "name": "改名后的群", "source": "fb_post"}])
+        self.assertEqual(n, 0)  # 同 url IGNORE
+        rows = self.db.conn.execute(
+            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL_1,)).fetchall()
+        self.assertEqual(len(rows), 1)
+        self.assertEqual(rows[0]["status"], "in_progress")  # 不动 status
+        self.assertEqual(rows[0]["name"], "G1")  # 不覆盖 name
+        self.assertEqual(rows[0]["source"], "ddg")  # 二次 upsert 带 fb_post 也不覆盖 source
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_facebook_discover.py b/fetcher/tests/test_facebook_discover.py
new file mode 100644
index 0000000..bb60706
--- /dev/null
+++ b/fetcher/tests/test_facebook_discover.py
@@ -0,0 +1,418 @@
+# -*- coding: utf-8 -*-
+"""FetchDdgSerp 原子 + parse/classify 纯函数单测。
+
+parse/classify 用真实 spike 样本（docs/feat_2026-08-09_fb-discovery-group-feed/
+spike/ddg_sample_1.html，2026-08-09 实测 10 条有机结果全为 FB 群主页）与真实
+URL；HTTP 层全部 mock（_http_get / urlopen），不依赖真实网络。
+"""
+
+from __future__ import annotations
+
+import gzip
+import socket
+import threading
+import unittest
+import urllib.error
+import urllib.parse
+from pathlib import Path
+from unittest import mock
+
+from fetcher.atoms import facebook_discover as fd
+from fetcher.atoms.facebook_discover import (
+    FetchDdgSerp,
+    classify_fb_url,
+    parse_serp_results,
+)
+from fetcher.core.types import Outcome
+
+# 真实 spike 样本：<root>/docs/feat_2026-08-09_fb-discovery-group-feed/spike/
+SPIKE_HTML = (Path(__file__).resolve().parents[2]
+              / "docs" / "feat_2026-08-09_fb-discovery-group-feed"
+              / "spike" / "ddg_sample_1.html")
+
+SAMPLE_QUERY = "site:facebook.com/groups 跨境电商 whatsapp"
+
+
+class _Ctx:
+    """最小 WorkerContext 替身：记录 wait 次数/时长，可模拟停止信号。"""
+
+    def __init__(self, stopped: bool = False):
+        self.stop = threading.Event()
+        if stopped:
+            self.stop.set()
+        self.waits: list[float] = []
+        self.logs: list[str] = []
+
+    def stopped(self) -> bool:
+        return self.stop.is_set()
+
+    def wait(self, seconds: float) -> bool:
+        self.waits.append(seconds)
+        return self.stop.is_set()
+
+    def log(self, msg: str) -> None:
+        self.logs.append(msg)
+
+
+class _StopAfterRequest(_Ctx):
+    """请求发出后才置位 stop：验证节奏 wait 被中断 → SKIPPED。"""
+
+    def stopped(self) -> bool:
+        return False   # 请求前不停止
+
+    def wait(self, seconds: float) -> bool:
+        self.waits.append(seconds)
+        return True    # 等待期间 stop 置位
+
+
+def _run(params, ctx=None):
+    return FetchDdgSerp().run(ctx or _Ctx(), params)
+
+
+def _sample_html() -> str:
+    return SPIKE_HTML.read_text(encoding="utf-8")
+
+
+class TestParseSerpResults(unittest.TestCase):
+    def test_sample_structure(self):
+        """真实样本：10 条结果，全部解码为 https FB 群 URL，键只有 url/title。"""
+        results = parse_serp_results(_sample_html())
+        self.assertEqual(len(results), 10)
+        for r in results:
+            self.assertEqual(set(r), {"url", "title"})
+            self.assertTrue(
+                r["url"].startswith("https://www.facebook.com/groups/"))
+            self.assertNotIn("%", r["url"])            # uddg 已 URL 解码
+            self.assertNotIn("&amp;", r["url"])        # HTML 实体已还原
+            self.assertTrue(r["title"].strip())
+
+    def test_first_result_matches_sample(self):
+        results = parse_serp_results(_sample_html())
+        self.assertEqual(
+            results[0]["url"],
+            "https://www.facebook.com/groups/crossborderelectroniccommerce/")
+        self.assertEqual(results[0]["title"], "跨境电商交流群 | Facebook")
+
+    def test_title_html_entities_unescaped(self):
+        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+                '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2F&amp;rut=x">'
+                'A &amp; B &lt;测试&gt;</a>')
+        results = parse_serp_results(html)
+        self.assertEqual(results[0]["title"], "A & B <测试>")
+
+    def test_title_tags_stripped(self):
+        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+                '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2F&amp;rut=x">'
+                '<b>跨境</b> 交流群</a>')
+        results = parse_serp_results(html)
+        self.assertEqual(results[0]["title"], "跨境 交流群")
+
+    def test_no_results_returns_empty(self):
+        self.assertEqual(parse_serp_results("<html><body>无结果</body></html>"), [])
+        self.assertEqual(parse_serp_results(""), [])
+
+
+class TestClassifyFbUrl(unittest.TestCase):
+    def test_post_permalink(self):
+        url = ("https://www.facebook.com/groups/185879310028412/"
+               "posts/1437583168191347/")
+        self.assertEqual(
+            classify_fb_url(url),
+            ("post", "185879310028412",
+             "https://www.facebook.com/groups/185879310028412"))
+
+    def test_post_permalink_variant(self):
+        """permalink 变体 + slug 群 id。"""
+        url = ("https://www.facebook.com/groups/crossborderelectroniccommerce/"
+               "permalink/123456789/")
+        self.assertEqual(
+            classify_fb_url(url),
+            ("post", "crossborderelectroniccommerce",
+             "https://www.facebook.com/groups/crossborderelectroniccommerce"))
+
+    def test_group_numeric(self):
+        url = "https://www.facebook.com/groups/2245859412418547/"
+        self.assertEqual(
+            classify_fb_url(url),
+            ("group", "2245859412418547",
+             "https://www.facebook.com/groups/2245859412418547"))
+
+    def test_group_slug_without_trailing_slash(self):
+        url = "https://www.facebook.com/groups/yiliukescrm"
+        self.assertEqual(
+            classify_fb_url(url),
+            ("group", "yiliukescrm",
+             "https://www.facebook.com/groups/yiliukescrm"))
+
+    def test_video_is_none(self):
+        self.assertIsNone(
+            classify_fb_url("https://www.facebook.com/watch/?v=123456789"))
+
+    def test_user_profile_is_none(self):
+        self.assertIsNone(classify_fb_url("https://www.facebook.com/someuser"))
+
+    def test_non_facebook_is_none(self):
+        self.assertIsNone(
+            classify_fb_url("https://www.youtube.com/watch?v=abc"))
+
+
+class TestAtomParams(unittest.TestCase):
+    def test_missing_query_is_fatal(self):
+        with mock.patch.object(fd, "_http_get") as m:
+            r = _run({})
+        self.assertIs(r.outcome, Outcome.FATAL)
+        m.assert_not_called()          # FATAL 不发请求
+
+    def test_non_str_query_is_fatal(self):
+        r = _run({"query": 123})
+        self.assertIs(r.outcome, Outcome.FATAL)
+
+    def test_blank_query_is_fatal(self):
+        r = _run({"query": "   "})
+        self.assertIs(r.outcome, Outcome.FATAL)
+
+    def test_page_lt_1_is_fatal(self):
+        for page in (0, -1, "0"):
+            r = _run({"query": "x", "page": page})
+            self.assertIs(r.outcome, Outcome.FATAL, f"page={page!r}")
+
+
+class TestAtomHttpOutcomes(unittest.TestCase):
+    def test_ok_with_results(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())) as m:
+            ctx = _Ctx()
+            r = _run({"query": SAMPLE_QUERY}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.OK)
+        self.assertEqual(r.data["engine"], "ddg")
+        self.assertEqual(r.data["query"], SAMPLE_QUERY)
+        self.assertEqual(r.data["page"], 1)
+        results = r.data["results"]
+        self.assertEqual(len(results), 10)
+        first = results[0]
+        self.assertEqual(set(first), {"url", "title", "kind",
+                                      "group_id", "group_url"})
+        self.assertEqual(first["kind"], "group")
+        self.assertEqual(
+            first["group_url"],
+            "https://www.facebook.com/groups/crossborderelectroniccommerce")
+        # 请求 URL：q=quote(query)（safe='/'）、s=offset=0
+        url_called = m.call_args[0][0]
+        self.assertIn(f"q={urllib.parse.quote(SAMPLE_QUERY)}", url_called)
+        self.assertIn("&s=0", url_called)
+        # 正常路径：请求后节奏 wait 恰好 1 次，且 ≥ 60s 地板
+        self.assertEqual(len(ctx.waits), 1)
+        self.assertGreaterEqual(ctx.waits[0], 60)
+
+    def test_page_2_offset(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())) as m:
+            _run({"query": "x", "page": 2})
+        self.assertIn("&s=10", m.call_args[0][0])
+
+    def test_ok_mixed_kinds(self):
+        """帖 + 群主页 + 非 FB 混合：全部保留，非 FB 的 kind 为 None。"""
+        html = (
+            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+            '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2F123%2Fposts%2F456%2F'
+            '&amp;rut=a">Post A</a>'
+            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+            '?uddg=https%3A%2F%2Fwww.facebook.com%2Fgroups%2Fslugg%2F&amp;rut=b">'
+            'Group B</a>'
+            '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/'
+            '?uddg=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc&amp;rut=c">'
+            'Video C</a>')
+        with mock.patch.object(fd, "_http_get", return_value=(200, html)):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.OK)
+        results = r.data["results"]
+        self.assertEqual(len(results), 3)
+        self.assertEqual(results[0]["kind"], "post")
+        self.assertEqual(results[0]["group_id"], "123")
+        self.assertEqual(results[0]["group_url"],
+                         "https://www.facebook.com/groups/123")
+        self.assertEqual(results[1]["kind"], "group")
+        self.assertIsNone(results[2]["kind"])
+        self.assertIsNone(results[2]["group_id"])
+
+    def test_empty_serp_is_empty(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, "<html>nothing</html>")):
+            ctx = _Ctx()
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.EMPTY)
+        self.assertEqual(len(ctx.waits), 1)   # 空结果也走请求后节奏
+
+    def test_202_is_blocked_with_backoff_wait(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(202, "anomaly")):
+            ctx = _Ctx()
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.BLOCKED)
+        # 202 路径：退避 uniform(180,240) + 请求后节奏 = 2 次 wait
+        self.assertEqual(len(ctx.waits), 2)
+        self.assertGreaterEqual(ctx.waits[0], 180)
+        self.assertLessEqual(ctx.waits[0], 240)
+        self.assertGreaterEqual(ctx.waits[1], 60)
+
+    def test_403_is_blocked(self):
+        with mock.patch.object(fd, "_http_get", return_value=(403, "")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.BLOCKED)
+
+    def test_429_is_blocked(self):
+        with mock.patch.object(fd, "_http_get", return_value=(429, "")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.BLOCKED)
+
+    def test_5xx_is_net_error(self):
+        with mock.patch.object(fd, "_http_get", return_value=(500, "")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.NET_ERROR)
+
+    def test_transport_error_is_net_error_no_wait(self):
+        with mock.patch.object(fd, "_http_get",
+                               side_effect=OSError("connection reset")):
+            ctx = _Ctx()
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.NET_ERROR)
+        self.assertEqual(ctx.waits, [])   # 传输异常无响应，不节奏 wait
+
+    def test_timeout_is_net_error(self):
+        with mock.patch.object(fd, "_http_get",
+                               side_effect=TimeoutError("timed out")):
+            r = _run({"query": "x"})
+        self.assertIs(r.outcome, Outcome.NET_ERROR)
+
+    def test_stopped_is_skipped_no_wait_no_http(self):
+        with mock.patch.object(fd, "_http_get") as m:
+            ctx = _Ctx(stopped=True)
+            r = _run({"query": "x"}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.SKIPPED)
+        self.assertEqual(ctx.waits, [])
+        m.assert_not_called()
+
+    def test_interrupted_during_wait_is_skipped(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            r = _run({"query": "x"}, ctx=_StopAfterRequest())
+        self.assertIs(r.outcome, Outcome.SKIPPED)
+
+    def test_rhythm_floor_enforced(self):
+        """task 透传的 config 节奏（13-20s）低于 60s 地板 → 强制 60s。"""
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            ctx = _Ctx()
+            _run({"query": "x", "sample_min": 10, "sample_max": 20}, ctx=ctx)
+        self.assertEqual(ctx.waits, [60.0])
+
+    def test_rhythm_range_respected(self):
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            ctx = _Ctx()
+            _run({"query": "x", "sample_min": 90, "sample_max": 120}, ctx=ctx)
+        self.assertEqual(len(ctx.waits), 1)
+        self.assertGreaterEqual(ctx.waits[0], 90)
+        self.assertLessEqual(ctx.waits[0], 120)
+
+    def test_timeout_zero_passed_through(self):
+        """显式 timeout=0 不被 or 缺省吞掉（0 or 30 → 30 是反模式）。
+
+        None 判断语义：显式 0 是合法输入，原样传给 _http_get。
+        """
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())) as m:
+            ctx = _Ctx()
+            r = _run({"query": "x", "timeout": 0}, ctx=ctx)
+        self.assertIs(r.outcome, Outcome.OK)
+        self.assertEqual(m.call_args[1]["timeout"], 0)
+
+    def test_sample_zero_not_swallowed_by_or_default(self):
+        """显式 sample_min=0/sample_max=0 不被 or 缺省吞掉。
+
+        直接断言传给 random.uniform 的区间（参数解析层，确定性）：
+        None 判断语义下 sample_min=0 被 floor 抬到 60、sample_max=0 被
+        max(sample_max, sample_min) 抬到 60 → uniform(60.0, 60.0)；
+        or 反模式下 sample_max 走 `0 or (60+20)` → uniform(60.0, 80.0)。
+        """
+        with mock.patch.object(fd, "_http_get",
+                               return_value=(200, _sample_html())):
+            with mock.patch.object(fd.random, "uniform") as uni:
+                uni.return_value = 61.0
+                ctx = _Ctx()
+                _run({"query": "x", "sample_min": 0, "sample_max": 0},
+                     ctx=ctx)
+        self.assertEqual(uni.call_args[0], (60.0, 60.0))
+
+
+class _FakeResp:
+    """最小 urllib 响应替身：可带 gzip 头。"""
+
+    def __init__(self, body: bytes, encoding: str | None = None):
+        self._body = body
+        self.headers = {}
+        if encoding:
+            self.headers["Content-Encoding"] = encoding
+        self.status = 200
+
+    def read(self) -> bytes:
+        return self._body
+
+    def __enter__(self):
+        return self
+
+    def __exit__(self, *exc):
+        return False
+
+
+class TestHttpGet(unittest.TestCase):
+    def test_request_headers(self):
+        with mock.patch("urllib.request.urlopen",
+                        return_value=_FakeResp(b"<html>ok</html>")) as m:
+            status, html = fd._http_get(
+                "https://html.duckduckgo.com/html/?q=x", timeout=5)
+        self.assertEqual(status, 200)
+        self.assertEqual(html, "<html>ok</html>")
+        req = m.call_args[0][0]
+        # Request 的 add_header 会把 key 首字母大写、其余小写，get_header 在此
+        # Python 版本是大小写敏感直接查 dict——统一转小写做不区分大小写断言。
+        sent = {k.lower(): v for k, v in req.headers.items()}
+        self.assertTrue(sent["user-agent"].startswith("Mozilla/"))
+        self.assertEqual(sent["accept-language"], "zh-CN")
+        self.assertEqual(sent["accept-encoding"], "gzip")
+        self.assertEqual(m.call_args[1]["timeout"], 5)
+
+    def test_gzip_decompress(self):
+        raw = "<html>gzipped</html>".encode("utf-8")
+        with mock.patch("urllib.request.urlopen",
+                        return_value=_FakeResp(gzip.compress(raw),
+                                               encoding="gzip")):
+            status, html = fd._http_get(
+                "https://html.duckduckgo.com/html/?q=x")
+        self.assertEqual(status, 200)
+        self.assertEqual(html, "<html>gzipped</html>")
+
+    def test_http_error_returns_status(self):
+        err = urllib.error.HTTPError("https://x", 429, "rate limited",
+                                     hdrs={}, fp=None)
+        with mock.patch("urllib.request.urlopen", side_effect=err):
+            status, html = fd._http_get(
+                "https://html.duckduckgo.com/html/?q=x")
+        self.assertEqual(status, 429)
+        self.assertEqual(html, "")
+
+    def test_urlerror_raised(self):
+        with mock.patch("urllib.request.urlopen",
+                        side_effect=urllib.error.URLError("dns fail")):
+            with self.assertRaises(urllib.error.URLError):
+                fd._http_get("https://html.duckduckgo.com/html/?q=x")
+
+    def test_socket_timeout_raised(self):
+        with mock.patch("urllib.request.urlopen",
+                        side_effect=socket.timeout("timed out")):
+            with self.assertRaises(socket.timeout):
+                fd._http_get("https://html.duckduckgo.com/html/?q=x")
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_fb_discover_task.py b/fetcher/tests/test_fb_discover_task.py
new file mode 100644
index 0000000..8071588
--- /dev/null
+++ b/fetcher/tests/test_fb_discover_task.py
@@ -0,0 +1,302 @@
+# -*- coding: utf-8 -*-
+"""Step 1.3: FbDiscoverTask 测试（SPEC §5.2）。
+
+覆盖：fetch 原子透传（query/page/sample_min/max）、on_success 分流落库
+（帖→fb_posts 且 keyword/source='ddg' 溯源、群→fb_groups、帖派生群同时进
+两表、名称去 | Facebook / - Facebook 后缀、kind=None 跳过、空 results 防御、
+无 group_id 防御）、on_giveup 无落库 + 短语 + failed 计数、acquire_item 认领
++ payload id 注入、prepare/label/make_stats、名称净化边界。mock 只在原子层
+（FetchDdgSerp.run），落库用真实 ShopDB 临时库断言。
+"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import MagicMock
+
+from fetcher import IdentityStore, RunConfig, ShopDB, WorkerContext
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.sites.facebook.discover_task import (
+    FbDiscoverTask,
+    QUEUE,
+    _clean_title,
+)
+
+# 帖 permalink 与派生群主页（对齐 FetchDdgSerp OK 输出形态）
+POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
+            "1437583168191347/")
+GROUP_URL = "https://www.facebook.com/groups/185879310028412"
+GID = "185879310028412"
+QUERY = "site:facebook.com/groups 跨境电商 whatsapp"
+
+
+def _ctx(db, consumer_kind="local", wid=0):
+    """真实 WorkerContext（字段可空装配）+ IdentityStore 包装临时库；
+    set_status 记录调用供断言。"""
+    ctx = WorkerContext(config=RunConfig(), log=lambda m: None)
+    ctx.consumer_kind = consumer_kind
+    ctx.wid = wid
+    ctx.store = IdentityStore(db)
+    ctx.state["task"] = {"stats": {"ok": 0, "empty": 0, "failed": 0}}
+    ctx.status_calls = []
+    ctx.set_status = lambda **kw: ctx.status_calls.append(kw)
+    return ctx
+
+
+def _result(results):
+    return ActionResult(Outcome.OK, "ok", {"results": results})
+
+
+def _post_result(url=POST_URL, title="深圳跨境电商群 | Facebook"):
+    return {"url": url, "title": title, "kind": "post",
+            "group_id": GID, "group_url": GROUP_URL}
+
+
+def _group_result(title="深圳外贸交流 - Facebook"):
+    return {"url": GROUP_URL, "title": title, "kind": "group",
+            "group_id": GID, "group_url": GROUP_URL}
+
+
+def _non_fb_result():
+    return {"url": "https://www.1688.com/", "title": "1688 首页",
+            "kind": None, "group_id": None, "group_url": None}
+
+
+class FbDiscoverTaskTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+        self.task = FbDiscoverTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _fb_posts(self):
+        return self.db.conn.execute(
+            "SELECT url, group_id, group_name, keyword, source FROM fb_posts"
+        ).fetchall()
+
+    def _fb_groups(self):
+        return self.db.conn.execute(
+            "SELECT url, group_id, name, source FROM fb_groups"
+        ).fetchall()
+
+    def _enqueue(self, query=QUERY, page=1):
+        self.db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, requires,"
+            " created_at) VALUES (?, NULL, ?, ?, '2026-08-09 10:00:00')",
+            (QUEUE, json.dumps({"query": query, "page": page},
+                               ensure_ascii=False), '["local"]'))
+        self.db.conn.commit()
+
+    # ---- fetch 原子透传 ----
+
+    def test_fetch_passes_query_page_and_pacing_to_atom(self):
+        """fetch 调 FetchDdgSerp 原子，params 透传 query/page/sample_min/max。"""
+        mock_atom = MagicMock()
+        sentinel = ActionResult(Outcome.OK, "ok", {})
+        mock_atom.run.return_value = sentinel
+        self.task._make_atom = lambda: mock_atom
+        cfg = RunConfig(sample_min=13.0, sample_max=20.0)
+        ctx = WorkerContext(config=cfg, log=lambda m: None)
+        item = {"query": QUERY, "page": 2}
+        r = self.task.fetch(ctx, item)
+        self.assertIs(r, sentinel)
+        mock_atom.run.assert_called_once()
+        params = mock_atom.run.call_args[0][1]
+        self.assertEqual(params, {"query": QUERY, "page": 2,
+                                  "sample_min": 13.0, "sample_max": 20.0})
+
+    # ---- on_success 分流落库 ----
+
+    def test_on_success_post_goes_to_fb_posts_and_derived_group_to_groups(self):
+        """帖 permalink → fb_posts（keyword/source='ddg' 溯源）；帖派生群同时
+        进 fb_groups；名称去 | Facebook 后缀。返回新增帖数。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([_post_result()]))
+        self.assertEqual(n, 1)
+        posts = self._fb_posts()
+        self.assertEqual(len(posts), 1)
+        p = posts[0]
+        self.assertEqual(p["url"], POST_URL)
+        self.assertEqual(p["group_id"], GID)
+        self.assertEqual(p["group_name"], "深圳跨境电商群")
+        self.assertEqual(p["keyword"], QUERY)
+        self.assertEqual(p["source"], "ddg")
+        groups = self._fb_groups()
+        self.assertEqual(len(groups), 1)
+        g = groups[0]
+        self.assertEqual(g["url"], GROUP_URL)
+        self.assertEqual(g["group_id"], GID)
+        self.assertEqual(g["name"], "深圳跨境电商群")
+        self.assertEqual(g["source"], "ddg")
+
+    def test_on_success_group_goes_to_fb_groups_only(self):
+        """群主页 → 仅 fb_groups（url 取 group_url），不落 fb_posts。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([_group_result()]))
+        self.assertEqual(n, 0)
+        self.assertEqual(len(self._fb_posts()), 0)
+        groups = self._fb_groups()
+        self.assertEqual(len(groups), 1)
+        self.assertEqual(groups[0]["url"], GROUP_URL)
+        self.assertEqual(groups[0]["name"], "深圳外贸交流")  # 去 - Facebook 后缀
+
+    def test_on_success_mixed_kinds_fan_out(self):
+        """混合条目：帖 + 群 + 非 FB → 两表各得其位，非 FB 跳过。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(
+            ctx, {"query": QUERY, "page": 1},
+            _result([_post_result(), _group_result(), _non_fb_result()]))
+        self.assertEqual(n, 1)
+        self.assertEqual(len(self._fb_posts()), 1)
+        groups = self._fb_groups()
+        # 帖派生群 + 群主页同 URL → INSERT OR IGNORE 去重为 1 行
+        self.assertEqual(len(groups), 1)
+        self.assertEqual(groups[0]["url"], GROUP_URL)
+
+    def test_on_success_kind_none_skipped(self):
+        """kind=None 的非 FB 条目跳过（不落任何表），stats 仍算 ok。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([_non_fb_result()]))
+        self.assertEqual(n, 0)
+        self.assertEqual(len(self._fb_posts()), 0)
+        self.assertEqual(len(self._fb_groups()), 0)
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
+
+    def test_on_success_cleans_name_suffixes(self):
+        """名称去 | Facebook / - Facebook 后缀（strip 后 endswith，去一次）；
+        无后缀原样；空标题落空串。"""
+        ctx = _ctx(self.db)
+        results = [
+            _post_result(url=POST_URL + "1", title=" 群A | Facebook "),
+            _post_result(url=POST_URL + "2", title="群B - Facebook"),
+            _post_result(url=POST_URL + "3", title="群C（无后缀）"),
+            _post_result(url=POST_URL + "4", title=""),
+        ]
+        self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                             _result(results))
+        names = sorted(r["group_name"] for r in self._fb_posts())
+        self.assertEqual(names, ["", "群A", "群B", "群C（无后缀）"])
+
+    def test_on_success_post_without_group_id(self):
+        """帖无 group_id/group_url（防御）→ fb_posts 落 group_id NULL，
+        不派生群行，不崩。"""
+        ctx = _ctx(self.db)
+        results = [{"url": POST_URL, "title": "孤儿帖 | Facebook",
+                    "kind": "post", "group_id": None, "group_url": None}]
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result(results))
+        self.assertEqual(n, 1)
+        p = self._fb_posts()[0]
+        self.assertIsNone(p["group_id"])
+        self.assertEqual(len(self._fb_groups()), 0)
+
+    def test_on_success_counts_ok_and_calls_set_status(self):
+        """有 results 且落库 → ok+1；set_status 携带 ok/empty/failed 计数。"""
+        ctx = _ctx(self.db)
+        self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                             _result([_post_result()]))
+        self.assertEqual(ctx.state["task"]["stats"],
+                         {"ok": 1, "empty": 0, "failed": 0})
+        last = ctx.status_calls[-1]
+        self.assertEqual(last["ok"], 1)
+        self.assertEqual(last["empty"], 0)
+        self.assertEqual(last["failed"], 0)
+        self.assertEqual(last["n"], 1)
+
+    def test_on_success_empty_results_counts_empty(self):
+        """results 空（防御：正常 OK 路径不会出现）→ empty+1，返回 0。"""
+        ctx = _ctx(self.db)
+        n = self.task.on_success(ctx, {"query": QUERY, "page": 1},
+                                 _result([]))
+        self.assertEqual(n, 0)
+        stats = ctx.state["task"]["stats"]
+        self.assertEqual(stats, {"ok": 0, "empty": 1, "failed": 0})
+        self.assertEqual(len(self._fb_posts()), 0)
+        self.assertEqual(len(self._fb_groups()), 0)
+
+    # ---- on_giveup ----
+
+    def test_on_giveup_no_db_write_and_counts_failed(self):
+        """BLOCKED/NET_ERROR/EMPTY 均不落库，仅 failed+1 + 返回短语。"""
+        ctx = _ctx(self.db)
+        phrase = self.task.on_giveup(ctx, {"query": QUERY, "page": 1},
+                                     "DDG 限流（HTTP 202）", "block")
+        self.assertIsInstance(phrase, str)
+        self.assertTrue(phrase)
+        self.assertEqual(len(self._fb_posts()), 0)
+        self.assertEqual(len(self._fb_groups()), 0)
+        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)
+
+    # ---- acquire_item ----
+
+    def test_acquire_item_claims_discover_fb_and_injects_id(self):
+        """认领 discover_fb 最老 pending 项，payload 注入 id；行置 claimed。"""
+        self._enqueue()
+        self._enqueue(query=QUERY + "2", page=2)
+        ctx = _ctx(self.db)
+        item = self.task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["query"], QUERY)
+        self.assertEqual(item["page"], 1)
+        self.assertIn("id", item)
+        row = self.db.conn.execute(
+            "SELECT status, claimed_by FROM work_items"
+            " WHERE payload_json LIKE ?", ("%" + QUERY + "%",)).fetchone()
+        self.assertEqual(row[0], "claimed")
+        self.assertEqual(row[1], "local0")
+
+    def test_acquire_item_empty_queue_returns_none(self):
+        ctx = _ctx(self.db)
+        self.assertIsNone(self.task.acquire_item(ctx))
+
+    # ---- 元数据 ----
+
+    def test_class_attrs(self):
+        self.assertEqual(FbDiscoverTask.name, "fb_discover")
+        self.assertEqual(FbDiscoverTask.unit, "查询")
+        self.assertEqual(FbDiscoverTask.QUEUE, "discover_fb")
+
+    def test_make_stats(self):
+        self.assertEqual(self.task.make_stats(),
+                         {"ok": 0, "empty": 0, "failed": 0})
+
+    def test_label(self):
+        item = {"query": QUERY, "page": 3}
+        self.assertEqual(self.task.label(item), f"{QUERY} 第3页")
+
+    def test_prepare_returns_true(self):
+        self._enqueue()
+        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
+        self.assertTrue(self.task.prepare(cfg))
+
+
+class CleanTitleTest(unittest.TestCase):
+    def test_strips_pipe_facebook_suffix(self):
+        self.assertEqual(_clean_title("深圳跨境电商群 | Facebook"),
+                         "深圳跨境电商群")
+
+    def test_strips_dash_facebook_suffix(self):
+        self.assertEqual(_clean_title("深圳外贸交流 - Facebook"),
+                         "深圳外贸交流")
+
+    def test_no_suffix_unchanged(self):
+        self.assertEqual(_clean_title("普通标题"), "普通标题")
+
+    def test_strips_whitespace_before_match(self):
+        self.assertEqual(_clean_title("  群A | Facebook  "), "群A")
+
+    def test_blank_or_none(self):
+        self.assertEqual(_clean_title(""), "")
+        self.assertEqual(_clean_title(None), "")
+        self.assertEqual(_clean_title("   "), "")
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_fb_group_task.py b/fetcher/tests/test_fb_group_task.py
new file mode 100644
index 0000000..f8bb15e
--- /dev/null
+++ b/fetcher/tests/test_fb_group_task.py
@@ -0,0 +1,270 @@
+# -*- coding: utf-8 -*-
+"""Step 2.1: FbGroupTask 测试。
+
+覆盖：fetch 透传（url/provider/limit 断言）、on_success 逐帖落号
+（post_url 溯源 + group_id）+ 群 done 回写（post_count/has_contact/
+last_crawled_at）、on_giveup 群 failed、prepare 崩溃恢复（in_progress
+→ pending）、acquire_item 认领 + id 注入、label 格式、giveup_cost、
+make_stats、on_abort 短语。全 mock 原子，不起真实网络/API；落库断言
+用真实 ShopDB 临时库。
+"""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest.mock import MagicMock
+
+from fetcher import RunConfig, ShopDB
+from fetcher.core.types import ActionResult, Outcome
+from fetcher.sites.facebook.group_task import FbGroupTask
+from fetcher.sites.facebook.urls import group_id_from_url
+
+GROUP_URL = "https://www.facebook.com/groups/185879310028412"
+POST_URL_1 = GROUP_URL + "/posts/1111111111111/"
+POST_URL_2 = GROUP_URL + "/posts/2222222222222/"
+
+
+def _seed_group(db, url=GROUP_URL, status="pending"):
+    db.conn.execute(
+        "INSERT INTO fb_groups (url, group_id, name, source, status,"
+        " first_seen_at) VALUES (?, '185879310028412',"
+        " 'Shenzhen Expats 2026', 'ddg', ?, '2026-08-08 10:00:00')",
+        (url, status))
+    db.conn.commit()
+
+
+class _Ctx:
+    """最小 WorkerContext 替身（store/state/set_status/consumer_kind）。"""
+
+    def __init__(self, db):
+        self.store = MagicMock()
+        self.store.db = db
+        self.state = {"task": {"stats": {"ok": 0, "empty": 0, "failed": 0}}}
+        self.status_calls = []
+        self.consumer_kind = "local"
+        self.wid = 0
+        self.logs = []
+
+    def set_status(self, **kw):
+        self.status_calls.append(kw)
+
+    def log(self, msg):
+        self.logs.append(msg)
+
+
+def _result(posts=None, has_contact=None):
+    """原子 OK 结果：posts 逐帖含 phones（模拟 parse_post 分桶）。"""
+    posts = posts if posts is not None else [
+        {"url": POST_URL_1, "text": "x" * 200,
+         "phones": [{"number": "13812345678", "bucket": "cn_uncertain",
+                     "source": "text"}]},
+        {"url": POST_URL_2, "text": "y" * 200, "phones": []},
+    ]
+    phones = []
+    seen = set()
+    for p in posts:
+        for ph in p.get("phones") or []:
+            if ph["number"] not in seen:
+                seen.add(ph["number"])
+                phones.append(ph)
+    data = {"provider": "brightdata", "group_url": GROUP_URL,
+            "post_count": len(posts), "posts": posts, "phones": phones,
+            "has_contact": has_contact if has_contact is not None
+            else bool(phones)}
+    return ActionResult(Outcome.OK, "ok", data)
+
+
+class FbGroupTaskTest(unittest.TestCase):
+    def setUp(self):
+        self._tmp = tempfile.TemporaryDirectory()
+        self.db = ShopDB(Path(self._tmp.name) / "t.db")
+        self.task = FbGroupTask()
+
+    def tearDown(self):
+        self.db.close()
+        self._tmp.cleanup()
+
+    def _ctx(self):
+        return _Ctx(self.db)
+
+    # ---- fetch 透传 ----
+
+    def test_fetch_passes_url_provider_limit_to_atom(self):
+        mock_atom = MagicMock()
+        sentinel = ActionResult(Outcome.OK, "ok", {})
+        mock_atom.run.return_value = sentinel
+        self.task._make_atom = lambda: mock_atom
+        ctx = self._ctx()
+        item = {"url": GROUP_URL, "provider": "apify", "limit": 20}
+        r = self.task.fetch(ctx, item)
+        self.assertIs(r, sentinel)
+        mock_atom.run.assert_called_once()
+        params = mock_atom.run.call_args[0][1]
+        self.assertEqual(params, {"url": GROUP_URL, "provider": "apify",
+                                  "limit": 20})
+
+    def test_fetch_defaults_provider_limit(self):
+        """payload 缺 provider/limit：provider=None 透传（原子缺省
+        brightdata）、limit 取原子缺省 10。"""
+        mock_atom = MagicMock()
+        mock_atom.run.return_value = ActionResult(Outcome.OK, "ok", {})
+        self.task._make_atom = lambda: mock_atom
+        self.task.fetch(self._ctx(), {"url": GROUP_URL})
+        params = mock_atom.run.call_args[0][1]
+        self.assertEqual(params["provider"], None)
+        self.assertEqual(params["limit"], 10)
+
+    # ---- on_success 落库 ----
+
+    def test_on_success_saves_contacts_per_post_and_marks_done(self):
+        _seed_group(self.db)
+        ctx = self._ctx()
+        r = _result()
+        n = self.task.on_success(ctx, {"url": GROUP_URL}, r)
+        self.assertEqual(n, 2)  # 返回帖数（计入批次配额）
+        rows = {row["post_url"]: row for row in self.db.conn.execute(
+            "SELECT * FROM fb_contacts").fetchall()}
+        # 逐帖落号：post_url 溯源 + group_id 从群 URL 解析
+        self.assertEqual(rows[POST_URL_1]["number"], "13812345678")
+        self.assertEqual(rows[POST_URL_1]["group_id"], "185879310028412")
+        # 第二帖无号码 → 无对应 fb_contacts 行
+        self.assertEqual(len(rows), 1)
+        # 群 done 回写三字段
+        group = self.db.conn.execute(
+            "SELECT * FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
+        self.assertEqual(group["status"], "done")
+        self.assertEqual(group["post_count"], 2)
+        self.assertEqual(group["has_contact"], 1)
+        self.assertIsNotNone(group["last_crawled_at"])
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
+        self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)
+
+    def test_on_success_stats_judged_per_post_phones(self):
+        """stats ok/empty 判定基于逐帖 post['phones']，不依赖原子顶级
+        phones/has_contact 聚合（原子结构变化不影响判定）。"""
+        # 场景 1：逐帖有号码但顶级聚合缺失 → ok + has_contact=1
+        _seed_group(self.db)
+        ctx = self._ctx()
+        posts = [{"url": POST_URL_1, "text": "x" * 200,
+                  "phones": [{"number": "13812345678",
+                               "bucket": "cn_uncertain",
+                               "source": "text"}]}]
+        data = {"provider": "brightdata", "group_url": GROUP_URL,
+                "post_count": 1, "posts": posts}  # 顶级 phones/has_contact 缺失
+        self.task.on_success(ctx, {"url": GROUP_URL},
+                             ActionResult(Outcome.OK, "ok", data))
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 1)
+        self.assertEqual(ctx.state["task"]["stats"]["empty"], 0)
+        self.assertEqual(self.db.conn.execute(
+            "SELECT has_contact FROM fb_groups WHERE url=?",
+            (GROUP_URL,)).fetchone()[0], 1)
+        # 场景 2：逐帖全无号码但顶级聚合有值 → empty + has_contact=0
+        url2 = GROUP_URL + "2"
+        _seed_group(self.db, url=url2)
+        ctx2 = self._ctx()
+        posts2 = [{"url": POST_URL_2, "text": "x" * 200, "phones": []}]
+        data2 = {"provider": "brightdata", "group_url": url2,
+                 "post_count": 1, "posts": posts2,
+                 "phones": [{"number": "1"}], "has_contact": True}
+        self.task.on_success(ctx2, {"url": url2},
+                             ActionResult(Outcome.OK, "ok", data2))
+        self.assertEqual(ctx2.state["task"]["stats"]["ok"], 0)
+        self.assertEqual(ctx2.state["task"]["stats"]["empty"], 1)
+        self.assertEqual(self.db.conn.execute(
+            "SELECT has_contact FROM fb_groups WHERE url=?",
+            (url2,)).fetchone()[0], 0)
+
+    def test_on_success_no_phones_counts_empty_and_has_contact_0(self):
+        _seed_group(self.db)
+        ctx = self._ctx()
+        r = _result(posts=[{"url": POST_URL_1, "text": "x" * 200,
+                            "phones": []}])
+        self.task.on_success(ctx, {"url": GROUP_URL}, r)
+        group = self.db.conn.execute(
+            "SELECT status, post_count, has_contact FROM fb_groups"
+            " WHERE url=?", (GROUP_URL,)).fetchone()
+        self.assertEqual(group["status"], "done")
+        self.assertEqual(group["post_count"], 1)
+        self.assertEqual(group["has_contact"], 0)
+        self.assertEqual(ctx.state["task"]["stats"]["ok"], 0)
+        self.assertEqual(ctx.state["task"]["stats"]["empty"], 1)
+
+    # ---- on_giveup ----
+
+    def test_on_giveup_marks_failed(self):
+        _seed_group(self.db)
+        ctx = self._ctx()
+        phrase = self.task.on_giveup(ctx, {"url": GROUP_URL}, "block",
+                                     "block")
+        self.assertIsInstance(phrase, str)
+        row = self.db.conn.execute(
+            "SELECT status FROM fb_groups WHERE url=?", (GROUP_URL,)).fetchone()
+        self.assertEqual(row[0], "failed")
+        self.assertEqual(ctx.state["task"]["stats"]["failed"], 1)
+
+    # ---- prepare 崩溃恢复 ----
+
+    def test_prepare_resets_in_progress(self):
+        _seed_group(self.db, status="in_progress")
+        _seed_group(self.db, url=GROUP_URL + "2", status="pending")
+        cfg = RunConfig(db_path=Path(self._tmp.name) / "t.db")
+        ok = self.task.prepare(cfg)
+        self.assertTrue(ok)
+        statuses = [r[0] for r in self.db.conn.execute(
+            "SELECT status FROM fb_groups ORDER BY id").fetchall()]
+        self.assertEqual(statuses, ["pending", "pending"])
+
+    # ---- acquire_item ----
+
+    def test_acquire_item_claims_from_queue_with_id(self):
+        ctx = self._ctx()
+        self.db.conn.execute(
+            "INSERT INTO work_items (queue, site, payload_json, requires,"
+            " created_at) VALUES ('crawl_fb_group', 'facebook', ?,"
+            " '[\"local\"]', '2026-08-08 10:00:00')",
+            (json.dumps({"url": GROUP_URL, "provider": "brightdata",
+                         "limit": 10}),))
+        self.db.conn.commit()
+        item = self.task.acquire_item(ctx)
+        self.assertIsNotNone(item)
+        self.assertEqual(item["url"], GROUP_URL)
+        self.assertIn("id", item)
+
+    def test_acquire_item_empty_queue_returns_none(self):
+        ctx = self._ctx()
+        self.assertIsNone(self.task.acquire_item(ctx))
+
+    # ---- label / 配额 / stats / abort ----
+
+    def test_label_format(self):
+        self.assertEqual(
+            self.task.label({"url": GROUP_URL, "provider": "apify",
+                             "limit": 20}),
+            f"{GROUP_URL}（apify，≤20帖）")
+
+    def test_giveup_cost(self):
+        self.assertEqual(self.task.giveup_cost({}), 1)
+
+    def test_make_stats(self):
+        self.assertEqual(self.task.make_stats(),
+                         {"ok": 0, "empty": 0, "failed": 0})
+
+    def test_on_abort_phrase(self):
+        phrase = self.task.on_abort(self._ctx(), {"url": GROUP_URL})
+        self.assertIn("in_progress", phrase)
+        self.assertIn(GROUP_URL, phrase)
+
+    # ---- group_id 解析 ----
+
+    def test_group_id_from_url(self):
+        self.assertEqual(group_id_from_url(GROUP_URL),
+                         "185879310028412")
+        self.assertEqual(group_id_from_url(GROUP_URL + "/"),
+                         "185879310028412")
+        self.assertIsNone(group_id_from_url(""))
+        self.assertIsNone(group_id_from_url("https://www.1688.com/"))
+
+
+if __name__ == "__main__":
+    unittest.main()
diff --git a/fetcher/tests/test_fb_post_task.py b/fetcher/tests/test_fb_post_task.py
index 58e6d19..b6788ea 100644
--- a/fetcher/tests/test_fb_post_task.py
+++ b/fetcher/tests/test_fb_post_task.py
@@ -8,21 +8,22 @@ group_id 解析。全 mock 原子，不起真实浏览器/网络。
 """
 
 import json
 import tempfile
 import unittest
 from pathlib import Path
 from unittest.mock import MagicMock
 
 from fetcher import RunConfig, ShopDB, WorkerContext
 from fetcher.core.types import ActionResult, Outcome
-from fetcher.sites.facebook.post_task import FbPostTask, _group_id_from_url
+from fetcher.sites.facebook.post_task import FbPostTask
+from fetcher.sites.facebook.urls import group_id_from_url
 
 POST_URL = ("https://www.facebook.com/groups/185879310028412/posts/"
             "1437583168191347/")
 GROUP_URL = "https://www.facebook.com/groups/185879310028412"
 
 
 def _seed_post(db, url=POST_URL, status="pending"):
     db.conn.execute(
         "INSERT INTO fb_posts (url, group_id, group_name, keyword, source,"
         " status, first_seen_at) VALUES (?, '185879310028412',"
@@ -159,20 +160,72 @@ class FbPostTaskTest(unittest.TestCase):
                          {"wechat_ids": ["wx12345"], "tg_handles": ["tgbot1"],
                           "wa_group_invites": ["AbCdEf123456"]})
 
     def test_on_success_empty_sidecar_not_set(self):
         _seed_post(self.db)
         ctx = self._ctx()
         self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL},
                              _result())
         self.assertNotIn("result_json", ctx.state)
 
+    def test_on_success_upserts_group_row(self):
+        """抓帖后 fb_groups 出现派生群行（SPEC §5.5：每帖=发现一群）。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL,
+                                   "name": "Shenzhen Expats 2026"}, _result())
+        rows = self.db.conn.execute(
+            "SELECT * FROM fb_groups").fetchall()
+        self.assertEqual(len(rows), 1)
+        row = rows[0]
+        self.assertEqual(row["url"], GROUP_URL)
+        self.assertEqual(row["group_id"], "185879310028412")
+        self.assertEqual(row["name"], "Shenzhen Expats 2026")
+        self.assertEqual(row["source"], "fb_post")
+        self.assertEqual(row["status"], "pending")
+
+    def test_on_success_group_name_defaults_to_empty(self):
+        """payload 无 name 时群名缺省空串（name 溯源 or ""）。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        self.task.on_success(ctx, {"url": POST_URL, "domain": GROUP_URL},
+                             _result())
+        row = self.db.conn.execute(
+            "SELECT name, source FROM fb_groups").fetchone()
+        self.assertEqual(row[0], "")
+        self.assertEqual(row[1], "fb_post")
+
+    def test_on_success_no_group_id_zero_writes(self):
+        """item 无 domain/group_id 时 fb_groups 零写入（幂等边界）。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        self.task.on_success(ctx, {"url": POST_URL}, _result())
+        n = self.db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
+        self.assertEqual(n, 0)
+
+    def test_on_success_repeat_fetch_is_idempotent(self):
+        """重复抓同群帖：INSERT OR IGNORE 不新增行、不动既有状态。"""
+        _seed_post(self.db)
+        ctx = self._ctx()
+        item = {"url": POST_URL, "domain": GROUP_URL, "name": "G"}
+        self.task.on_success(ctx, item, _result())
+        # 二次抓帖：已有行不动（status/name 保持采集进度）
+        self.task.on_success(ctx, item, _result())
+        rows = self.db.conn.execute(
+            "SELECT COUNT(*) FROM fb_groups").fetchone()[0]
+        self.assertEqual(rows, 1)
+        row = self.db.conn.execute(
+            "SELECT name, status FROM fb_groups").fetchone()
+        self.assertEqual(row[0], "G")
+        self.assertEqual(row[1], "pending")
+
     def test_queue_router_finish_writes_sidecar_to_result_json(self):
         """侧车经 QueueRouter._finish 真正落 work_items.result_json
         （SPEC §8 观测副产物机制，触达 router 钩子代码）。"""
         from fetcher.control.queue_router import QueueRouter, QueueSpec
         spec = QueueSpec(queue="crawl_fb_post", site="facebook",
                          task=self.task)
         router = QueueRouter([spec])
         self.db.conn.execute(
             "INSERT INTO work_items (queue, site, payload_json, requires,"
             " created_at) VALUES ('crawl_fb_post', 'facebook', ?, ?, "
@@ -235,19 +288,19 @@ class FbPostTaskTest(unittest.TestCase):
         self.assertEqual(item["url"], POST_URL)
         self.assertIn("id", item)
 
     def test_acquire_item_empty_queue_returns_none(self):
         ctx = self._ctx()
         self.assertIsNone(self.task.acquire_item(ctx))
 
     # ---- group_id 解析 ----
 
     def test_group_id_from_url(self):
-        self.assertEqual(_group_id_from_url(GROUP_URL),
+        self.assertEqual(group_id_from_url(GROUP_URL),
                          "185879310028412")
-        self.assertEqual(_group_id_from_url(GROUP_URL + "/"), "185879310028412")
-        self.assertIsNone(_group_id_from_url(""))
-        self.assertIsNone(_group_id_from_url("https://www.1688.com/"))
+        self.assertEqual(group_id_from_url(GROUP_URL + "/"), "185879310028412")
+        self.assertIsNone(group_id_from_url(""))
+        self.assertIsNone(group_id_from_url("https://www.1688.com/"))
 
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/platform/server/app/api/tasks.py b/platform/server/app/api/tasks.py
index fba97b2..fbbe9e3 100644
--- a/platform/server/app/api/tasks.py
+++ b/platform/server/app/api/tasks.py
@@ -109,20 +109,25 @@ class TaskParams(BaseModel):
     max_consecutive_fail: int | None = None  # → --max-consecutive-fail
     block_rest_min: float | None = None     # → --block-rest-min
     block_rest_max: float | None = None     # → --block-rest-max
     # 开关
     use_proxy: bool | None = None           # true → --proxy
     headless: bool | None = None            # false → --headed
     auto_solve: bool | None = None          # false → --no-auto-solve
     retry_failed: bool | None = None        # 前端 1688_contact 表单开关遗留，不映射 CLI
     # wa_check 专用：
     accounts: list[str] | None = None       # 账号池，空 = 仅默认账号
+    # fb 批次专用：
+    keywords: str | None = None            # fb_discover：查询词，换行分隔原文
+    pages: int | None = None               # fb_discover：每词页数（1-10）
+    provider: str | None = None            # fb_group：brightdata / apify
+    posts_per_group: int | None = None     # fb_group：每群帖数上限
     # 注：batch_num/sample_min/sample_max 为 subprocess 类型（yiwugo）节奏参数；
     # wa_check 走 daemon 批次，只消费 limit/accounts
     # 循环模式：本轮正常结束（done/failed）后 N 秒自动重启；None/<=0 = 不循环
     repeat_interval: int | None = None
 
 
 class TaskCreate(BaseModel):
     type: str = Field(...)
     params: TaskParams = Field(default_factory=TaskParams)
 
diff --git a/platform/server/app/db.py b/platform/server/app/db.py
index 2f8301a..9ed68b4 100644
--- a/platform/server/app/db.py
+++ b/platform/server/app/db.py
@@ -232,20 +232,116 @@ def enqueue_fb_post_batch(queue: str, site: str, batch_id: int,
                 (r["id"],))
         conn.commit()
         return len(rows)
     except Exception:
         conn.rollback()
         raise
     finally:
         conn.close()
 
 
+def enqueue_fb_discover_batch(batch_id: int, keywords: str,
+                               pages: int) -> int:
+    """fb_discover 批次入队：关键词（换行分隔）逐词 × 页码展开。
+
+    payload {"kind":"serp","engine":"ddg","query":kw,"page":N}；
+    requires=["local"]、site=NULL。幂等：同 query+page 已有 pending
+    跳过（防循环模式重入批量重复堆栈，参照 enqueue_feeder_batch 的
+    json_extract 幂等模式）。keywords 空 → 0。返回入队 item 数。
+    """
+    words = [w.strip() for w in (keywords or "").splitlines()]
+    words = [w for w in words if w]
+    if not words:
+        return 0
+    pages = max(1, int(pages))
+    conn = sqlite3.connect(DB_PATH, timeout=30)
+    try:
+        conn.execute("PRAGMA busy_timeout = 30000")
+        now = _bj_now()
+        n = 0
+        for kw in words:
+            for page in range(1, pages + 1):
+                exists = conn.execute(
+                    "SELECT COUNT(*) FROM work_items WHERE queue=?"
+                    " AND status='pending'"
+                    " AND json_extract(payload_json, '$.query')=?"
+                    " AND json_extract(payload_json, '$.page')=?",
+                    ("discover_fb", kw, page)).fetchone()[0]
+                if exists:
+                    continue
+                payload = {"kind": "serp", "engine": "ddg",
+                           "query": kw, "page": page}
+                conn.execute(
+                    "INSERT INTO work_items (queue, site, batch_id,"
+                    " payload_json, requires, created_at)"
+                    " VALUES (?, NULL, ?, ?, ?, ?)",
+                    ("discover_fb", batch_id,
+                     json.dumps(payload, ensure_ascii=False),
+                     '["local"]', now))
+                n += 1
+        conn.commit()
+        return n
+    except Exception:
+        conn.rollback()
+        raise
+    finally:
+        conn.close()
+
+
+def enqueue_fb_group_batch(batch_id: int, provider: str,
+                           posts_per_group: int, limit: int) -> int:
+    """fb_group 批次入队：SELECT pending fb_groups → INSERT items →
+    源行置 in_progress（BEGIN IMMEDIATE 单事务，与群采集消费互斥不双喂，
+    对齐 enqueue_fb_post_batch）。
+
+    payload {"url","provider","limit"}（limit=posts_per_group）；
+    requires=["local"]、site=NULL。fb_groups 表不存在（fetcher 侧未建
+    表）→ 返回 0（防御性探测）。limit>0 限量（<=0 不限）。返回入队行数。
+    """
+    conn = sqlite3.connect(DB_PATH, timeout=30)
+    try:
+        conn.row_factory = sqlite3.Row
+        conn.execute("PRAGMA busy_timeout = 30000")
+        tables = {r[0] for r in conn.execute(
+            "SELECT name FROM sqlite_master WHERE type='table'")}
+        if "fb_groups" not in tables:
+            return 0
+        conn.execute("BEGIN IMMEDIATE")
+        sql = ("SELECT * FROM fb_groups WHERE status='pending'"
+               " ORDER BY first_seen_at, id")
+        params: list = []
+        if limit > 0:
+            sql += " LIMIT ?"
+            params.append(limit)
+        rows = conn.execute(sql, params).fetchall()
+        now = _bj_now()
+        for r in rows:
+            payload = json.dumps(
+                {"url": r["url"], "provider": provider,
+                 "limit": posts_per_group},
+                ensure_ascii=False)
+            conn.execute(
+                "INSERT INTO work_items (queue, site, batch_id, payload_json,"
+                " requires, created_at) VALUES (?, NULL, ?, ?, ?, ?)",
+                ("crawl_fb_group", batch_id, payload, '["local"]', now))
+            conn.execute(
+                "UPDATE fb_groups SET status='in_progress' WHERE id=?",
+                (r["id"],))
+        conn.commit()
+        return len(rows)
+    except Exception:
+        conn.rollback()
+        raise
+    finally:
+        conn.close()
+
+
 def enqueue_feeder_batch(queue: str, site: str, batch_id: int,
                          limit: int) -> tuple[int, int]:
     """feeder 批次入队：1 条 discover + 活跃类目 category 种子，全部带
     batch_id 与 payload.batch_limit（收束边界，0=不限）。幂等：已有同
     keyword pending category / pending discover 跳过。返回 (n_cat, n_disc)。
     """
     conn = sqlite3.connect(DB_PATH, timeout=30)
     try:
         conn.execute("PRAGMA busy_timeout = 30000")
         n_cat = 0
diff --git a/platform/server/app/runner.py b/platform/server/app/runner.py
index 8de7983..d9cc125 100644
--- a/platform/server/app/runner.py
+++ b/platform/server/app/runner.py
@@ -55,20 +55,28 @@ BATCH_TYPES = {
         "domain_suffix": "", "kind": "feeder",
     },
     "wa_check": {
         "queue": "wa_check", "site": None,
         "domain_suffix": "", "kind": "wa",
     },
     "fb_post": {
         "queue": "crawl_fb_post", "site": "facebook",
         "domain_suffix": "", "kind": "fb_post",
     },
+    "fb_discover": {
+        "queue": "discover_fb", "site": None,
+        "domain_suffix": "", "kind": "fb_discover",
+    },
+    "fb_group": {
+        "queue": "crawl_fb_group", "site": None,
+        "domain_suffix": "", "kind": "fb_group",
+    },
 }
 
 # 批次任务类型集合（TASK_TYPES = TASK_COMMANDS ∪ BATCH_TYPES）
 BATCH_TYPE_NAMES = set(BATCH_TYPES)
 
 BJ_TZ = timezone(timedelta(hours=8))
 
 _ERROR_KEYS = ("错误", "failed", "Error")
 _SUCCESS_KEYS = ("完成", "成功", "OK")
 _WARNING_KEYS = ("风控", "滑块", "警告")
@@ -286,28 +294,39 @@ def enqueue_batch_for_task(task_id: int, task_type: str,
     """批次任务入队：按 BATCH_TYPES 分派 contact/feeder/wa。返回 item 数。
 
     contact：limit 限量；feeder：discover+category 种子；wa：账号清单
     （params.accounts）50/块。batch_id = task_id。
     """
     spec = BATCH_TYPES.get(task_type)
     if spec is None:
         raise ValueError(f"非批次任务类型: {task_type}")
     params = params or {}
     limit = int(params.get("limit") or 0)
-    from app.db import (enqueue_contact_batch, enqueue_fb_post_batch,
+    from app.db import (enqueue_contact_batch, enqueue_fb_discover_batch,
+                        enqueue_fb_group_batch, enqueue_fb_post_batch,
                         enqueue_feeder_batch, enqueue_wa_batch)
     if spec["kind"] == "contact":
         return enqueue_contact_batch(spec["queue"], spec["site"],
                                      spec["domain_suffix"], task_id, limit)
     if spec["kind"] == "fb_post":
         return enqueue_fb_post_batch(spec["queue"], spec["site"],
                                      task_id, limit)
+    if spec["kind"] == "fb_discover":
+        # 缺省 keywords=""、pages=1
+        return enqueue_fb_discover_batch(task_id, params.get("keywords") or "",
+                                         int(params.get("pages") or 1))
+    if spec["kind"] == "fb_group":
+        # 缺省 provider="brightdata"、posts_per_group=50，limit 透传
+        return enqueue_fb_group_batch(task_id,
+                                      (params.get("provider") or "brightdata"),
+                                      int(params.get("posts_per_group") or 50),
+                                      limit)
     if spec["kind"] == "feeder":
         n_cat, n_disc = enqueue_feeder_batch(
             spec["queue"], spec["site"], task_id, limit)
         return n_cat + n_disc
     if spec["kind"] == "wa":
         accounts = params.get("accounts") or []
         return enqueue_wa_batch(task_id, accounts, limit)
     return 0
 
 
diff --git a/platform/server/tests/test_batch_tasks.py b/platform/server/tests/test_batch_tasks.py
index a589fca..d62fba1 100644
--- a/platform/server/tests/test_batch_tasks.py
+++ b/platform/server/tests/test_batch_tasks.py
@@ -434,20 +434,47 @@ class BatchStartStopTest(BatchTasksTestBase):
 
 
 class TaskTypesTest(BatchTasksTestBase):
     def test_task_types_include_batch_and_yiwugo(self):
         from app.api.tasks import TASK_TYPES
         for t in ("1688_contact", "madeinchina_contact", "1688_shop",
                   "1688_company", "madeinchina_shop", "wa_check",
                   "yiwugo_search"):
             self.assertIn(t, TASK_TYPES)
 
+    def test_task_types_union_contains_fb_batch_types(self):
+        """Step 3.3：TASK_TYPES 并集（TASK_COMMANDS ∪ BATCH_TYPES）含两新批次类型。"""
+        from app.api.tasks import TASK_TYPES
+        self.assertIn("fb_discover", TASK_TYPES)
+        self.assertIn("fb_group", TASK_TYPES)
+
+    def test_fb_batch_params_roundtrip_via_create_task(self):
+        """TaskCreate 携带四字段 → create_task 落库 params_json → 读回齐全。"""
+        from app.api.tasks import TaskCreate, create_task
+        body = TaskCreate(type="fb_discover", params={
+            "keywords": "耐克\n阿迪达斯",
+            "pages": 3,
+            "provider": "brightdata",
+            "posts_per_group": 50,
+        })
+        task = create_task(body)
+        conn = self._conn()
+        row = conn.execute(
+            "SELECT params_json FROM tasks WHERE id=?",
+            (task["id"],)).fetchone()
+        conn.close()
+        params = json.loads(row["params_json"])
+        self.assertEqual(params["keywords"], "耐克\n阿迪达斯")
+        self.assertEqual(params["pages"], 3)
+        self.assertEqual(params["provider"], "brightdata")
+        self.assertEqual(params["posts_per_group"], 50)
+
     def test_preview_batch_type_returns_description(self):
         from app.api.tasks import preview_task
         body = type("Body", (), {"type": "1688_contact",
                                  "params": type("P", (), {
                                      "model_dump": lambda self: {
                                          "limit": 50}})()})()
         result = preview_task(body)
         self.assertIn("批次", result["cmdline"])
 
     def test_runner_startup_skips_batch_orphan_cleanup(self):
@@ -468,12 +495,184 @@ class TaskTypesTest(BatchTasksTestBase):
         tr.shutdown()
         conn = self._conn()
         row = conn.execute("SELECT status FROM tasks WHERE id=?",
                            (tid,)).fetchone()
         conn.close()
         # 批次 running 不被标 failed（孤儿清理跳过）；sweeper 重建为 running
         # （有 pending item）——若清理误标会变 failed
         self.assertEqual(row["status"], "running")
 
 
+# =====================================================================
+# 5. Step 3.1：fb_discover / fb_group 分派
+# =====================================================================
+
+
+class FbBatchDispatchTest(BatchTasksTestBase):
+    """enqueue_batch_for_task 对 fb_discover/fb_group 分派参数透传。
+
+    enqueue_fb_discover_batch / enqueue_fb_group_batch 由 Step 3.2 实现，
+    本 Step mock app.db 模块属性断言分派参数（缺省值/显式值/limit 透传）。
+    """
+
+    def test_fb_discover_dispatch_with_defaults(self):
+        """缺省 keywords=""、pages=1。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_discover_batch",
+                          create=True, return_value=3) as mock_enqueue:
+            n = enqueue_batch_for_task(7, "fb_discover", {})
+        mock_enqueue.assert_called_once_with(7, "", 1)
+        self.assertEqual(n, 3)
+
+    def test_fb_discover_dispatch_with_explicit_keywords_pages(self):
+        """显式 keywords 原样透传、pages 转 int。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_discover_batch",
+                          create=True, return_value=3) as mock_enqueue:
+            n = enqueue_batch_for_task(
+                7, "fb_discover",
+                {"keywords": "面膜 洗面奶", "pages": "3"})
+        mock_enqueue.assert_called_once_with(7, "面膜 洗面奶", 3)
+        self.assertEqual(n, 3)
+
+    def test_fb_group_dispatch_with_defaults(self):
+        """缺省 provider="brightdata"、posts_per_group=50、limit=0。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_group_batch",
+                          create=True, return_value=4) as mock_enqueue:
+            n = enqueue_batch_for_task(8, "fb_group", {})
+        mock_enqueue.assert_called_once_with(8, "brightdata", 50, 0)
+        self.assertEqual(n, 4)
+
+    def test_fb_group_dispatch_with_explicit_values_and_limit(self):
+        """显式 provider/posts_per_group 转 int + limit 透传。"""
+        from app.runner import enqueue_batch_for_task
+        with patch.object(db_module, "enqueue_fb_group_batch",
+                          create=True, return_value=4) as mock_enqueue:
+            n = enqueue_batch_for_task(
+                8, "fb_group",
+                {"provider": "scraperapi", "posts_per_group": "30",
+                 "limit": "120"})
+        mock_enqueue.assert_called_once_with(8, "scraperapi", 30, 120)
+        self.assertEqual(n, 4)
+
+
+# =====================================================================
+# 6. Step 3.2：fb_discover / fb_group 真实入队
+# =====================================================================
+
+
+class FbBatchEnqueueTest(BatchTasksTestBase):
+    """enqueue_fb_discover_batch / enqueue_fb_group_batch 真实落库。
+
+    临时 sqlite 断言真实行：展开数/幂等/空关键词/限量/表缺失/源行置位/
+    payload 全键断言。
+    """
+
+    def _seed_fb_groups(self, n=3):
+        """建 fb_groups 表（对齐 fetcher 侧 schema）+ 种 n 条 pending 群。"""
+        conn = self._conn()
+        conn.execute(
+            "CREATE TABLE IF NOT EXISTS fb_groups ("
+            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
+            " url TEXT NOT NULL UNIQUE, group_id TEXT, name TEXT,"
+            " source TEXT NOT NULL DEFAULT 'ddg',"
+            " status TEXT NOT NULL DEFAULT 'pending', post_count INTEGER,"
+            " has_contact INTEGER, first_seen_at TEXT NOT NULL,"
+            " last_crawled_at TEXT)")
+        for i in range(n):
+            conn.execute(
+                "INSERT INTO fb_groups (url, group_id, name, status,"
+                " first_seen_at) VALUES (?, ?, ?, 'pending',"
+                " '2026-08-08 10:00:00')",
+                (f"https://www.facebook.com/groups/g{i}", f"g{i}",
+                 f"群{i}"))
+        conn.commit()
+        conn.close()
+
+    def test_fb_discover_expands_keywords_times_pages(self):
+        """2 词 × 2 页 = 4 条；payload 全键/requires/site/batch_id 断言。"""
+        from app.db import enqueue_fb_discover_batch
+        n = enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2)
+        self.assertEqual(n, 4)
+        items = self._wi(7)
+        self.assertEqual(len(items), 4)
+        for r in items:
+            self.assertEqual(r["queue"], "discover_fb")
+            self.assertIsNone(r["site"])
+            self.assertEqual(r["batch_id"], 7)
+            self.assertEqual(json.loads(r["requires"]), ["local"])
+            p = json.loads(r["payload_json"])
+            self.assertEqual(p["kind"], "serp")
+            self.assertEqual(p["engine"], "ddg")
+            self.assertIn(p["query"], ("面膜", "洗面奶"))
+            self.assertIn(p["page"], (1, 2))
+        # 每个词 × 每页组合恰好一条
+        combos = {(json.loads(r["payload_json"])["query"],
+                   json.loads(r["payload_json"])["page"])
+                  for r in items}
+        self.assertEqual(combos, {("面膜", 1), ("面膜", 2),
+                                  ("洗面奶", 1), ("洗面奶", 2)})
+
+    def test_fb_discover_idempotent_same_query_page(self):
+        """同 query+page 已有 pending → 二次调用入队 0（不重复堆栈）。"""
+        from app.db import enqueue_fb_discover_batch
+        self.assertEqual(enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2), 4)
+        self.assertEqual(enqueue_fb_discover_batch(7, "面膜\n洗面奶", 2), 0)
+        self.assertEqual(len(self._wi(7)), 4)
+
+    def test_fb_discover_empty_keywords_returns_zero(self):
+        """空关键词（空串/纯空白行）→ 0，不产生 item。"""
+        from app.db import enqueue_fb_discover_batch
+        self.assertEqual(enqueue_fb_discover_batch(7, "", 2), 0)
+        self.assertEqual(enqueue_fb_discover_batch(7, "  \n \n", 2), 0)
+        self.assertEqual(len(self._wi(7)), 0)
+
+    def test_fb_discover_pages_less_than_one_treated_as_one(self):
+        """pages<1 → 按 1 页处理（裁定 2）。"""
+        from app.db import enqueue_fb_discover_batch
+        self.assertEqual(enqueue_fb_discover_batch(7, "面膜", 0), 1)
+
+    def test_fb_group_enqueues_and_marks_in_progress(self):
+        """limit=2 取 2 群；payload {url,provider,limit}；源行置 in_progress。"""
+        from app.db import enqueue_fb_group_batch
+        self._seed_fb_groups(3)
+        n = enqueue_fb_group_batch(8, "brightdata", posts_per_group=50,
+                                   limit=2)
+        self.assertEqual(n, 2)
+        items = self._wi(8)
+        self.assertEqual(len(items), 2)
+        urls = [json.loads(r["payload_json"])["url"] for r in items]
+        self.assertEqual(urls[0], "https://www.facebook.com/groups/g0")
+        self.assertEqual(urls[1], "https://www.facebook.com/groups/g1")
+        for r in items:
+            self.assertEqual(r["queue"], "crawl_fb_group")
+            self.assertIsNone(r["site"])
+            self.assertEqual(r["batch_id"], 8)
+            self.assertEqual(json.loads(r["requires"]), ["local"])
+            p = json.loads(r["payload_json"])
+            self.assertEqual(set(p), {"url", "provider", "limit"})
+            self.assertEqual(p["provider"], "brightdata")
+            self.assertEqual(p["limit"], 50)
+        # 源行：前 2 群 in_progress，第 3 群保持 pending
+        conn = self._conn()
+        sts = conn.execute(
+            "SELECT status FROM fb_groups ORDER BY id").fetchall()
+        conn.close()
+        self.assertEqual([r["status"] for r in sts],
+                         ["in_progress", "in_progress", "pending"])
+
+    def test_fb_group_limit_zero_unlimited(self):
+        """limit=0（不限）→ 全部 pending 群入队。"""
+        from app.db import enqueue_fb_group_batch
+        self._seed_fb_groups(3)
+        self.assertEqual(enqueue_fb_group_batch(8, "brightdata", 50, 0), 3)
+
+    def test_fb_group_missing_table_returns_zero(self):
+        """fb_groups 表不存在（fetcher 侧未建）→ 0（防御性探测）。"""
+        from app.db import enqueue_fb_group_batch
+        self.assertEqual(enqueue_fb_group_batch(8, "brightdata", 50, 2), 0)
+        self.assertEqual(len(self._wi(8)), 0)
+
+
 if __name__ == "__main__":
     unittest.main()
diff --git a/platform/start.sh b/platform/start.sh
index cc76f94..74a4b79 100755
--- a/platform/start.sh
+++ b/platform/start.sh
@@ -16,20 +16,26 @@ FRONTEND_PORT=3000
 # 生产多 worker 由运维在此显式加 --workers N
 # daemon 全局有头运行：桌面会弹出浏览器窗口，属预期行为，勿当异常关闭
 DAEMON_ARGS=${DAEMON_ARGS:---workers 1}
 # 有头为全局硬性要求：即使外部覆盖了 DAEMON_ARGS，也强制保留 --headed
 [[ " $DAEMON_ARGS " == *" --headed "* ]] || DAEMON_ARGS="$DAEMON_ARGS --headed"
 
 # wa_check 查号账号池（逗号分隔，对应 vendor/wa-check/auth_info-<name>/）；
 # 缺省 default 无登录态，wa_check 批次会全部「未登录」空跑放弃
 export WA_CHECK_ACCOUNTS=${WA_CHECK_ACCOUNTS:-xiaohao-4,xiaohao-5}
 
+# FB 群采集第三方 API key（fb_group 批次用；缺失时该群采集 FATAL → 批次 failed）
+# key 由部署方在启动 shell 环境提供（.env 已 gitignore，不入库）；daemon 继承该环境
+# （start.sh 的 nohup 子进程天然继承）。缺失时原子 FATAL 是既有行为，本期不新增凭证体系。
+export BRIGHTDATA_API_KEY="${BRIGHTDATA_API_KEY:-}"
+export APIFY_TOKEN="${APIFY_TOKEN:-}"
+
 is_running() { # pidfile
   [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null
 }
 
 start_backend() {
   local pidfile="$PID_DIR/server.pid"
   if is_running "$pidfile"; then
     echo "[跳过] 后端已在运行 (pid $(cat "$pidfile"), :$BACKEND_PORT)"
     return
   fi
diff --git a/platform/web/src/lib/api.ts b/platform/web/src/lib/api.ts
index b04f87f..6f3aaf3 100644
--- a/platform/web/src/lib/api.ts
+++ b/platform/web/src/lib/api.ts
@@ -77,20 +77,22 @@ export interface Task {
 
 export type TaskType =
   | '1688_shop'
   | '1688_company'
   | '1688_contact'
   | 'madeinchina_contact'
   | 'madeinchina_shop'
   | 'yiwugo_search'
   | 'wa_check'
   | 'fb_post'
+  | 'fb_discover'
+  | 'fb_group'
 
 // 采集类参数全量可选键：留空即不传，由 CLI 默认值生效。
 // 批次类型（1688/madeinchina 采集 + wa_check）只读 limit / repeat_interval /
 // accounts，其余 daemon 级参数（workers/proxy/节奏等）已收敛到 daemon 启动，
 // 逐任务覆盖取消（SPEC §3.2 用户可见变化）；旧模板多余字段后端忽略。
 // wa_check 只使用 limit / accounts；旧模板多余字段后端忽略（加载时忽略未知键）。
 export interface TaskParams {
   batch_num?: number
   limit?: number
   max_batches?: number
@@ -110,20 +112,25 @@ export interface TaskParams {
   block_rest_min?: number
   block_rest_max?: number
   use_proxy?: boolean
   headless?: boolean
   auto_solve?: boolean
   retry_failed?: boolean // 仅 1688_contact；已不映射 CLI（build_command 分支已删），表单开关遗留
   // 任务结束后自动重启的间隔（秒）；0 或不传 = 不循环
   repeat_interval?: number
   // wa_check 专用
   accounts?: string[]
+  // fb_discover / fb_group 专用
+  keywords?: string // 换行分隔的搜索原文
+  pages?: number
+  provider?: string
+  posts_per_group?: number
 }
 
 export interface CreateTaskRequest {
   type: TaskType
   params: TaskParams
 }
 
 export interface TaskPreview {
   cmd: string[] | null // 批次类型（含 wa_check）返回 null
   cmdline: string // cmd 拼接的命令行，或批次类型的说明文案
diff --git a/platform/web/src/pages/Tasks.tsx b/platform/web/src/pages/Tasks.tsx
index 0e5abaf..b7ae2df 100644
--- a/platform/web/src/pages/Tasks.tsx
+++ b/platform/web/src/pages/Tasks.tsx
@@ -84,21 +84,21 @@ function batchProgress(task: Task): { done: number; total: number; failed: numbe
   const done = p.done
   if (typeof total !== 'number' || typeof done !== 'number') return null
   const failed = typeof p.failed === 'number' ? (p.failed as number) : 0
   if (total <= 0) return null
   return { done, total, failed }
 }
 
 // P4 批次采集类型（progress 为 work_items 聚合，非 last_line）
 const BATCH_TYPE_NAMES = new Set(['1688_shop', '1688_company', '1688_contact',
                                   'madeinchina_shop', 'madeinchina_contact',
-                                  'wa_check', 'fb_post'])
+                                  'wa_check', 'fb_post', 'fb_discover', 'fb_group'])
 
 function TaskRow({
   task,
   selected,
   onSelect,
   onChanged,
   onShowLogs,
 }: {
   task: Task
   selected: boolean
diff --git a/platform/web/src/pages/tasks/TaskFormDialog.tsx b/platform/web/src/pages/tasks/TaskFormDialog.tsx
index ff08943..90aadd3 100644
--- a/platform/web/src/pages/tasks/TaskFormDialog.tsx
+++ b/platform/web/src/pages/tasks/TaskFormDialog.tsx
@@ -17,20 +17,21 @@ import {
 } from '@/components/ui/collapsible'
 import {
   Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
 } from '@/components/ui/dialog'
 import { Input } from '@/components/ui/input'
 import { Label } from '@/components/ui/label'
 import {
   Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
 } from '@/components/ui/select'
 import { Switch } from '@/components/ui/switch'
+import { Textarea } from '@/components/ui/textarea'
 import { ChevronDown, Save, Terminal, Trash2 } from 'lucide-react'
 import { TASK_TYPE_OPTIONS, taskTypeLabel } from './task-ui'
 
 interface NumField {
   key: string
   label: string
   placeholder: string
   hint?: string
 }
 
@@ -68,20 +69,27 @@ const MISC_NUM_FIELDS: NumField[] = [
   { key: 'repeat_interval', label: '循环间隔（秒）', placeholder: '0 = 不循环，如 1800' },
 ]
 
 const ALL_NUM_KEYS = [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map(
   (f) => f.key,
 )
 
 // 高级区包含的数字键（模板加载命中时自动展开高级区）
 const ADVANCED_NUM_KEYS = [...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS].map((f) => f.key)
 
+// fb_discover 新建时预填的默认关键词矩阵（SPEC §7.4）
+const FB_DISCOVER_DEFAULT_KEYWORDS = `site:facebook.com/groups 外贸 whatsapp
+site:facebook.com/groups 跨境电商 whatsapp
+site:facebook.com/groups china sourcing whatsapp
+site:facebook.com/groups 货代 微信
+site:facebook.com/groups 亚马逊卖家 微信`
+
 interface TaskFormDialogProps {
   open: boolean
   onOpenChange: (open: boolean) => void
   onSaved: () => void
   task?: Task | null // 传入 = 编辑模式（type 只读，回填 params）
 }
 
 export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDialogProps) {
   const editing = task != null
 
@@ -96,38 +104,47 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
   const [submitting, setSubmitting] = useState(false)
 
   // wa_check 专用表单状态
   const [waLimit, setWaLimit] = useState('')
   const [waAccounts, setWaAccounts] = useState<WaAccount[]>([])
   const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
 
   // P4 批次采集专用：limit（contact=条数、shop/company=页数）
   const [batchLimit, setBatchLimit] = useState('')
 
+  // P4 fb_discover 专用
+  const [fbDiscoverKeywords, setFbDiscoverKeywords] = useState('')
+  const [fbDiscoverPages, setFbDiscoverPages] = useState('')
+  // P4 fb_group 专用
+  const [fbGroupProvider, setFbGroupProvider] = useState<'brightdata' | 'apify'>('brightdata')
+  const [fbGroupPostsPerGroup, setFbGroupPostsPerGroup] = useState('')
+
   // 命令预览
   const [preview, setPreview] = useState<TaskPreview | null>(null)
 
   // 任务模板
   const [templates, setTemplates] = useState<TaskTemplate[]>([])
   const [templateSel, setTemplateSel] = useState('')
   const [saveTplOpen, setSaveTplOpen] = useState(false)
   const [tplName, setTplName] = useState('')
   const [savingTpl, setSavingTpl] = useState(false)
   const [tplToDelete, setTplToDelete] = useState<TaskTemplate | null>(null)
   const [deletingTpl, setDeletingTpl] = useState(false)
   const [tplManageOpen, setTplManageOpen] = useState(false)
 
   const isWaCheck = type === 'wa_check'
   // P4 批次采集类型：表单只留 limit + repeat_interval（节奏/代理收敛 daemon 级）
   const isBatch = ['1688_shop', '1688_company', '1688_contact',
                    'madeinchina_shop', 'madeinchina_contact',
                    'fb_post'].includes(type)
+  const isFbDiscover = type === 'fb_discover'
+  const isFbGroup = type === 'fb_group'
 
   const setValue = (key: string, v: string) =>
     setValues((prev) => ({ ...prev, [key]: v }))
 
   // 用一组 params 回填整个表单（编辑初始化 / 模板加载共用）
   const fillFromParams = (p: Record<string, unknown>) => {
     const next: Record<string, string> = {}
     for (const key of ALL_NUM_KEYS) {
       if (typeof p[key] === 'number') next[key] = String(p[key])
     }
@@ -140,20 +157,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     setWaLimit(typeof p.limit === 'number' ? String(p.limit) : '')
     setBatchLimit(typeof p.limit === 'number' ? String(p.limit) : '')
     // wa 表单只保留 limit + accounts：历史任务 params_json 中的旧字段
     // （batch_num/sample_min/… 等）后端忽略，回填时跳过未知键（SPEC C3）
     setSelectedAccounts(
       Array.isArray(p.accounts)
         ? (p.accounts as unknown[]).filter((a): a is string => typeof a === 'string')
         : [],
     )
     if (ADVANCED_NUM_KEYS.some((k) => typeof p[k] === 'number')) setAdvancedOpen(true)
+    // fb_discover / fb_group 回填
+    setFbDiscoverKeywords(typeof p.keywords === 'string' ? p.keywords : '')
+    setFbDiscoverPages(typeof p.pages === 'number' ? String(p.pages) : '')
+    setFbGroupProvider(p.provider === 'apify' ? 'apify' : 'brightdata')
+    setFbGroupPostsPerGroup(typeof p.posts_per_group === 'number' ? String(p.posts_per_group) : '')
   }
 
   // 打开时初始化：编辑模式回填 task.params，新建模式重置为空白默认
   useEffect(() => {
     if (!open) return
     setPreview(null)
     setAdvancedOpen(false)
     setTemplateSel('')
     if (task) {
       setType(task.type as TaskType)
@@ -162,20 +184,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     } else {
       setType('1688_shop')
       setValues({})
       setChannels('')
       setUseProxy(true)
       setHeadless(true)
       setAutoSolve(true)
       setRetryFailed(false)
       setWaLimit('')
       setSelectedAccounts([])
+      setFbDiscoverKeywords(FB_DISCOVER_DEFAULT_KEYWORDS)
+      setFbDiscoverPages('1')
+      setFbGroupProvider('brightdata')
+      setFbGroupPostsPerGroup('50')
+      setBatchLimit('')
     }
     // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [open, task])
 
   // 打开时拉取模板列表
   useEffect(() => {
     if (!open) return
     api.getTaskTemplates()
       .then(setTemplates)
       .catch(() => setTemplates([]))
@@ -211,20 +238,48 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     if (isWaCheck) {
       const params: TaskParams = { accounts: selectedAccounts }
       const limitN = Number(waLimit)
       if (waLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) params.limit = limitN
       // 循环间隔：由模板回填时透传（wa 表单不展示该字段）
       const riRaw = (values.repeat_interval ?? '').trim()
       const riN = Number(riRaw)
       if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
       return params
     }
+    if (isFbDiscover) {
+      const params: TaskParams = {}
+      const kw = fbDiscoverKeywords.trim()
+      if (kw !== '') params.keywords = kw
+      const pagesN = Number(fbDiscoverPages)
+      if (fbDiscoverPages.trim() !== '' && Number.isInteger(pagesN) && pagesN >= 1 && pagesN <= 10) {
+        params.pages = pagesN
+      }
+      const riRaw = (values.repeat_interval ?? '').trim()
+      const riN = Number(riRaw)
+      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
+      return params
+    }
+    if (isFbGroup) {
+      const params: TaskParams = { provider: fbGroupProvider }
+      const ppgN = Number(fbGroupPostsPerGroup)
+      if (fbGroupPostsPerGroup.trim() !== '' && Number.isInteger(ppgN) && ppgN >= 1) {
+        params.posts_per_group = ppgN
+      }
+      const limitN = Number(batchLimit)
+      if (batchLimit.trim() !== '' && Number.isInteger(limitN) && limitN >= 0) {
+        params.limit = limitN
+      }
+      const riRaw = (values.repeat_interval ?? '').trim()
+      const riN = Number(riRaw)
+      if (riRaw !== '' && Number.isInteger(riN) && riN > 0) params.repeat_interval = riN
+      return params
+    }
     const params: TaskParams = { use_proxy: useProxy, headless, auto_solve: autoSolve }
     for (const key of ALL_NUM_KEYS) {
       const raw = (values[key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) continue
       if (key === 'repeat_interval' && n === 0) continue // 0 = 不循环，不传
       ;(params as Record<string, unknown>)[key] = n
     }
     // 后端 channels 为 int（代理通道 id）：整数才提交（Number.isFinite 会放行 '1.5'，后端 int 会 422）
@@ -236,23 +291,25 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     if (retryFailed && type === '1688_contact') params.retry_failed = true
     return params
   }
 
   // 参数签名：内容变化时触发防抖预览
   const paramsKey = useMemo(
     () =>
       JSON.stringify({
         type, values, channels, useProxy, headless, autoSolve, retryFailed,
         waLimit, selectedAccounts,
+        fbDiscoverKeywords, fbDiscoverPages, fbGroupProvider, fbGroupPostsPerGroup,
       }),
     [type, values, channels, useProxy, headless, autoSolve, retryFailed,
-      waLimit, selectedAccounts],
+      waLimit, selectedAccounts,
+      fbDiscoverKeywords, fbDiscoverPages, fbGroupProvider, fbGroupPostsPerGroup],
   )
 
   // 命令预览：防抖 500ms 调 preview 接口，失败静默不阻塞
   useEffect(() => {
     if (!open) return
     const timer = setTimeout(() => {
       api.previewTask({ type, params: buildParams() })
         .then((res) => setPreview(res))
         .catch(() => setPreview(null))
     }, 500)
@@ -275,20 +332,57 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
     if (isWaCheck) {
       if (waLimit.trim() !== '') {
         const n = Number(waLimit)
         if (!Number.isInteger(n) || n < 0) {
           toast.error('查号上限需为不小于 0 的整数（0 = 全部未查）')
           return false
         }
       }
       return true
     }
+    if (isFbDiscover) {
+      // keywords 空 → 警告但不阻塞（后端 enqueue 空→0 幂等，裁定#5）
+      if (fbDiscoverKeywords.trim() === '') {
+        toast.warning('未填写查询词，将使用空关键词（后端幂等跳过）')
+      }
+      if (fbDiscoverPages.trim() !== '') {
+        const n = Number(fbDiscoverPages)
+        if (!Number.isInteger(n) || n < 1 || n > 10) {
+          toast.error('每词页数需为 1-10 的整数')
+          return false
+        }
+      }
+      return true
+    }
+    if (isFbGroup) {
+      // provider 防御校验：Select 已限定，代码级再兜底（裁定#5）
+      const provider = fbGroupProvider as string
+      if (provider !== 'brightdata' && provider !== 'apify') {
+        toast.error('数据来源仅支持 Bright Data 或 Apify')
+        return false
+      }
+      if (fbGroupPostsPerGroup.trim() !== '') {
+        const n = Number(fbGroupPostsPerGroup)
+        if (!Number.isInteger(n) || n < 1) {
+          toast.error('每群帖数上限需为不小于 1 的整数')
+          return false
+        }
+      }
+      if (batchLimit.trim() !== '') {
+        const n = Number(batchLimit)
+        if (!Number.isInteger(n) || n < 0) {
+          toast.error('群数上限需为不小于 0 的整数（0 = 不限）')
+          return false
+        }
+      }
+      return true
+    }
     for (const f of [...BASIC_FIELDS, ...RHYTHM_FIELDS, ...RETRY_FIELDS, ...MISC_NUM_FIELDS]) {
       const raw = (values[f.key] ?? '').trim()
       if (raw === '') continue
       const n = Number(raw)
       if (!Number.isInteger(n) || n < 0) {
         toast.error(`「${f.label}」需为不小于 0 的整数，或留空使用默认值`)
         return false
       }
     }
     const batchNum = Number(values.batch_num)
@@ -552,20 +646,114 @@ export function TaskFormDialog({ open, onOpenChange, onSaved, task }: TaskFormDi
                           {a.name}
                           {a.phone ? `（+${a.phone}）` : ''}
                         </Label>
                       </div>
                     ))}
                   </div>
                 )}
                 <p className="text-xs text-muted-foreground">全不选 = 仅默认账号；多选按批轮换</p>
               </div>
             </>
+          ) : isFbDiscover ? (
+            <>
+              <div className="space-y-2">
+                <Label htmlFor="fb-discover-kw">搜索关键词</Label>
+                <Textarea
+                  id="fb-discover-kw"
+                  className="min-h-24 font-mono text-xs"
+                  value={fbDiscoverKeywords}
+                  placeholder="每行一个查询词"
+                  onChange={(e) => setFbDiscoverKeywords(e.target.value)}
+                />
+                <p className="text-xs text-muted-foreground">
+                  DDG SERP 单 IP 限流（实测约 2 连查即封、约 4 分钟恢复），查询间有节奏冷却，整批约 8-15 分钟跑完
+                </p>
+              </div>
+              <div className="grid grid-cols-2 gap-3">
+                <div className="space-y-2">
+                  <Label htmlFor="fb-discover-pages">每词页数</Label>
+                  <Input
+                    id="fb-discover-pages"
+                    type="number"
+                    min={1}
+                    max={10}
+                    value={fbDiscoverPages}
+                    placeholder="1"
+                    onChange={(e) => setFbDiscoverPages(e.target.value)}
+                  />
+                </div>
+                <div className="space-y-2">
+                  <Label htmlFor="fb-discover-repeat">循环间隔（秒）</Label>
+                  <Input
+                    id="fb-discover-repeat"
+                    type="number"
+                    min={0}
+                    value={values.repeat_interval ?? ''}
+                    placeholder="0 = 不循环"
+                    onChange={(e) => setValue('repeat_interval', e.target.value)}
+                  />
+                </div>
+              </div>
+            </>
+          ) : isFbGroup ? (
+            <>
+              <div className="space-y-2">
+                <Label>数据来源</Label>
+                <Select value={fbGroupProvider} onValueChange={(v) => setFbGroupProvider(v as 'brightdata' | 'apify')}>
+                  <SelectTrigger className="h-8 font-medium">
+                    <SelectValue />
+                  </SelectTrigger>
+                  <SelectContent>
+                    <SelectItem value="brightdata">Bright Data（默认）</SelectItem>
+                    <SelectItem value="apify">Apify</SelectItem>
+                  </SelectContent>
+                </Select>
+              </div>
+              <div className="grid grid-cols-2 gap-3">
+                <div className="space-y-2">
+                  <Label htmlFor="fb-group-ppg">每群帖数上限</Label>
+                  <Input
+                    id="fb-group-ppg"
+                    type="number"
+                    min={1}
+                    value={fbGroupPostsPerGroup}
+                    placeholder="50"
+                    onChange={(e) => setFbGroupPostsPerGroup(e.target.value)}
+                  />
+                </div>
+                <div className="space-y-2">
+                  <Label htmlFor="fb-group-limit">群数上限</Label>
+                  <Input
+                    id="fb-group-limit"
+                    type="number"
+                    min={0}
+                    value={batchLimit}
+                    placeholder="留空 = 不限"
+                    onChange={(e) => setBatchLimit(e.target.value)}
+                  />
+                </div>
+              </div>
+              <div className="space-y-2">
+                <Label htmlFor="fb-group-repeat">循环间隔（秒）</Label>
+                <Input
+                  id="fb-group-repeat"
+                  type="number"
+                  min={0}
+                  value={values.repeat_interval ?? ''}
+                  placeholder="0 = 不循环"
+                  onChange={(e) => setValue('repeat_interval', e.target.value)}
+                />
+              </div>
+              <p className="text-xs text-muted-foreground">
+                Bright Data 免费层 5K 条/月额度；provider key 走环境变量 BRIGHTDATA_API_KEY / APIFY_TOKEN（缺失时该群采集失败）
+              </p>
+            </>
           ) : (
             <>
               <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                 {BASIC_FIELDS.map(renderNumField)}
               </div>
 
               <div className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                 <div>
                   <Label htmlFor="use-proxy" className="cursor-pointer">使用代理</Label>
                   <p className="text-xs text-muted-foreground">通过代理通道发起请求</p>
diff --git a/platform/web/src/pages/tasks/task-ui.tsx b/platform/web/src/pages/tasks/task-ui.tsx
index 32e3f00..b9c84cd 100644
--- a/platform/web/src/pages/tasks/task-ui.tsx
+++ b/platform/web/src/pages/tasks/task-ui.tsx
@@ -71,20 +71,22 @@ export function levelBadge(level: TaskEventLevel) {
 
 export const TASK_TYPE_OPTIONS: { value: TaskType; label: string }[] = [
   { value: '1688_shop', label: '1688 店铺采集' },
   { value: '1688_company', label: '1688 公司采集' },
   { value: '1688_contact', label: '1688 联系方式采集' },
   { value: 'madeinchina_shop', label: '中国制造网 展厅采集' },
   { value: 'madeinchina_contact', label: '中国制造网 联系方式采集' },
   { value: 'yiwugo_search', label: '义乌购搜索' },
   { value: 'wa_check', label: 'WhatsApp 查号' },
   { value: 'fb_post', label: 'Facebook 帖子采集' },
+  { value: 'fb_discover', label: 'Facebook 帖子发现' },
+  { value: 'fb_group', label: 'Facebook 群帖采集' },
 ]
 
 export function taskTypeLabel(type: string): string {
   return TASK_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type
 }
 
 /** worker 标识徽标：同一 worker 恒同色（哈希取色相，明暗主题通用）。 */
 export function workerChip(worker: number | string | undefined | null) {
   if (worker === undefined || worker === null || worker === '') return null
   const s = String(worker)
@@ -137,20 +139,48 @@ export function paramsSummary(task: { type: string; params: Record<string, unkno
   if (task.type === 'wa_check') {
     const parts: string[] = []
     const limit = num('limit')
     if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '全部未查')
     const accs = Array.isArray(p.accounts) ? (p.accounts as unknown[]).filter((a) => typeof a === 'string') : []
     if (accs.length > 0) parts.push(`账号=${accs.join(',')}`)
     if (repeatPart) parts.push(repeatPart)
     return parts.length > 0 ? parts.join(' ') : '默认参数'
   }
 
+  // fb_discover：N 词 × M 页（keywords 按换行拆词计数、空视为 1；pages 缺省 1）
+  if (task.type === 'fb_discover') {
+    const raw = typeof p.keywords === 'string' ? p.keywords : ''
+    const wordCount = raw
+      .split('\n')
+      .map((s) => s.trim())
+      .filter((s) => s.length > 0).length
+    const m = typeof p.pages === 'number' && Number.isFinite(p.pages) ? p.pages : 1
+    const parts: string[] = []
+    parts.push(wordCount > 0 ? `${wordCount} 词 × ${m} 页` : `默认矩阵 × ${m} 页`)
+    if (repeatPart) parts.push(repeatPart)
+    return parts.join(' ')
+  }
+
+  // fb_group：provider + 每群≤N帖 + 群数上限（limit，0=不限）
+  if (task.type === 'fb_group') {
+    const provider = p.provider === 'apify' ? 'Apify' : 'Bright Data'
+    const ppg =
+      typeof p.posts_per_group === 'number' && Number.isFinite(p.posts_per_group)
+        ? p.posts_per_group
+        : 50
+    const limit = num('limit')
+    const parts: string[] = [`provider=${provider}`, `每群≤${ppg}帖`]
+    parts.push(limit !== null && limit > 0 ? `群数上限=${limit}` : '群数不限')
+    if (repeatPart) parts.push(repeatPart)
+    return parts.join(' ')
+  }
+
   // P4 批次采集类型（1688/madeinchina shop/company/contact + fb_post）：
   // 只读 limit（contact=条数、shop/company=页数）+ repeat_interval
   const BATCH_TYPES = new Set(['1688_shop', '1688_company', '1688_contact',
                                'madeinchina_shop', 'madeinchina_contact',
                                'fb_post'])
   if (BATCH_TYPES.has(task.type)) {
     const parts: string[] = []
     const limit = num('limit')
     if (limit !== null) parts.push(limit > 0 ? `上限=${limit}` : '不限量')
     if (repeatPart) parts.push(repeatPart)
