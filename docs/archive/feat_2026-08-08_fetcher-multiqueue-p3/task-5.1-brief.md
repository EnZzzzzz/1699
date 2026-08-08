# Task 5.1 Brief — 1688 shop/company feeder 任务拆分（复用 Step 4.1 模式）

> 来源：PLAN.md P3-5 Step 5.1 全文 + SPEC §3.7/§3.8 + 主 Agent 裁定。本文件是本次任务的唯一需求来源。

## 目标

把 `Alibaba1688ShopTask`（alibaba1688/shop.py）与 `Alibaba1688CompanyTask`（alibaba1688/company.py）从「进程内 CategoryPool/KeywordPool + cold_start 填池」重构为 **work_items 驱动 feeder**——与 Step 4.1 的 `MadeInChinaShopTask` 重构同模式（可直接参考其重构后代码 madeinchina/shop.py）。company 进度键 `company:` 前缀沿用。

## 背景（SPEC §3.7 feeder 模式，Step 4.1 已落地）

- **类目页工作项**：payload `{"kind":"category","keyword":..,"name":..}`（company 为 `{"kind":"company","keyword":..,"name":..}` 或统一 kind="category" + company: 前缀 keyword——**裁定：统一 kind="category"，company 的 keyword 天然带 "company:" 前缀**（进度表/播种按前缀区分），不需要第二种 kind；discover 同 kind="discover"）
- **page_no 不进 payload**：处理时读 `category_progress.next_page`（单一事实来源）
- **链式续喂**：on_success → advance/exhausted → 未采完 INSERT 下一页 item
- **失败补插**：attempts 耗尽 → `refill_item` 补插同 payload（Step 4.1 已建 Task 基类钩子 + QueueRouter 接线）
- **CLI acquire**：改 `claim_next_eligible([queue], consumer_id)` 与 daemon 同路径

## 规格

### 1. Alibaba1688ShopTask 重构（alibaba1688/shop.py）

**保留**（逐字迁移到 payload 形态）：`fetch` 单页抓取逻辑（mtop 握手、referer 链、_JS_DATA_READY 轮询、_JS_EXTRACT_SHOPS 解析）、`build_search_url`、`SEED_CATEGORIES`、`fetch_homepage_categories`、ZERO_NEW 判定（1688 用 hasMore/空页判 exhausted，无 ZERO_NEW_LIMIT——**裁定：1688 沿用现状 on_success 的 exhausted 判定逻辑，不引入 mic 的零新增保护**）。

**改造**（对照 Step 4.1 mic shop 重构模式）：
- item 形态：payload dict `{"kind","keyword","name"}`；page_no 处理时读 `db.get_category_progress(keyword)["next_page"]`
- `fetch(ctx, item)`：`kind=="category"` → 读 next_page → 现逻辑抓搜索页；`kind=="discover"` → 返回 `ActionResult.success("discover", data={"discover": True})`
- **discover 执行（on_success）**：`kind=="discover"` → 首页类目提取（`fetch_homepage_categories` + SEED_CATEGORIES 兜底）→ **mtop 握手**（`ensure_mtop_token`，SPEC §3.7「discover = 首页类目提取 + mtop 握手」）→ 新类目（不在 category_progress 且无同 keyword pending category item）逐条 INSERT category item → 返回 0 计数
- **on_success（category）**：现状逻辑迁移（start_run/upsert_shops/finish_run 入库 → hasMore/空页 exhausted 或 advance → 未采完 INSERT 下一页 item → stats shops/new/pages）
- **validate**：discover item 检查 discover 键放行（Step 4.1 C1 教训）；category 检查 shops list
- **refill_item**：category 补插同 payload（attempts=0）；discover 补插（幂等由 pending 检查保证）
- **cold_start**：保留纯浏览软着陆（类目提取归 discover；cold_start_before_acquire 保持 True）
- **acquire_item（CLI）**：`claim_next_eligible(["crawl_1688_shop"], consumer_id)` → payload；无货 None
- **prepare（CLI）**：保留打印口径；**启动播种**：`iter_active_categories()`（无拼音过滤——1688 中文/英文关键词都算）逐条插 category item（幂等）+ 1 条 discover item（幂等）
- CategoryPool/after_item 释放逻辑退役

