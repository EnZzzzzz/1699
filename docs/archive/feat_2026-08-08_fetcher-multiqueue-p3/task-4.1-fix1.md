# Fix Round 1 — Step 4.1（resume implementer p3-4-step1）

你的 Step 4.1 任务 review 判定「需要修复」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-review.md

## 发现清单（逐字，按优先级）

### C1（Critical）— validate 拒绝 discover，生产路径封死

MadeInChinaShopTask.validate 检查 `isinstance((result.data or {}).get("shops"), list)`；discover item 的 fetch 返回 `{"discover": True}`（无 shops 键）→ validate 返回 False → CrawlLoop 判 scenario=EMPTY → 策略链 → on_giveup → _finish("failed")。**on_success 永远不会被调用，类目提取（_on_discover_success）永远不执行**——discover 是类目发现的唯一入口，封死后 feeder 只能靠播种存量类目续命。

修复：validate 对 discover item 放行：
```python
def validate(self, ctx, item, result):
    if item.get("kind") == "discover":
        return isinstance((result.data or {}).get("discover"), bool)
    return isinstance((result.data or {}).get("shops"), list)
```

### I2（Important）— discover 测试绕过 validate 直接调 on_success

DiscoverOutputTest 全部 4 个测试直接 `self.task.on_success(ctx, payload, ok_result(...))`，未走 fetch→validate→on_success 真实三段式——这是 C1 漏检的原因。

修复：至少一个 discover 测试走完整三段式（fetch → validate → on_success），并断言类目 item 被产出；建议该测试在修复前先 RED（validate 拒绝 discover → 断言失败）。

### M3（Minor）— _seed_category_items fmt 硬编码 "x2"

get_active_categories 不含 fmt 字段，播种一律 "x2"，plain 体系类目（jgdbj 等）会拼错 URL → fetch 失败 → attempts 耗尽 → refill 同 payload 继续错 → 循环。**已知局限记录**：本 Step 不改 db.py，短期接受 x2 默认 + discover 会纠正（discover 从页面提取带 fmt）；在 report 与代码注释记录此局限，Step 4.2 若可行再议（如 category_progress 加 fmt 列需另行裁定）。同时可考虑：refill 补插时若连续失败可放弃补插（防无限循环）——评估后决定是否加防护并记录。

### M4（Minor）— _seed_discover_item 内联 SQL 与 _count_pending_category 风格不一致

抽取 `_count_pending_by_kind(db, kind)` 统一，或接受现状并注释。选轻量方案。

### M5（Minor）— _insert_work_item 导入私有符号 _now

改内联 `datetime.now().strftime("%Y-%m-%d %H:%M:%S")` 或 SQLite `datetime('now','localtime')`，不导入 db 私有符号。

## 要求

1. 修复 C1/I2/M3/M4/M5
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-4.1-report.md 末尾（每条：改了什么、覆盖测试、命令、输出）
4. scoped commit（fetcher/fetcher/sites/madeinchina/shop.py、fetcher/tests/、task-4.1-report.md 等）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、report 已追加确认。
