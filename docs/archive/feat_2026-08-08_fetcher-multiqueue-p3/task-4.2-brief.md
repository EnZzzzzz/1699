# Task 4.2 Brief — iter_active_categories 统一查询 + crawl_mic_shop 入注册表 + feeder 冒烟

> 来源：PLAN.md P3-4 Step 4.2 全文 + SPEC §3.7/§5 + 主 Agent 裁定。本文件是本次任务的唯一需求来源。

## 目标

1. `db.py` 新增统一查询 `iter_active_categories(prefix="")`（SPEC §3.7：启动播种用；mic 沿用纯拼音 slug 过滤、company 用 `company:` 前缀——本 Step 先落地 mic 场景与前缀参数化，company 用法 Step 5.2 接）
2. 注册表加 `crawl_mic_shop`（feeder 队列，topup=None）
3. **feeder 冒烟**：临时库播种后 daemon 消费类目页 item，category_progress 推进、shops 落库；日志落 plan 目录

## 规格

### 1. iter_active_categories（fetcher/db.py）

```python
def iter_active_categories(self, prefix: str = "") -> list[dict]:
    """返回未采完的类目（启动播种用，幂等）。

    prefix 非空 → 只返回 keyword 以 prefix 开头的行（如 "company:"）。
    prefix 为空 → 返回全部未采完类目；mic 的纯拼音 slug 过滤由调用方
    按需做（与 get_active_categories 同口径）或本查询不做过滤。
    返回 [{"keyword","name"}]，按 id 排序。
    """
```

- 语义：`WHERE exhausted=0 [AND keyword LIKE prefix+'%'] ORDER BY id`
- **get_active_categories 退役或改造**：现状 `get_active_categories()`（mic 专用纯拼音过滤）改为调用 `iter_active_categories()` + `_is_pinyin_slug` 过滤（或保留别名），report 说明选择；grep 确认全部调用方（madeinchina/shop.py prepare、测试）迁移
- 现有测试适配（test_madeinchina.py 等如有 get_active_categories 断言）

### 2. crawl_mic_shop 入注册表（fetcher/cli/main.py `_build_registry`）

新增第 3 条队列：

```python
QueueSpec(queue="crawl_mic_shop", site="madeinchina",
          task=get_site("madeinchina").make_task("shop"),
          topup=None,           # feeder 类队列无补货
          domain_suffix="",     # 不参与 in_progress reset（shop 任务不标 in_progress）
          requires={"channel", "browser"})
```

- **启动 reset 精确化**：`reset_daemon_state` 只对 `topup is not None` 的队列做 `reset_in_progress(domain_suffix)`（feeder 队列跳过——它不产生 in_progress shops；现状是逐 spec 全循环，改成按 topup 过滤，防误动）
- daemon 启动播种：mic shop 的 `prepare`（Step 4.1 已实现 `_seed_category_items`/`_seed_discover_item` 幂等播种，用 `get_active_categories`）→ 本 Step 切到 `iter_active_categories`（拼音过滤沿用）
- `--queues` choices 自动含 crawl_mic_shop（从注册表动态派生，Step 3.1 已实现）

### 3. feeder 冒烟（验收证据，随跑随写）

环境铁律：--workers 1、直连、临时库 /tmp、+1 席以内；mic dummy cookie（madeinchina:direct 桶 1 条）避免 ensure_site 直连报错。

```
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_42.db --workers 1 --limit 8 -n 1 \
  --queues crawl_mic_shop --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
  > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/daemon-run.log 2>&1
```

取证要点（analysis.md）：
1. **启动播种**：daemon 启动日志/DB 显示 discover item 播种（category_progress 空库时）；若库中有存量未采完类目 → category item 播种
2. **discover 执行**：类目提取（首页+导航页）→ 新类目 INSERT category item
3. **类目页消费**：category item 认领 → market 页抓取 → category_progress next_page 推进 / shops 落库（或按环境失败如实记录）
4. **链式续喂**：on_success 后下一页 item 插入（如有成功页）
5. mic 网络/滑块环境噪声如实记录，取结构证据（播种→认领→progress 读写路径走通）即可，不硬求抓取成功
- 冒烟日志写 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/`（命令 + raw + analysis md，随跑随写）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖：

1. **iter_active_categories 基本**：未采完类目返回、exhausted 排除、按 id 排序
2. **prefix 过滤**：prefix="company:" 只返回 company: 前缀行；prefix="" 全部
3. **拼音过滤迁移**：get_active_categories（或等价）经 iter_active_categories + _is_pinyin_slug 后行为与现状一致（回归断言）
4. **reset 只对 topup 队列**：feeder 队列（topup=None）不触发 reset_in_progress（模拟含 in_progress 的 shop 行不被误重置）
5. **注册表含 crawl_mic_shop**：_build_registry 或 CLI 装配测试断言 3 条队列 + choices
6. **幂等播种**（回归）：重复播种不产生重复 pending item

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 463 passed）
- 现状（已读码）：db.py `get_active_categories`（:556-565，纯拼音过滤）、`_is_pinyin_slug`（:69）、`get_exhausted_keywords`、`advance_category_page`/`mark_category_exhausted`；cli/main.py `_build_registry`（Step 3.1，2 条队列）+ `reset_daemon_state`（逐 spec 循环 reset_in_progress）；madeinchina/shop.py（Step 4.1 重构完成，prepare 播种用 get_active_categories）
- Step 4.1 的 M3 deferred：fmt=x2 播种局限——本 Step 不改 category_progress 表（加 fmt 列需另行裁定，超出本 Step 范围），记录即可
- 不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/、docs/feat_2026-08-07_apify-provider-pairing-login/

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/db.py`、`fetcher/fetcher/cli/main.py`、`fetcher/fetcher/sites/madeinchina/shop.py`（如播种切 iter_active_categories）、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/`、`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md`
- 工作区有他人未提交改动，**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 冒烟证据落 smoke-step4.2/（播种→discover→类目页消费→progress 推进 路径走通的结构证据）
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md`：实现摘要、测试列表、TDD 证据、冒烟取证、改动文件、自查发现
