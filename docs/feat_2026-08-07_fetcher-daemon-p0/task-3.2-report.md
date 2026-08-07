# Step 3.2 report — 文档同步

> 依据 brief：task-3.2-brief.md。只改三处文档，无代码改动。

## 改动明细

### 1. docs/scheduler-architecture.md §10 落地路线表

P0 行的「验收」单元格末尾追加：

```
；✅ 已完成（2026-08-07，实施记录 docs/feat_2026-08-07_fetcher-daemon-p0/）
```

其他行未动。

### 2. fetcher/README.md 快速上手 CLI 段

- 代码块内新增一行：`python -m fetcher daemon --proxy  # 常驻模式：1688 contact 从 work_items 队列持续消费`（置于站点/任务命令之后、注册表说明注释之前）。
- 代码块后新增一段说明，要点：
  - daemon = 1688 contact 常驻模式：从 `work_items` 表认领工作项，shops pending 自动补货入队，队列取空挂起等货而非退出；
  - 支持全部共享网络层参数（`--proxy` / `--workers` / `--headed` 等），另有 `--queue`（P0 仅默认值 `crawl_1688_contact`，不开放选择）；
  - `--limit N` 跑完 N 个后退出，作冒烟/联调收工手段；
  - **互斥约束明文写出**：daemon 与旧 CLI `1688 contact` 同站互斥——两边启动都会把 shops 的 in_progress 重置为 pending（daemon 另回收 work_items 的 claimed 残留），同站同跑会互相重置，同一时刻只跑一个。

### 3. AGENTS.md §1 项目结构

fetcher/ 段的 CLI 行后新增两行（缩进对齐既有块格式）：

```
                  CLI 另有 daemon 常驻模式：1688 contact 从 work_items 表消费（空队列挂起等货，
                  与旧 CLI 同站互斥），见 docs/scheduler-architecture.md
```

（brief 要求「一行以内」，因项目结构块为多行续行格式、单行长行会明显超出对齐宽度，拆成两条续行，内容仍是一句话。）

## 事实核对位置

- `fetcher/fetcher/cli/main.py:51-61`：daemon parser 挂载（与站点平级）、`-n/--num`、`--limit`、`--queue`（默认 `crawl_1688_contact`）、`add_common_args(p_daemon, ...)` 全套共享参数 — 核实 README 参数描述。
- `fetcher/fetcher/cli/main.py:202-243` `_run_daemon`：`get_site("1688")` + `make_task("contact")` 包 `DaemonTaskProxy`；启动时先 `reset_claimed_work_items()` 再 `reset_in_progress()` — 核实「1688 contact」「回收 claimed 残留」。
- `fetcher/fetcher/sites/alibaba1688/contact.py:108`：旧 CLI contact 的 `prepare` 同样调 `reset_in_progress(...)` — 核实「两边启动都会 reset in_progress」的互斥表述。
- SPEC §3.3（shops 状态流、空队列条件变量挂起）、§3.4（CLI 挂载、`--limit` 退出语义）— 口径与 brief 一致，未另行扩展。

## 自查（对照 brief 验收）

- [x] 三处更新完成，风格跟随各文件既有格式（表格单元格追加、README 代码块+说明段、AGENTS 续行缩进）
- [x] README 互斥约束写明（加粗 + 原因说明）
- [x] 不含任何代码改动（git status 仅三个文档文件 + brief/report）

## 疑虑

- AGENTS.md brief 原文要求「一行以内」，实际按项目结构块的既有续行格式拆为两条缩进续行（语义仍一句话）；若严格要物理一行可再合并，但会明显超出块内对齐宽度。