### 2. Alibaba1688CompanyTask 重构（alibaba1688/company.py）

同上模式，差异点：
- 进度键：keyword 带 `"company:"` 前缀（现状沿用）——`get_category_progress("company:xxx")`、播种 `iter_active_categories(prefix="company:")`
- discover：公司搜索的关键词来源——**读现状 cold_start 逻辑**（company.py:234-248：首页类目提取 + mtop 握手，关键字是类目关键词的 company 变体？——以代码为准，把现 cold_start 的提取逻辑迁移到 discover on_success，产出 `company:` 前缀 keyword 的 category item）
- payload：`{"kind":"category","keyword":"company:xxx","name":..}`（kind 统一 category）
- `ip_request_budget=12`、on_success 的 company 落库逻辑（companies 表？——以代码为准迁移）
- **注意**：company 的 shops 落库与 1688 shop 不同（company 采的是公司搜索页）——以现状 on_success 为准逐字迁移

### 3. 复核/回归

- 旧 CLI `python -m fetcher 1688 shop`/`1688 company` 路径保留可用（acquire 走 work_items 队列——与 daemon 同路径）
- 现有 test_alibaba1688 相关测试（如有 CategoryPool 断言）适配或退役

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖（tests/test_1688_feeder.py 或并入既有测试）：

1. **链式续喂**（1688 shop）：category on_success 有 hasMore → advance + INSERT 下一页 item；hasMore=false/空页 → exhausted 不插
2. **discover 产出**（1688 shop）：fetch→validate→on_success 三段式 → 首页类目逐条 INSERT category item（含 mtop 握手调用断言，mock 或注入）；已存在类目不重复
3. **company: 前缀隔离**：company 的 keyword 带前缀，get_category_progress/播种按前缀不混（与 1688 shop 类目互不干扰）
4. **失败补插**：category attempts 耗尽 → refill 同 payload 新 item
5. **幂等播种**：重复 prepare 不产生重复 pending
6. **CLI acquire**：claim_next_eligible([queue]) 认领返回 payload；无货 None
7. **validate discover 放行**（Step 4.1 教训回归）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 468 passed）
- **参考实现**：Step 4.1 重构后的 `fetcher/fetcher/sites/madeinchina/shop.py`（payload 驱动模式：_seed_category_items/_seed_discover_item/_count_pending_by_kind/_insert_work_item/fetch/on_success/refill_item/validate/acquire_item）——直接对照其结构迁移到 1688
- 现状（已读码）：alibaba1688/shop.py（CategoryPool :140 前、task :181-373：cold_start :239 提取+mtop、acquire_item :254、fetch :263、on_success :328、after_item :365 释放池）；company.py（:175-355，company: 前缀、KeywordPool、cold_start :234）；db.py（iter_active_categories(prefix=) 已有——Step 4.2；advance/mark_exhausted/get_category_progress 已有）
- 队列名：`crawl_1688_shop` / `crawl_1688_company`（注册表 Step 5.2 加，本 Step 的 acquire/prepare 用这两个名字）
- **db.py 本 Step 不改**；不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/、docs/feat_2026-08-07_apify-provider-pairing-login/

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/sites/alibaba1688/shop.py`、`fetcher/fetcher/sites/alibaba1688/company.py`、`fetcher/fetcher/control/task.py`（如 refill 需要）、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.1-report.md`
- 工作区有他人未提交改动，**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.1-report.md`：实现摘要、测试列表、TDD 证据、改动文件、自查发现（含 company: 前缀隔离验证结论）
