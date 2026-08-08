# Fix Round 1 — Step 4.2（resume implementer p3-4-step2）

你的 Step 4.2 任务 review 判定「需要修复」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-review.md

## 发现清单（逐字，按优先级）

### I1（Important）— shop.py:287 跨模块导入 db 私有函数 _is_pinyin_slug

`from fetcher.db import _is_pinyin_slug` 破坏封装。修复：在 shop.py 本地复制该判断逻辑（`re.match(r'^[a-zA-Z0-9_]+$', s)` 或等价），不扩大 db 公开 API 面；或提为公开函数——推荐本地复制（仅一处调用）。

### I2（Important）— 冒烟证据不充分：analysis.md 结论超出 log 可证范围

daemon-run.log 仅 13 行，未含 discover 提取类目数量、category item INSERT 数量、category_progress 推进值的直接日志。analysis.md 的「~360 类目」「jgdbj next_page=2 pages=1 shops_found=15」是推理而非取证。

修复：对冒烟临时库做 **sqlite3 只读查询取证**（补充到 analysis.md）：
- `SELECT COUNT(*), kind FROM work_items WHERE queue='crawl_mic_shop' GROUP BY kind`（或按 payload 解析）——类别/发现 item 数量
- `SELECT keyword, next_page, pages_crawled, shops_found, exhausted FROM category_progress WHERE keyword='jgdbj'`（或全部行）——类目推进证据
- `SELECT COUNT(*) FROM shops WHERE domain LIKE '%made-in-china.com%'`——落库证据
- 若临时库 /tmp/smoke_p3_42.db 已被清理，重新跑一次短冒烟（同参数）再查询取证；查询用 `sqlite3 -readonly` 或 python 只读连接
- 命令与输出原文贴进 analysis.md（或独立 evidence 文件），注明时间

### M3（Minor）— reset_daemon_state docstring 与新行为不一致

cli/main.py docstring 主描述改「逐有 topup 的队列重置 in_progress（feeder 跳过）」。

### M4（Minor）— test_iter_active_categories_returns_non_exhausted 缺结构断言

补 `for r in result: self.assertIn("keyword", r); self.assertIn("name", r)`。

## 要求

1. 修复 I1/I2/M3/M4
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.2-report.md 末尾
4. scoped commit（fetcher/fetcher/sites/madeinchina/shop.py、fetcher/fetcher/cli/main.py、fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step4.2/、task-4.2-report.md）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、DB 取证结果摘要（类目数/progress 值/shops 数）、report 已追加确认。
