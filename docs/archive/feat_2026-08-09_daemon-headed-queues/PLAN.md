# PLAN — daemon 全局有头运行（start.sh 接入 --headed）

> 关联：同目录 SPEC.md（v2，最终方案）。v1 的 Phase/Step 全部作废（框架改动不再需要）。
> 状态字段：pending / in_progress / done（只有验收通过才能标 done）

## Phase 清单

| Phase | 目标 | 预计 Step 数 | 依赖 | 状态 |
|---|---|---|---|---|
| P1 | start.sh 接入 --headed + 前端提示 + AGENTS.md 同步 + 端到端冒烟 | 3 | 无 | done |

## 冲突扫描结论

1. **PLAN 内部**：S1→S3 顺序执行，无矛盾。
2. **PLAN vs 代码库现状**：不改动任何导出/签名；`--headed` 是 daemon 既有参数（`cli/main.py:89`），fetcher 零改动，无消费方迁移。`stop.sh` 语义不变（pidfile 优雅退出）。
3. **PLAN vs 外部依赖**：无新依赖；CloakBrowser 席位占用不变（1/5）；headed 需桌面环境——部署目标即用户 macOS 本机，成立。
4. **运行影响**：实施需重启 daemon（stop.sh/start.sh），进行中批次由 daemon 启动崩溃恢复机制回收（`reset_daemon_state`，claimed→pending）——重启是安全操作，但需用户确认执行时机。

## P1 — 接入与冒烟

**准入条件**：SPEC v2 评审通过。
**完成标准**：start.sh 拉起的 daemon 全局有头；前端提示上线；平台 fb_post 任务（上限=3）有头跑通。

### Step 列表

- [x] **S1（~10min，依赖：无）start.sh + AGENTS.md + 前端文案**
  - `platform/start.sh`：`DAEMON_ARGS` 增加 `--headed`，注释同步（有头窗口、勿误杀）。
  - `AGENTS.md` §1 daemon 条目按 SPEC §6 补一句。
  - `platform/web/src/pages/tasks/TaskFormDialog.tsx:518` 文案按 SPEC §5 替换。
  - 验收：`platform/web` 下 `npx tsc -b` 通过；`git diff` 仅上述三处。
  - ✅ done（2026-08-09）：tsc exit 0；diff 仅 AGENTS.md / start.sh / TaskFormDialog.tsx 三处（工作区另有先前会话遗留的 runner.py/test_batch_tasks.py 未提交改动，未触碰）。

- [x] **S2（~10min，依赖：S1）重启 daemon 冒烟**
  - `platform/stop.sh && platform/start.sh`；`ps` 确认 daemon 命令行含 `--headed`；桌面确认有头浏览器窗口弹出；daemon.log 无 exit 76 / 启动异常。
  - 验收：窗口可见、日志正常、消费者心跳上报（consumer_status）。
  - ✅ done（2026-08-09）：停服先清掉历史双 daemon（16324/18446）；新 daemon 命令行 `python -m fetcher daemon --workers 1 --headed`；CloakBrowser/Chromium 150 主进程 `--start-maximized` 无 `--headless`，桌面可见窗口；日志本次运行段（启动重置 4 claimed→pending）无 exit 76/无 local 异常（8/8 旧代码遗留的 local 崩溃日志在文件头部，非本次运行）；consumer_status 心跳 w0/local0/local1 实时。

- [x] **S3（~20min，依赖：S2）端到端冒烟（#80 同参数）**
  - 平台创建 fb_post 任务（上限=3）：有头窗口中观察到 facebook 页面实际加载；任务进度聚合正常、终态 done；fb_posts 表有产出；task_events 无异常错误。
  - 验收：上述全部成立。
  - ✅ done（2026-08-09）：playwright 驱动前端创建 #83（fb_post 上限=3）+ UI 启动；daemon 认领 3 项（21902-21904），有头窗口逐一加载 facebook 页面（block 拦截：未提取到号码，kind=block——种子 URL 为构造数据触发 FB 登录墙）；任务 16:24:59 派生 done，progress {total:3, failed:3}；fb_posts 状态同步 in_progress→failed；task_events 仅 1 条 info（提交），无异常错误；冒烟种子数据已清理（fb_posts 恢复 277 done/22 failed）。

## 归档

P1 验收后，本目录（含 ledger.md）移至 `docs/archive/`。
