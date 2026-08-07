# Step 2.2 brief — DaemonTaskProxy 单测

> 来源：PLAN.md Phase 2 Step 2.2。本文本是你的需求唯一来源。

## 内容

新增 `fetcher/tests/test_daemon_task.py`，测试 Step 2.1 产出的 `fetcher/fetcher/control/daemon_task.py` 的 `DaemonTaskProxy`。基建参照 `fetcher/tests/test_control_loop.py`（FakeBrowser/FakeContext）和 `fetcher/tests/test_contact_task.py`（临时 sqlite）。

**注意一处计划更新**（Step 2.1 已裁定并评审通过）：work_item 终态不落 `after_item`，改挂 `on_success`（→done）和 `on_giveup`（→failed）——因为 `after_item(ctx, item)` 拿不到处置结果。下面用例 ④ 按此验收。

用例：

1. **有货直取**：预置 work_items pending 行 → `acquire_item(ctx)` 返回 dict，含 `id` + `domain`/`name`/`url` 三键（name/url 允许 None 但键在）；该行状态变 claimed、claimed_by=`w{wid}`。
2. **空队列自动补货**：shops 有 pending、work_items 为空 → acquire_item 自动 top-up 后返回；shops 对应行变 in_progress。
3. **stop 退出**：队列空且无法补货（shops 也空）→ stop Event 置位后 acquire_item 在注入的小超时内返回 None（monkeypatch 模块级 `_WAIT_TIMEOUT` 或用 proxy 提供的注入点，先读 daemon_task.py 确认可注入方式）。
4. **终态钩子**：模拟 loop 调用 `on_success(ctx, item, result)` → 对应 work_item 变 done；`on_giveup(ctx, item, reason, kind)` → failed（result_json/reason 落库）；重复 finish 幂等（pop 语义，不误伤其他 item）。
5. **CrawlLoop 联跑**：仿 test_control_loop.py 的集成方式，proxy 包一个假 inner task（可编程 fetch），跑完 N 项后队列空、stop 置位，loop 正常退出且 stats/终态正确；两个 worker 线程共享一个 proxy 实例时不串 item（各拿各的）。

## 验收

- [ ] 5 个用例全绿（先红后绿：针对每个用例断言的行为，先有失败证据——对新测试文件，可对「未实现的断言路径」做临时破坏式验证或至少展示初次运行的真实失败；若所有测试一次通过，在 report 说明你如何确认测试不是假阳性，例如临时改坏被测代码看测试变红）
- [ ] 用例验证真实行为（真实临时 sqlite、真实线程/条件变量），不 mock 被测对象本身
- [ ] 全量 `cd fetcher && python -m pytest tests -x -q` 无回归
- [ ] 测试输出干净（无多余 warning/噪音）

## 约束

- 只新增 `fetcher/tests/test_daemon_task.py`；不改 daemon_task.py（若发现接口不可测的硬伤，停下以 NEEDS_CONTEXT 上报，不擅自改实现）。
- 先读 `fetcher/fetcher/control/daemon_task.py` 确认注入点（db_factory、_WAIT_TIMEOUT 等），再读 test_control_loop.py 的基建，然后写测试。
