# Step 5.2 — 全量回归

> 这是你的需求唯一来源。PLAN Step 5.2 原文 + 验收标准抄录如下。

## PLAN Step 5.2 原文（验收以 checkbox 为准）

- [ ] fetcher 全测试组（unittest discover）全绿
- [ ] 平台测试组全绿；`npx tsc -b` 全绿
- 预估 15min；验收：三组全绿（SPEC §10 验收 6）

## SPEC §10 验收 6

全量回归：fetcher 测试全绿（新增原子/Task/DB/CLI 测试 + 既有 FB 测试不动）、平台测试全绿、`npx tsc -b` 通过。

## 协调者裁定

1. **命令**：
   - fetcher：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests`（全量，~30s）
   - 平台：`cd platform/server && .venv/bin/python -m unittest discover -s tests`
   - 前端：`cd platform/web && npx tsc -b`
2. **零改动**：本 Step 不写代码不改文件，纯回归验证。
3. **若有不绿**：记录具体失败（测试名 + 输出），判断是否为本 feature 引入（git bisect 或对比 feature 前基线）——若是本 feature 引入，停下 BLOCKED 上报（修复循环是主 Agent 职责）；若是既有失败（与 feature 无关），记录并继续（report 说明）。
4. **验收**：三组全绿，或 report 记录明确的既有失败清单（非 feature 引入）。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.2-report.md：
- 三组命令与输出（测试数、通过数、耗时）
- 失败清单（如有）+ 归属判断
- ledger.md 追加一行记录

commit：只 add report（+ledger.md 若追加）；禁止 -A。commit message 风格：docs(fb): Step 5.2 ...
