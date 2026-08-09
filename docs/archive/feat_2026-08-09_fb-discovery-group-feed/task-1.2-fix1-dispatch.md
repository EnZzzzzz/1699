你正在修复 Step 1.2 的 review 发现（第 1 轮修复）。

## 任务描述

先读你的任务 brief：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-brief.md`（需求唯一来源）
再读 implementer 的完整 report：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.2-report.md`

## Review 发现（逐条修复）

1. **`fetcher/fetcher/atoms/facebook_discover.py`（约 L151-155）**：`float(params.get("sample_min") or MIN_SAMPLE_FLOOR)`、`sample_max`、`int(params.get("timeout") or 30)` 使用 `or` 做缺省值判断，会吞掉显式传入的 `0`（`0 or default` → default）。虽然后续 `max(…, MIN_SAMPLE_FLOOR)` 会纠正到 60，但这是 Python falsy-or-default 反模式。统一改为显式 None 判断（与 L147 page 的处理方式一致）：`raw = params.get("sample_min"); sample_min = float(raw) if raw is not None else MIN_SAMPLE_FLOOR`（timeout 同理：`raw is not None else 30`）。改后语义：显式传 0 时 sample_min 被 floor 抬到 60（不变）、timeout=0 保持 0（int 0 是合法超时？——若 0 无意义可加 max(1, …)，但以不改行为为准，仅修 or 反模式）。

## 你的工作

1. 先写一个会失败的测试捕获 bug（显式传 `{"sample_min": 0}` / `{"timeout": 0}` 时断言行为——设计什么断言能区分 or 反模式与 None 判断；若无法区分（因为 floor 会掩盖），则写明 RED 依据或补一个直接测参数解析的断言）。按 TDD 走。
2. 修代码。
3. 重跑覆盖改动代码的测试 + 回归（`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_facebook_discover.py"` 及 `-p "test_facebook*.py"`）。
4. **把修复报告追加**到 report 文件末尾（改了什么、覆盖测试、命令、输出）。
5. commit（只 add 你的文件；**严禁 git add -A**）。
6. 短契约回复（状态 / commit / 测试总结 / 疑虑 / report 路径）。

工作目录：/Volumes/DataDrive/proj/public/1699。TDD skill 已加载。
