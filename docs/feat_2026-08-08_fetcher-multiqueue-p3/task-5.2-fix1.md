# Fix Round 1 — Step 5.2（resume implementer p3-5-step2）

你的 Step 5.2 任务 review 判定「需要修复」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-review.md

## 发现清单（逐字，按优先级）

### I1（Important）— company 队列未冒烟

冒烟只覆盖了 crawl_1688_shop，brief 字面要求「daemon 消费 1688 shop/company 队列」。company 冒烟能捕获仅影响 company task 实例化的注册表装配错误（如 make_task("company") 静默失败/返回错误类型、company: 前缀播种错误）。

修复（二选一，**优先补冒烟**）：
- 补 company daemon 短冒烟：`python -m fetcher daemon --db /tmp/smoke_p3_52c.db --workers 1 --limit 4 -n 1 --queues crawl_1688_company --batch-rest 1 --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2`，raw 输出落 smoke-step5.2/company-run.log；取证 company: 前缀的播种（iter_active_categories(prefix="company:") 运行时证据）+ 认领 + DB 只读取证
- 若环境受限（滑块墙完全无法推进），在 analysis.md 明确记录 trade-off：Step 5.1 的 test_1688_feeder.py 已完整覆盖 make_task("company") + company: 前缀隔离 + 播种逻辑（引用具体测试名），注册表装配无 company 特有故障模式

### I2（Important）— DB 取证缺原始 SQL 命令/输出

analysis.md 只有摘要表，无原始 SQL 命令与输出（Step 4.2 教训：命令+输出原文贴入）。

修复：对冒烟 A/B（及新增 company 冒烟）的临时库，把实际执行的 sqlite3 查询命令与输出原文贴进 analysis.md（如 `sqlite3 /tmp/smoke_p3_52.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status;"` + 原始表格输出；category_progress 行；shops 计数）。注明查询时间。

### M1（Minor）— test_feeder_queues_topup_is_none 范围与名称不符

过滤集合只含两个新 1688 feeder，名称暗示全部 feeder。修复：feeder_names 集合加 "crawl_mic_shop" 断言 len=3，或改名为 test_new_feeder_queues_topup_is_none——选覆盖面更全的方案。

## 要求

1. 修复 I1/I2/M1
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md 末尾
4. scoped commit（fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/、task-5.2-report.md）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、company 冒烟/取证要点、report 已追加确认。
