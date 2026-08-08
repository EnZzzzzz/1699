# Task 4.1 Brief — crawl_mic_contact 接入确认 + mic shop feeder 任务拆分

> 来源：PLAN.md P3-4 Step 4.1 全文 + SPEC §3.7/§3.8/§3.4 + 主 Agent 裁定。本文件是本次任务的唯一需求来源。

## 目标

1. `crawl_mic_contact` 入注册表与 mic contact prepare 的 reset 域过滤——**主 Agent 已核实 Step 3.1 完成**（双队列注册表已含 mic contact；逐 site reset 已做；mic contact prepare 内部 `reset_in_progress(SHOWROOM_DOMAIN_SUFFIX)` 带域过滤）。本 Step 只需**复核确认**（grep 验证），无需改动。
2. **mic shop feeder 任务拆分**（核心交付）：`MadeInChinaShopTask` 从「进程内 CategoryPool + acquire 自选类目」重构为「**work_items 驱动 + 单类目页处理**」——item 处理逻辑可独立于内存池调用（SPEC §3.8：与 daemon 同一代码路径，避免双份流水线）。

## 背景（SPEC §3.7 feeder 模式）

shop 任务源是「进程内 CategoryPool + cold_start 探索式发现 + category_progress 页码表」，任务项自带 page_no。译为 work_items：

- **类目页工作项**：payload `{"kind":"category","keyword":<slug>,"name":<cat_name>,"fmt":"market"|"plain"}`。**page_no 不进 payload**——处理时读 `category_progress.next_page`（单一事实来源；同类目下一页 item 只在上一页成功后插入 → 多消费者不会同页撞车）
- **发现工作项**：payload `{"kind":"discover"}`。执行 = 现 `cold_start` 的类目提取（首页 + 市场导航页 `fetch_market_categories`），新类目（不在 category_progress 且无同 keyword pending item）逐条 INSERT category item
- **链式续喂**：category item `on_success` → `advance_category_page`/`mark_category_exhausted`（含 ZERO_NEW_LIMIT 保护迁移）→ 未采完则 INSERT 下一页 item
- **失败补插**：category item 最终失败（attempts 耗尽）→ 路由层补插同 payload 新 item（attempts=0），保证类目链不死
- 进程内 CategoryPool/ACQUIRE_WAIT_MAX 空转逻辑**退役**（work_items 队列天然解决）

## 规格

### 1. MadeInChinaShopTask 重构（fetcher/sites/madeinchina/shop.py）

**保留**（逐字迁移到 payload 驱动形态）：`fetch`（单类目页抓取 + 子域名提取入库 shops）、`_JS_EXTRACT_SHOWROOMS`、`is_platform_subdomain`、`_slug_fmt` 的 fmt 处理（payload 带 fmt，不再查池）、`on_giveup`/`on_abort`/`summary`/`compose`/`label` 适配 payload 形态、ZERO_NEW_LIMIT 判定。

**改造**：

- `make_stats` 保持 `{"shops","new","pages"}`（contact 无关；QueueRouter.make_stats 会合并）
- **item 形态**：payload dict `{"kind","keyword","name","fmt"}`（category）或 `{"kind":"discover"}`；page_no 处理时读 `db.get_category_progress(keyword)["next_page"]`（无记录=1）
- `fetch(ctx, item)`：`kind=="category"` → 读 next_page → 抓 market 页（现有 fetch 逻辑，item 键改 payload 键：`item["keyword"]`/`item["name"]`/`item["fmt"]`）；`kind=="discover"` → 不抓页面返回特殊结果（或由 cold_start/discover 逻辑处理——见下）
- **discover 执行**：`fetch` 对 discover item 返回 `ActionResult.success("discover", data={"discover": True})` 或单独处理路径——on_success 里 `kind=="discover"` 走类目提取 + INSERT category item（首页+导航页提取，新类目逐条插）。**裁定**：discover 的类目提取逻辑复用现有 `cold_start` 的提取段（`fetch_market_categories` 首页+导航页 + 内置种子兜底），放到 on_success 或独立方法 `_run_discover(ctx)`——选职责清晰处
- **on_success(ctx, item, result)**：
  - `kind=="discover"` → 提取类目 → 对每个新类目（不在 category_progress 且无同 keyword pending category item）INSERT category item（`{"kind","keyword","name","fmt"}`）→ 返回 0 计数（discover 不计入页数）或按现状口径
  - `kind=="category"` → 现状逻辑：shops 入库计数 → ZERO_NEW_LIMIT 零新增判定（streak 计存放哪：**裁定 task 实例内存 dict（slug→streak，沿用现有 zero_new + 锁）**——同类目串行链式下不会并发写，但保留锁防御）→ `advance_category_page(keyword, name, shops_found)` 或连续零新增达阈值 `mark_category_exhausted` → **未采完则 INSERT 下一页 item**（同 payload 新行，attempts=0）
