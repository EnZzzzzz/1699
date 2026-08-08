# Fix Round 1 — Step 3.1（resume implementer）

你的 Step 3.1 任务 review 判定「需要修复」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-review.md

## 发现清单（逐字，按优先级）

### I1（Important）— Step 1.2 纯函数单测被整段删除（测试资产回归）

重写 test_queue_router.py 时把 Step 1.2 已建立的 eligible_queues / condvar_timeout 纯函数单测整段删掉了，导致：
- eligible_queues 的冷却过滤/资源过滤/到期恢复边缘用例无覆盖
- condvar_timeout 的边界（冷却中 min、不冷却 cap、极小剩余>0）无覆盖

要求：从 git 历史找回 Step 1.2 的纯函数单测（git show ebd16ba 或查看 test_queue_router.py 的旧版本），恢复/并入新 test_queue_router.py，保证边缘用例覆盖不丢。grep 确认 eligible_queues/condvar_timeout 的边界断言存在。

### I2（Important）— TDD #9（reset 逐 site）无对应测试

brief 明确列出「reset 逐 site：两 domain_suffix 的 in_progress 各自重置，其他站点不动」，但实现无对应测试。

要求：新增测试——seed 两个不同 domain_suffix 的 shops 均为 in_progress（如 .1688.com 与 .cn.made-in-china.com），调用 daemon 的 reset 路径（若 reset 逻辑在 _run_daemon 内不便测，提取为可测函数如 `reset_daemon_state(db, registry)`），断言仅指定 domain_suffix 的 shops 被重置、其他站点不动；reset_claimed_work_items 全量语义保留。

### I3（Important）— --queues 校验用硬编码列表而非注册表动态派生

main.py 中 all_queue_names 手写列表与 _build_registry() 重复，P3-4/P3-5 加队列要改两处，违背「注册表结构必须可扩展」。

要求：改为从注册表动态派生——先建全量 registry（无过滤），取所有 spec.queue 做校验/choices，再用 --queues 过滤装配。choices 参数本身也应动态（argparse choices 可传动态列表，在 build_parser 或 daemon 分支处理）。

### M4（Minor）— compose/summary 委托首个 spec 缺注释

queue_router.py compose/summary 委托 `self._specs[0].task`，补一行注释说明「简单方案：委托首个注册 task（多队列下统计口径待后续细化）」。

### M5（Minor）— payload 添加 "id" 键与 spec 定义不一致

acquire_item 返回前 `payload["id"] = item["id"]`。确认旧代码（loop/contact task 等）是否有实际依赖 payload["id"]：若无依赖移除该行；若有，加注释说明具体依赖点。grep 复核 contact task 的 item 访问键集合（P0 SPEC 已确认只依赖 domain/name/url）。

### M6（Minor）— condvar_timeout（单 queue 版）dead code

condvar_timeout 全仓库无调用。删除或加「保留：未来单队列直连模式可能复用」注释——选删除（git 历史可找回），除非有明确未来用途。

## 要求

1. 修复 I1~I3 + M4~M6
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.1-report.md 末尾（每条：改了什么、覆盖测试、命令、输出）
4. scoped commit（fetcher/fetcher/control/queue_router.py、fetcher/fetcher/cli/main.py、fetcher/tests/、task-3.1-report.md 等本次改动文件）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、report 已追加确认。
