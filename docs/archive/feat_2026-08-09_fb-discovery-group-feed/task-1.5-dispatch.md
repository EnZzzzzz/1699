你正在执行 Step 1.5（重派）：发现层运行时冒烟（真实 DDG）。

## 任务描述

先读你的任务 brief（需求唯一来源，含精确冒烟步骤与环境事实）：
`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.5-brief.md`

## 上次尝试的教训（已写入 brief，务必遵守）

上次冒烟 BLOCKED：`FETCHER_DB_PATH` 环境变量对 daemon **无效**（`config_from_args` 只读
`--db` 参数，`resolved_db_path()` 回退生产库）。冒烟 daemon 两次启动对生产库执行了
`reset_claimed_work_items`（已止损、生产 daemon 34402 存活自愈、无 item 被误消费）。
**本次必须用 `--db <临时路径>` 参数**；初始化/查询临时 DB 也用 ShopDB 构造参数显式传
同一路径。同机生产 daemon 仍在运行（有头，34402）：你的冒烟 daemon 只跑 discover_fb
单队列 local 消费者，不碰生产队列；但 consumer_status 心跳同写 local0 键会短暂覆盖
生产 daemon 心跳——冒烟尽量快，结束后确认生产 daemon 心跳恢复（它是常驻 10s 心跳，
会自动覆盖回来）。

## 上下文

Phase 1 最后一个 Step（运行时冒烟）。Step 1.1-1.4 已完成（代码全绿）。不起代码，
只做真实运行时验证：起 daemon 单队列 + 手工灌 2 条 work_items → 观察真实 DDG 抓取
落库。发现代码 bug → 停下 BLOCKED 上报，不要自己修代码。

## 开始之前

对步骤/验收/环境有疑问——**现在就问**。

## 你的工作

1. 按 brief 步骤执行（命令输出保留）
2. 验证验收标准（fb_posts 或 fb_groups ≥1 行真实新增；间隔 ≥60s；记录完整）
3. 冒烟记录追加到 ledger.md 并 commit（只 add ledger.md 与 report，禁止 -A）
4. 完整证据写入 report

工作目录：/Volumes/DataDrive/proj/public/1699

## 力不从心时

停下升级（BLOCKED/NEEDS_CONTEXT）。DDG 限流是预期观测（记录即可），不是 BLOCKED；
连续 2 批全 BLOCKED 才按 brief 熔断判定上报。

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.5-report.md`：
- 执行过程与命令输出
- **验收证据**：fb_posts/fb_groups 查询结果（真实行数+内容）、item 状态流转、消费间隔、日志片段
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
