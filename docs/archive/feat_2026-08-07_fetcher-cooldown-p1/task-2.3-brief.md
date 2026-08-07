# Step 2.3 brief — 迁移单测

> 来源：PLAN.md Phase 2 Step 2.3。本文本是你的需求唯一来源。

## 范围修正（主 Agent 裁定，避免重复覆盖）

PLAN 原列 5 用例中的 ①（策略 cooldown 区间 + 零等待）和 ②（分布参数一致）**已在 Step 2.1 完成**（`fetcher/tests/test_cooldown_contract.py` 新增 7 用例，含 or 短路、封顶、缺省取参、零等待断言）。本 Step 只做 loop 侧的 ③④⑤。

## 内容

新增 `fetcher/tests/test_cooldown.py`（基建参照 `fetcher/tests/test_control_loop.py` 的 FakeBrowser/可编程 fetch 和 `test_daemon_task.py` 的联跑模式）：

1. **chokepoint 单测**：`_cooldown(seconds, reason)` 写入 `ctx.cooldown_until[reason]`（值 ≈ time.time()+seconds）；等待期间置 stop → 立即返回 True（远小于 seconds）；正常路径返回 False。倒计时/静默两条展示路径各覆盖一次（`prefix` 传/不传）。
2. **`_process_item` 策略冷却集成**：仿 test_daemon_task.py 用例 5 的 CrawlLoop 联跑——假 task 第一次 fetch 返回 blocked、假策略返回 `StepResult(True, cooldown=t)`（t 用小值或可注入），断言：loop 经 `_cooldown` 执行了等待（monkeypatch `_cooldown` 计时或 spy reason=f"strategy:{name}"）、随后重试 fetch、终态正确；再覆盖「冷却中被 stop 中断 → return 'stop' 终局」分支。
3. **4 处等待点触发**：小参数配置（batch_num=1、batch_rest=小值、rest_every=1、sample_min/max 小值）联跑，spy `_cooldown` 的 reason 序列，断言 batch_rest / sample_interval / periodic_rest 都经 chokepoint 触发且时长落在公式区间；launch_backoff 路径（首次 launch 失败一次）如构造代价高可只做 reason 级断言，report 说明。

## 验收

- [ ] 3 组用例全绿（防假阳性：至少一轮定向破坏证据，如破坏 cooldown_until 写入或中断检查，看对应用例变红）
- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归
- [ ] 测试验证真实行为（真实 threading.Event/临时 sqlite/spy，不 mock 被测的 _cooldown 本身——spy 记录参数但调用真实实现）

## 约束

- 只新增 `fetcher/tests/test_cooldown.py`；不改 loop.py / strategies.py（发现接口不可测的硬伤 → NEEDS_CONTEXT 上报）。
- 先读 `fetcher/fetcher/control/loop.py`（_cooldown 在 :108-122 一带，4 处等待点 :145-146 / :208-210 / :218 / :257，_process_item 消费点 :405-413）再写测试。