- **失败补插钩子**：Task 基类新增 `refill_item(self, ctx, item) -> None`（默认空实现，CLI 兼容）；MadeInChinaShopTask 实现——`kind=="category"` 且最终失败时 INSERT 同 payload 新 item（attempts=0），discover 不补插（discover 失败可再发？——裁定：discover 也补插一次，幂等由「无同 keyword pending item」保证）
- **acquire_item（CLI 路径）**：改为从 work_items 队列 `crawl_mic_shop` 认领——`db.claim_next_eligible(["crawl_mic_shop"], consumer_id)` → 返回 payload dict（与 daemon router 同路径）；无货返回 None。CategoryPool/ACQUIRE_WAIT_MAX 逻辑删除
- **prepare（CLI 路径）**：保留 get_exhausted_keywords/进度库恢复的打印口径；**启动播种**（与 daemon 启动播种同逻辑，幂等）：① `iter_active_categories()`（Step 4.2 才建？——**本 Step 用现成 `get_active_categories()`** 过渡，Step 4.2 换统一查询）逐条插 category item（已有同 keyword pending item 跳过）；② 插一条 discover item（已有 pending discover 跳过）
- **cold_start**：`cold_start_before_acquire=True` 现状会逛首页填池——重构后类目发现走 discover item，cold_start 可保留为纯软着陆（逛首页不留提取）或退役——**裁定：保留 cold_start 为纯浏览软着陆（不提取类目，提取归 discover）**，`cold_start_before_acquire` 保持 True（行为：新会话先逛首页再认领）

### 2. QueueRouter 失败补插接线（control/queue_router.py）

`release_item(ctx)` 里 `db.release_work_item(item_id)` 返回 `"failed"`（attempts 耗尽）时：调 `self._task_for(ctx).refill_item(ctx, ctx.state.get("item"))`（补插钩子），记日志。Task 基类加 `refill_item` 默认空实现。

### 3. 复核确认（grep 验证，report 记录结论）

- 注册表已含 `crawl_mic_contact`（cli/main.py `_build_registry`）：site="madeinchina"、task=get_site("madeinchina").make_task("contact")、topup 参数化 `.cn.made-in-china.com`
- 启动 reset 已逐 site（`reset_daemon_state` 按 domain_suffix 循环）
- mic contact prepare 的 `reset_in_progress(SHOWROOM_DOMAIN_SUFFIX)` 带域过滤

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖（tests/test_mic_shop_feeder.py 或并入 test_madeinchina.py）：

1. **链式续喂**：category item on_success（有新增店铺）→ category_progress next_page+1 + 新 INSERT 下一页 item（payload 同、attempts=0）
2. **ZERO_NEW_LIMIT 保护**：连续 N 页零新增（streak 计数）→ mark_category_exhausted + 不插下一页
3. **失败补插**：category item attempts 耗尽（release 返回 failed）→ 同 payload 新 item 插入（attempts=0）
4. **discover 产出**：discover on_success → 提取类目（mock fetch_market_categories 或注入）→ 新类目逐条 INSERT category item；已存在类目不重复
5. **幂等播种**：重复 prepare/播种 → 不产生重复 pending item（同 keyword pending 存在时跳过）
6. **CLI acquire**：claim_next_eligible(["crawl_mic_shop"]) 认领返回 payload；无货 None
7. **page_no 运行时读**：fetch 时读 next_page（mock category_progress 不同值 → 抓不同页）
8. **refill_item 基类默认空**（contact task 等无补插）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 447 passed）
- 现状（已读码）：madeinchina/shop.py（CategoryPool :161-217、task :219-471、fetch :350、on_success :398、ZERO_NEW_LIMIT=2、ACQUIRE_WAIT_MAX=600、SEED_CATEGORIES、fetch_market_categories :139）；db.py（get_category_progress/advance_category_page/mark_category_exhausted/get_active_categories 已有）；queue_router.py（release_item 已有，需接 refill）；control/task.py（Task 基类，Step 3.1 已加 budget_for/release_item）
- **db.py 本 Step 不改**（用现成 get_active_categories 过渡；iter_active_categories 是 Step 4.2 的统一查询）
- 不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/、docs/feat_2026-08-07_apify-provider-pairing-login/

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/sites/madeinchina/shop.py`、`fetcher/fetcher/control/queue_router.py`、`fetcher/fetcher/control/task.py`、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md`
- 工作区有他人未提交改动，**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 复核确认结论（§规格 3）写进 report
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md`：实现摘要、测试列表、TDD 证据、复核结论、改动文件、自查发现
