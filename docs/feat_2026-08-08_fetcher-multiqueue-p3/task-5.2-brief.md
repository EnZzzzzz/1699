# Task 5.2 Brief — crawl_1688_shop/company 入注册表 + feeder 冒烟 + 旧 CLI 等价确认

> 来源：PLAN.md P3-5 Step 5.2 全文 + SPEC §3.7/§5。本文件是本次任务的唯一需求来源。

## 目标

1. 注册表加 `crawl_1688_shop` + `crawl_1688_company`（feeder 队列，topup=None）——注册表至此 5 条全齐
2. 启动播种验证（iter_active_categories 1688 变体已在 Step 4.2 落地：prefix="" 无过滤、prefix="company:" 支持）
3. **冒烟**：daemon 消费 1688 shop/company 队列（直连滑块墙环境取结构证据：播种→认领→progress 读写路径走通）
4. **旧 CLI 等价确认**：`1688 shop --workers 1` 直连冒烟（acquire 走 work_items 队列后行为正常）

## 规格

### 1. 注册表装配（fetcher/cli/main.py `_build_registry`）

新增第 4、5 条队列：

```python
QueueSpec(queue="crawl_1688_shop", site="1688",
          task=get_site("1688").make_task("shop"),
          topup=None, domain_suffix="", requires={"channel", "browser"}),
QueueSpec(queue="crawl_1688_company", site="1688",
          task=get_site("1688").make_task("company"),
          topup=None, domain_suffix="", requires={"channel", "browser"}),
```

- 注册表共 5 条：crawl_1688_contact / crawl_mic_contact / crawl_mic_shop / crawl_1688_shop / crawl_1688_company（默认 `--queues` 全量 = 5 条）
- reset_daemon_state 对 topup=None 队列跳过（Step 4.2 已精确化，无需改）
- `--queues` choices 自动含新队列（动态派生，已有）
- policies 装配：1688 一个 Policy（已有）

### 2. 冒烟（验收证据，随跑随写）

环境铁律：--workers 1、直连、临时库 /tmp、+1 席以内；直连 1688 滑块墙近乎必现是环境噪声，取结构证据。

**冒烟 A（daemon 1688 shop）**：
```
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_52.db --workers 1 --limit 6 -n 1 \
  --queues crawl_1688_shop --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
  > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/shop-run.log 2>&1
```

取证要点（analysis.md）：
1. **启动播种**：discover item 播种（空进度库）；有存量未采完类目 → category item 播种
2. **discover 执行**：首页类目提取 + mtop 握手 → 新类目 INSERT category item（滑块墙可能挡首页——如实记录）
3. **类目页消费**：category item 认领 → offer_search 抓取 → progress 推进/落库（或按环境失败）
4. **DB 只读取证**（同 Step 4.2 教训）：work_items 计数、category_progress 行、shops 落库数——命令与输出原文贴 analysis.md

**冒烟 B（旧 CLI 等价）**：
```
cd fetcher
python -m fetcher 1688 shop --db /tmp/smoke_p3_52b.db --workers 1 --limit 2 -n 1
```
- 确认 CLI 路径 acquire 从 work_items 队列认领正常（播种→认领→处理），行为与 daemon 同路径；滑块墙环境取结构证据（播种/认领/落库路径走通）

冒烟日志写 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/`（命令 + raw + analysis md + DB 取证，随跑随写）。

## TDD 要求

至少覆盖（注册表装配层，tests/test_cli.py 或 test_queue_router.py）：

1. **注册表 5 条队列**：_build_registry 装配断言（含 1688 shop/company，topup=None）
2. **--queues choices 含 5 键** + 默认全量
3. **company 播种前缀**：iter_active_categories(prefix="company:") 播种 company 类目、crawl_1688_shop 播种不带前缀（隔离回归）
4. **reset 跳过 feeder**（回归）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 509 passed）
- 现状（已读码）：cli/main.py `_build_registry`（Step 3.1 起 2 条 + Step 4.2 加 crawl_mic_shop = 3 条）；alibaba1688/shop.py + company.py（Step 5.1 重构完成，prepare 播种 iter_active_categories）；db.py iter_active_categories（Step 4.2，prefix 参数化）
- 冒烟临时库 1688 shop 需要 1688:direct Cookie（库内有现成 165 条，ensure_site 直连可用）；不需要 dummy cookie（1688 桶有货）
- 不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/、docs/feat_2026-08-07_apify-provider-pairing-login/

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/cli/main.py`（如注册表）、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/`、`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md`
- 工作区有他人未提交改动，**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 冒烟证据落 smoke-step5.2/（播种→discover→类目页消费→progress 读写路径走通的结构证据 + DB 取证 + 旧 CLI 等价确认）
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md`：实现摘要、测试列表、TDD 证据、冒烟取证、改动文件、自查发现
