# Step 3.2 brief — 文档同步

> 来源：PLAN.md Phase 3 Step 3.2。本文本是你的需求唯一来源。

## 内容

三处文档更新（daemon P0 已完成的对外同步）：

1. **`docs/scheduler-architecture.md` §10 落地路线表**：P0 行标注完成——在「内容」或「验收」单元格追加「✅ 已完成（2026-08-07，实施记录 docs/feat_2026-08-07_fetcher-daemon-p0/）」。不动其他行。
2. **`fetcher/README.md`** CLI 用法段：补 daemon 子命令说明。先读 README 现有 CLI 文档的写法和详略程度，跟随其风格。要点：`python -m fetcher daemon` = 1688 contact 常驻模式（工作项从 work_items 表认领，shops pending 自动补货，空队列挂起等货）；支持 add_common_args 全套参数 + `--queue`（当前仅默认 `crawl_1688_contact`）；`--limit N` 可让 daemon 跑完 N 个后退出（联调用）；**与旧 CLI 同站互斥**（两边启动都会 reset in_progress，同站同跑会互相重置——这是 PLAN 冲突扫描的明文裁定，必须写清楚）。
3. **`AGENTS.md` §1 项目结构**：fetcher/ 段补一句 daemon 模式（一行以内，如「CLI 另有 daemon 常驻模式：1688 contact 从 work_items 表消费，见 docs/scheduler-architecture.md」）。读 AGENTS.md §1 的现有格式，保持对齐。

## 验收

- [ ] 三处更新完成，风格与各自文件既有格式一致
- [ ] README 的互斥约束写明
- [ ] 不含任何代码改动

## 约束

- 只动这三个文件。
- 事实口径以 `docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md` §3.3/§3.4 为准；不确定的行为描述先去读 `fetcher/fetcher/cli/main.py` 的 daemon 分支和 `control/daemon_task.py` 核实，不要凭印象写。
