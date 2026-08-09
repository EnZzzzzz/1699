# SPEC — daemon 全局有头运行（start.sh 接入 --headed）

> 版本：v2 · 2026-08-09
> **变更记录**：v1 方案为「`--headed-queues` 专属有头消费者」（requires 标记 + ctx 白名单 + Engine headed worker）。评审中用户裁定：1688 等站点无头被拦截风险高，有头应是**通用能力、全部队列生效**。核查代码后发现 daemon 子命令本就已支持全局 `--headed`（`cli/main.py:67` 套 `add_common_args` → :89 定义 → `config_from_args` :131 映射 `headless=not args.headed` → `_run_daemon` :345 消费），v1 的框架改动全部不需要，作废。本版为最终方案。

## 1. 背景与问题

平台批次任务（1688/madeinchina 采集、fb_post 等）由常驻 daemon 消费执行，daemon 以无头模式运行（`start.sh` 的 `DAEMON_ARGS` 未传 `--headed`）。无头浏览器被风控识别的风险高；有头模式下策略层还保留人工过证路径（`strategy/strategies.py:153` `if ctx.headed:`），对 Facebook login wall / checkpoint 等场景是必需入口。需求：**daemon 全局有头运行**。

## 2. 方案

`platform/start.sh` 的 `DAEMON_ARGS` 增加 `--headed`，daemon 内所有浏览器 worker 以有头模式 launch。fetcher 代码零改动。

- headless 是浏览器进程级 launch 参数（`net/browser.py:281`），每 worker 独立 BrowserManager/浏览器进程，全局有头即全部 worker 有头——语义与用户裁定一致。
- 前端不加控件：有头/无头与节奏/代理/并发一样，收敛为 daemon 启动参数，不逐任务下发。

## 3. 行为后果与依据

| 假设 | 依据 | 验证方式 |
|---|---|---|
| daemon 传 `--headed` 后全部浏览器 worker 有头 | 已读码确认链路：main.py:67/89/131/345 → Engine → BrowserManager launch | 冒烟：窗口弹出 |
| CloakBrowser 席位不变（有头/无头都是 1 worker 1 席） | scheduler-architecture §2（按浏览器二进制进程租约） | 冒烟：无 exit 76 |
| 有头窗口出现在桌面（daemon 虽 nohup 后台，GUI 照常显示） | macOS GUI 进程行为 | 冒烟：窗口可见 |
| 有头会话遇风控可人工过证 | `strategies.py:153`；`tests/test_swapip_two_phase.py:251+` | 运行时观察 |

代价记录：桌面出现浏览器窗口（当前 daemon 默认直连 1 worker = 1 个窗口）；有头渲染资源占用略高于无头。用户已裁定接受。

## 4. 范围与非目标

**范围**：`start.sh` DAEMON_ARGS；前端批次表单提示文案一行；`AGENTS.md` daemon 说明同步；重启 daemon + 冒烟。

**非目标**：

- 逐任务/逐队列 headless 切换（如未来需要「部分队列有头」，再立项做 v1 的 `--headed-queues` 机制，设计已存档于本节变更记录）；
- fetcher 框架任何代码改动；
- worker 数、节奏等其他 daemon 参数调整。

## 5. 前端交互形态（唯一确定形态）

不加控件。`TaskFormDialog.tsx:518` 批次分支提示文案由：

> 节奏/代理/并发已收敛到 daemon 启动参数，不再逐任务下发。

改为：

> 节奏/代理/并发/有头模式已收敛到 daemon 启动参数（当前全局有头运行），不再逐任务下发。

## 6. AGENTS.md 同步

§1 项目结构 daemon 条目补一句：daemon 全局有头运行（start.sh DAEMON_ARGS 含 `--headed`，桌面会弹出浏览器窗口，勿当异常进程关闭）。
