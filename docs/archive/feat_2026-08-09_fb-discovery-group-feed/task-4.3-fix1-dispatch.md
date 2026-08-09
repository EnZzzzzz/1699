你正在修复 Step 4.3 的 review 发现（第 1 轮修复）。

## 任务描述

先读你的任务 brief：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-brief.md（需求唯一来源）
再读 implementer 的完整 report：/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.3-report.md

## Review 发现（逐条修复，都在 TaskFormDialog.tsx 的 validate()）

1. **缺失 keywords 空 toast 警告**（TaskFormDialog.tsx:337-344）：validate() 的
   fb_discover 分支只校验了 pages，未对 keywords 为空给出 toast 警告。裁定#5 明确要求
   「keywords 空 → toast 警告但不阻塞（后端幂等）」——即 `toast.warning(...)` 但
   return true。当前静默放行。补上（文案自拟，如「未填写查询词，将使用空关键词
   （后端幂等跳过）」）。
2. **缺失 provider 防御校验**（TaskFormDialog.tsx:347-360）：裁定#5 要求 validate()
   fb_group 分支包含 `provider ∈ {brightdata, apify}` 防御校验。Select UI 已限定，
   但加代码级防御（若非法 → toast.error 并 return false）。

## 你的工作

1. 改 validate() 两处。
2. 验证：cd platform/web && npx tsc -b（全绿）。
3. **把修复报告追加**到 report 文件末尾（改了什么、tsc 输出）。
4. commit（只 add TaskFormDialog.tsx + report；**严禁 git add -A**）。
5. 短契约回复（状态 / commit / 测试总结 / 疑虑 / report 路径）。

工作目录：/Volumes/DataDrive/proj/public/1699。
