你正在修复 Step 3.1 的 review 发现（第 1 轮修复）。

## 任务描述

先读你的任务 brief：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-brief.md`（需求唯一来源）
再读 implementer 的完整 report：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-3.1-report.md`

## Review 发现（逐条修复）

1. **BATCH_TYPES 新增两条目格式与既有风格不一致**（runner.py 约 65-68 行）：既有 7 条
   全部是多行 dict 格式（`{` 独占首行，每行一个 k-v），新增两条目用了行内紧凑格式。
   改为与 wa_check/fb_post 一致的多行格式：
   ```python
   "fb_discover": {
       "queue": "discover_fb", "site": None,
       "domain_suffix": "", "kind": "fb_discover",
   },
   "fb_group": {
       "queue": "crawl_fb_group", "site": None,
       "domain_suffix": "", "kind": "fb_group",
   },
   ```
   （行为零变化，纯格式；测试应保持全绿。）

## 你的工作

1. 改格式。
2. 重跑覆盖测试：`cd platform/server && .venv/bin/python -m unittest tests.test_batch_tasks`（应全绿）。
3. **把修复报告追加**到 report 文件末尾（改了什么、覆盖测试、命令、输出）。
4. commit（只 add runner.py + report；**严禁 git add -A**）。
5. 短契约回复（状态 / commit / 测试总结 / 疑虑 / report 路径）。

工作目录：/Volumes/DataDrive/proj/public/1699。
