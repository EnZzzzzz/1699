# Fix Round 1 — Step 6.1（resume implementer p3-6-step1）

你的 Step 6.1 任务 review 判定「需要修复」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-review.md

## 发现清单（逐字，按优先级）

### C1（Critical）— daemon 无 claim-level 日志，验收证据不符 SPEC §7「日志显示」要求

daemon 默认日志没有认领/终态事件的时间戳输出，report 的全部跨站填充时间序列声明来自 **DB 重建（claimed_at/finished_at 查询 + 推理）**而非日志摘录。SPEC §7 明确「日志显示 madeinchina 冷却登记后、到期前，同 worker 认领并执行 1688 工作项」。

修复（product 可观测性改进，属本 Step 合理范围——SPEC §4.4 观测事件精神）：
- `QueueRouter.acquire_item` 认领成功时加日志：`ctx.log(f"claim queue={item['queue']} item={item['id']} site={item['site']} @<北京时间>")`（或经 log 的既有格式，含时间戳）
- `QueueRouter._finish`（done/failed 终态）与 `release_item`（release/failed）加日志：`ctx.log(f"finish item={id} status={status} @<时间戳>")`
- 日志要经 ctx.log（board/print 路径），行内含可 grep 的关键字（如 `[claim]`/`[finish]`）与时间戳
- TDD：单测断言这些日志行在 acquire/finish/release 时被输出（fake ctx.log 捕获）

### I1（Important）— report 时间事件表混淆 DB 重建与日志证据

修复：重跑冒烟后，report 的时间序列表改为**摘录真实日志行**（`[claim]`/`[finish]` 原文 + 时间戳），标注来源为日志；DB 查询仅作补充佐证（标注为 DB）。

### I2（Important）— 次冒烟 SIGTERM 截断未说明

修复：重跑冒烟用自然收工（--limit N 采满退出），避免 SIGTERM；如必须截断则在 report 说明（信号处理后的退出路径不丢已写数据，但日志可能缺尾行）。

### I3（Important）— mic Cookie 回写次数不一致未解释

修复：report 说明 Cookie 计数含义（回写条数随站点现场签发变化，非固定；主 14 / 次 13 差异正常）。

### C4（Important）— 主冒烟 1054 条 work_items 未做无重复认领检查

修复：对主冒烟 DB 补无重复认领查询（sqlite3 原文：无同 item 重复 claimed_by 冲突/无重复处理），命令+输出贴 report。

### M1/M2（Minor）— WAL 锁定说明 + report 表格上下文

M1：report 说明次冒烟 DB 被 WAL 锁定的原因（daemon 未正常关闭连接即退出——SIGTERM 路径）；M2：表格前补一句「直连 1688 滑块墙必现」的上下文说明。

## 要求

1. 修复 C1（产品日志 + TDD）→ I1/I2/I3/C4/M1/M2（重跑冒烟取证 + report 重写证据节）
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md 末尾（或重写证据节）
4. scoped commit（fetcher/fetcher/control/queue_router.py、fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/、task-6.1-report.md）
5. 环境铁律：--workers 1、直连、临时库 /tmp、+1 席以内

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、新冒烟日志摘录要点（[claim]/[finish] 行样例）、report 已追加确认。
