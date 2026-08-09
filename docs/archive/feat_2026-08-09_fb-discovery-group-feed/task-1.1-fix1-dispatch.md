你正在修复 Step 1.1 的 review 发现（第 1 轮修复）。

## 任务描述

先读你的任务 brief：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-brief.md`（它是你的需求唯一来源）

再读 implementer 的完整 report（了解上一版实现与测试情况）：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md`

## Review 发现（逐条修复，一条一条来）

1. **`fetcher/fetcher/db.py` upsert_fb_groups**：`g.get("source") or "ddg"` 会把显式空字符串 `""` 也归为 `"ddg"`。协调者裁定是「缺省 'ddg'」——key 不存在时默认；`or` 同时捕获 None 和空串，语义比需求宽。改为只在 key 不存在或 None 时默认：
   `source = g.get("source") if g.get("source") is not None else "ddg"`（或等价写法）。

2. **`fetcher/tests/test_db_fb_groups.py`**：新增一条测试（或在既有建表幂等测试中补断言）：
   `PRAGMA table_info('fb_posts')` 断言 `status` 列的 `dflt_value` 为 `'pending'`——固化
   save_fb_posts 依赖的 schema 契约，防止未来改 DEFAULT 静默破坏。

3. **`fetcher/tests/test_db_fb_groups.py`** `test_upsert_groups_dedup_keeps_status_and_name`：
   补一行断言：二次 upsert（带 source='fb_post'）后该行 `source` 仍保持首次的 `'ddg'`
   （INSERT OR IGNORE 语义：已存在行全字段不动）。

## 你的工作

1. 按 TDD：先为发现 2、3 写失败测试（RED，亲眼看失败）→ 修代码/补断言 → 转绿。
   发现 1 是代码语义修正：先写一个会失败的测试（显式传 `{"source": ""}` 期望保持空串或
   按裁定语义断言），再改代码。
2. 重跑覆盖改动代码的测试 + 相关回归（`cd fetcher && ../platform/server/.venv/bin/python
   -m unittest discover -s tests -p "test_db_fb_groups.py"` 及 `-p "test_db_fb*.py"` 回归）。
3. **把修复报告追加**到 report 文件末尾：改了什么、跑了哪些覆盖测试、命令、输出。
4. commit 修复（只 add 你的文件：fetcher/fetcher/db.py、fetcher/tests/test_db_fb_groups.py、
   docs/feat_2026-08-09_fb-discovery-group-feed/ 下的 report/brief；**严禁 git add -A**）。
5. 用与首次相同的短契约回复（状态 / commit / 测试总结 / 疑虑 / report 路径）。

工作目录：/Volumes/DataDrive/proj/public/1699。TDD skill 已加载。
