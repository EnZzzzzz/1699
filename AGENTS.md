# AGENTS.md — 1688 采集平台开发约定

> 本文件是面向 AI 编码 agent 的项目级指令。改代码前先读本文件；**改前端前必须读 [DESIGN.md](DESIGN.md)**（设计规范唯一文字来源，本文件只做摘要与强制引用）。

## 1. 项目结构

```
fetcher/          采集框架（Python 包，可独立安装）：
                  核心层 core/（ActionResult/Outcome/WorkerContext）· 原子层 atoms/（Atom 协议）
                  网络层 net/ · 判断层 detect/ · 策略层 strategy/ · 站点插件 sites/
                  CLI：python -m fetcher 1688 shop|contact|company / yiwugo search / taobao search
                  vendor/wa-check/：内置 Node/Baileys CLI（WhatsApp 查号协议实现）
platform/         管理系统（前后端分离）
  server/         FastAPI 后端（端口 8765）：app/api/ REST + SSE · app/runner.py 任务监督器
                  app/wa_tasks.py（wa_check 进程内执行器）· app/wa_login.py（WhatsApp 扫码登录）
  web/            React 18 + Vite + TS + Tailwind + shadcn/ui 前端（端口 3000，vite dev 有 HMR）
  start.sh        一键启动后端+前端；stop.sh 停止
.cache/1688.db    SQLite 主库（WAL 模式）：shops / contacts / tasks / task_events /
                  providers / proxy_channels / task_templates
scraper/ util/    旧版脚本，**只读参考，禁止修改**（新代码一律进 fetcher/ 或 platform/）
docs/             flow-architecture.md（fetcher 框架设计）、service-architecture.md（旧方案，存档）
```

## 2. 必读文档（按改动范围）

| 改动范围 | 必读 |
|---|---|
| `platform/web` 任何文件 | **[DESIGN.md](DESIGN.md)**（设计规范唯一来源，新增页面/组件前先读） |
| `fetcher/` 框架或原子 | `docs/flow-architecture.md`（Atom 契约、分层职责） |
| 任务系统 / runner | `platform/server/app/runner.py` 头部注释（subprocess 与进程内两类模型） |
| 数据库访问 | 见下方 §4 数据库约定 |

## 3. 设计规范摘要（完整约束以 DESIGN.md 为准）

**改 `platform/web` 前必须逐条对照 DESIGN.md，以下是最容易被违反的铁律：**

- **颜色 Token 唯一来源** `src/styles/tokens.css`：禁止在组件里散落硬编码色值（如 `#fff`、`rgb(...)`）；新增颜色走「tokens.css 加 token → tailwind.config.js 映射」两步，`:root` 与 `.dark` 两组 token 必须成对新增。
- **Select 与按钮并排**：`SelectTrigger` 必须 `h-8` + 显式 `font-medium`（默认 `font-normal` 会与按钮不齐）；长文案 trigger（如「每页 20 条」）**不要写死小宽度**，用 `w-fit` 自适应避免箭头压住文字；列表项文案与 trigger 一致。
- **按钮**：工具栏/分页条内统一 `variant="outline" size="sm"`；主操作才 `default`，危险操作 `destructive`。
- **状态徽标**：成功态用 `border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400`；同一状态全局同色（参考 `ShopsTab.shopStatusBadge`、`data/ContactsTab.tsx` 的 waBadge）。
- **页面骨架**：`PageHeader` → 筛选工具栏（`flex flex-wrap items-center gap-4`）→ 内容 → 分页。
- **页面状态**：一律用 `components/PageState.tsx` 的 LoadingState / ErrorState / EmptyState；Toast 全局只挂一次（Layout 的 Toaster），页内不重复挂。
- **表格分页**：表格外层 `rounded-lg border border-border`，数值列 `text-right`；分页统一 `PaginationBar`（`pages/data/shared.tsx`），左侧页码信息+每页条数选择器，右侧翻页按钮+跳页；时间戳用 `showTime` 直接展示，不做时区换算。
- **排版**：页面标题 `text-xl font-semibold`、描述 `text-sm text-muted-foreground`（PageHeader）；正文/表格/表单 `text-sm`；辅助信息 `text-muted-foreground` / `text-xs`。
- **圆角/阴影**：圆角以 `--radius: 0.625rem` 为基准（sm=-4px、md=-2px、lg=基准、xl=+4px）；阴影仅 `shadow-xs` 为基准微阴影，弹层 `shadow-md`。

## 4. 后端与数据库约定

- 时间戳一律为**北京时间字符串**（`YYYY-MM-DD HH:MM:SS`），**不要再做 +8 偏移**（库里已是北京时区）。
- SQLite 为 WAL 模式、爬虫可能正在写库：读连接用 `app.db.connect()`（只读，禁写）；写一律**短事务 + `PRAGMA busy_timeout = 30000`**。
- 新增列/表走 `app.db.migrate()` 幂等迁移；涉及可能缺列的场景要**防御性探测**（参考 `api/data.py` 的 `PRAGMA table_info` 探测模式）。
- `wa_registered` 语义：`1`=已注册、`0`=未注册、`NULL`=未查（等价 `wa_checked_at IS NULL`）。
- 改后端代码后 uvicorn **不会自动 reload**，需重启才生效（重启见 `platform/start.sh`/`stop.sh`；注意 pidfile 记录的是父进程，杀端口占用进程时按实际监听 pid）。

## 5. 任务系统（两类执行模型，新增任务类型时二选一）

- **subprocess 类**：`TASK_COMMANDS` 注册类型 → `build_command()` 拼 fetcher CLI → Popen，输出泵逐行写 task_events。适合已有 fetcher CLI 子命令的任务。
- **进程内类**：`IN_PROCESS_TYPES` 注册（如 `wa_check`）→ `_start_in_process` 在线程跑执行器（`wa_tasks.run`），`threading.Event` 协作式停止。适合数据在平台 DB、需分批写回的任务。
- 任务终态：`pending / running / done / failed / stopped`；停止先置 `stop_requested=1`；`repeat_interval>0` 走循环重启（Timer）。
- 新增任务类型需同步：`runner.py` 注册 + `api/tasks.py` 的 `TaskParams` 字段 + 前端 `TaskFormDialog.tsx` 表单分支 + `task-ui.tsx` 的 `TASK_TYPE_OPTIONS`。

## 6. 通用代码约定

- 类名合并一律用 `cn()`（`@/lib/utils`）；注释用中文，文件顶部一行注释说明模块职责。
- 前端提交前跑 `npx tsc -b`（`platform/web` 下）；Python 改动保持 `fetcher` 分层不引入重依赖。
- 不动 `scraper/`、`util/` 旧脚本；新能力进 `fetcher/`（框架侧）或 `platform/`（平台侧）。
- fetcher 原子只「做一件事并报告 Outcome」，不做重试/换 IP 等决策（决策在策略层/上层执行器）。
