你在 re-review 一个 Step 的第 1 轮修复。之前的 review 提出了发现，implementer 已尝试修复。你的工作是逐条判定发现 + 检查修复 diff——别无其他。

## 任务

读任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-brief.md

## 待验证的发现（上一轮 review 的 Important 发现，逐字抄录）

1. `fetcher/fetcher/db.py`（upsert_fb_groups）：`g.get("source") or "ddg"` 会把显式空字符串 `""` 也归为 `"ddg"`。协调者裁定是「缺省 'ddg'」——key 不存在时默认；`or` 同时捕获 None 和空串，语义比需求宽。建议改为 `g.get("source", "ddg")` 或 `g.get("source") if g.get("source") is not None else "ddg"`。
2. `fetcher/fetcher/db.py`（save_fb_posts）：INSERT 不包含 status 列依赖表 DEFAULT 'pending'，但测试只断言最终值，未断言 fb_posts schema 的 DEFAULT 就是 'pending'。建议测试加 `PRAGMA table_info('fb_posts')` 断言 status 列 dflt_value 为 'pending'。
3. `fetcher/tests/test_db_fb_groups.py` `test_upsert_groups_dedup_keeps_status_and_name`：未断言 source 不变（首次默认 ddg，二次带 source='fb_post' 后应仍为 ddg）。建议加 `self.assertEqual(rows[0]["source"], "ddg")`。

## 修复内容

读 implementer 的 report（修复报告追加在文件末尾）：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md

**Fix base：** b401560（上一轮 review 见过的 head）
**Head：** HEAD
**Diff 文件：** /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-fix1-review.md

只读一次 diff 文件——它包含修复 commit、stat 摘要和带上下文的修复 diff。不要重跑 git 命令。
你的 review 对这个 checkout 是只读的。不得以任何方式改动工作区、index、HEAD 或分支状态。

## 范围

你的范围就是发现清单和修复 diff。逐条判定每个发现。检查修复 diff 本身引入的新问题。**不要**重新 review 修复没碰的代码：如果你注意到完全在修复 diff 之外的问题，报在"范围外观察"下——它不阻塞本 Step，也不延长循环。

## 测试

implementer 已重跑覆盖改动代码的测试并把结果追加到 report 文件。把报告当作未经验证的声称：确认修复报告点名了覆盖测试并展示了输出，对照 diff 验证声称。不要为确认其报告而重跑套件。只有当读代码产生了具体疑问时才跑聚焦测试。

## 输出格式

你的最后一条消息就是报告本身：直接以第一条发现的判定开头。每行都是判定、带 file:line 的发现、或你跑过的检查——不要开场白、不要过程叙述。

### 发现逐条判定
按"待验证的发现"中的顺序，逐条：
- **[发现一句话]** — ADDRESSED | NOT ADDRESSED，附 file:line 证据。"尝试修了"不算解决：那个具体缺陷必须不复存在。

### 修复 diff 中的新破坏
修复本身弄坏或引入的任何问题，带严重度（Critical/Important/Minor）和 file:line。干净则写 "无"。

### 范围外观察
你注意到的完全在修复 diff 之外的问题。不阻塞；主 Agent 会记入 ledger 留给终审。没有则写 "无"。

### 结论
**修复轮：** [全部发现已解决且无新 Critical/Important 破坏 | 仍有未解决发现] —— 列出未解决项。
