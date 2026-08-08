# Fix Round 1 — Step 1.3（resume implementer）

你的 Step 1.3 任务 review 判定「需要修复」。reviewer 报告：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.3-review.md

## 发现清单（逐字，按优先级）

### F1（Important）— 冒烟证据缺口：让出型节奏冷却未在真实 daemon 运行中触发

冒烟因首 item 滑块墙失败 + max_consecutive_fail=1 abort，在任何节奏冷却执行前退出。「单队列行为等价」的运行时证据缺失。

要求二选一（本环境直连滑块墙近乎必现，A 不可行时应选 B）：
- A. 用能走到成功路径的参数重跑冒烟（直连环境基本不可行，不做强求）
- B. **补一个成功路径的集成测试**（推荐）：仿 tests/test_control_loop.py 的假基建模式（FakePage/MockBrowserManager/fake fetch OK），用 CrawlLoop + DaemonTaskProxy 跑 2 个成功 item，断言：
  1. item1 完成后让出型 sample_interval 登记 site 键
  2. 下一个 item 的认领发生在冷却到期之后（时间戳间隔落在 sample_min~max 区间，即等待确实发生在 acquire 的 condvar 而非 loop 内）
  3. 全程无 loop 内 wait 痕迹（fake ctx 记录 wait 调用次数，让出型调用点不应触发 ctx.wait）
- 冒烟报告（task-1.3-report.md）补一句明确说明：直连滑块墙下节奏冷却未在真实 daemon 触发，运行时等价性由该集成测试 + 结构证据支撑（不夸大）

### F2（Important）— brief 要求的跨文件注释检查未记录

brief §3 要求检查 core/context.py:113（cooldown_until 注释）与 strategies.py SwapIP「冷却例外」注释中是否有过时「P3 重议」引用。请实际检查：
- 有需同步的 → 同步更新
- 已是最新 → 在 report 记录「已核实无残留」（不能不做检查）
- 改动范围仅限这两处注释本身，不要扩大

### F3（Important）— 测试缺 negative 断言

test_cooldown.py 的 test_three_rhythm_sites_pass_yield_true 只断言三处节奏点传 yield_=True，未验证 launch_backoff 与策略冷却保持 yield_=False。补断言：by_reason 中 launch_backoff 的调用（如有）不得传 yield_=True；策略冷却路径（如可构造）同样。

### F4（Minor）— smoke-analysis.md 参数与 brief 建议不一致未解释

实际命令用了 --limit 2 -n 1 --batch-rest 10 等更小参数。在 smoke-analysis.md 补一句话说明参数调整理由（小参数快速收工、避免滑块墙长耗）。

### F5（Minor）— 让出型调用点后的死分支加注释

loop.py 三处 `if self._cooldown(..., yield_=True): return self.stats` 的 return 分支不可达（yield_=True 恒返回 False）。加一行注释说明「yield_=True 恒返回 False，stop 由 acquire_item 的 condvar 处理」。

### F6（Minor）— smoke-analysis.md 推测性声明改写

「若为原地型…会有至少 5s+ 的额外等待」是推测（sample_interval 未在 daemon 触发过）。改写为条件式表述或删除。

## 要求

1. 修复 F1~F6（F1 选 B 方案：集成测试 + report 如实说明）
2. 为 F1 的新集成测试遵守 TDD（先看失败再转绿；该测试首次跑会失败因为等待位置不对）
3. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
4. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-1.3-report.md 末尾（每条发现：改了什么、覆盖测试、命令、输出）
5. scoped commit（fetcher/fetcher/control/loop.py、fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step1.3/、task-1.3-report.md）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、report 已追加确认。
