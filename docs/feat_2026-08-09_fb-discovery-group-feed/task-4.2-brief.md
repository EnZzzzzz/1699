# Step 4.2 — task-ui.tsx

> 这是你的需求唯一来源。PLAN Step 4.2 原文 + SPEC §7.2 精确规格抄录如下。

## PLAN Step 4.2 原文（验收以 checkbox 为准）

- [ ] TASK_TYPE_OPTIONS 追加两项（label「Facebook 帖子发现」/「Facebook 群帖采集」）
- [ ] paramsSummary 追加两分支（N 词 × M 页；provider=… 每群≤N帖 群数上限=M）
- 预估 15min；验收：tsc 通过 + 类型标签渲染

## SPEC §7.2 task-ui.tsx（精确规格）

- `TASK_TYPE_OPTIONS` 追加两项：
  - `fb_discover` → label **「Facebook 帖子发现」**
  - `fb_group` → label **「Facebook 群帖采集」**
- `paramsSummary` 追加两分支：
  - `fb_discover` → `N 词 × M 页` + 循环（N=keywords 按换行拆词计数，M=pages 缺省 1）。
  - `fb_group` → `provider=Bright Data|Apify` + `每群≤N帖`（posts_per_group）+
    `群数上限=M`（limit，0=不限）+ 循环。

## 协调者裁定（覆盖 SPEC 未定细节）

1. **paramsSummary 分支位置（重要）**：fb_discover/fb_group 的新分支必须**置于既有
   `BATCH_TYPES` 集合检查之前**（task-ui.tsx 约 147-151 行有一个 `const BATCH_TYPES =
   new Set(['1688_shop', ..., 'fb_post'])` 集合用于「只读 limit+repeat」通用摘要）——
   否则 fb_discover/fb_group 会落入通用 limit 摘要，而不是自定义摘要。实现方式：
   在函数开头（wa_check 分支之后）加 `if (task.type === 'fb_discover') {...}` 与
   `if (task.type === 'fb_group') {...}` 两个独立分支，再走既有 BATCH_TYPES 检查。
   **不要**把 fb_discover/fb_group 加进那个 BATCH_TYPES 集合。
2. **fb_discover 摘要格式**：
   - N = `(task.params.keywords ?? '')` 按 `\n` split 后 strip 过滤空行的数量；
     keywords 缺省/空 → 视为 1 词（`N 词` 显示实际数量，空时显示 1）。
   - M = pages（number 才有效，否则 1）；`M 页`（M=1 时显示「1 页」）。
   - 组合：`2 词 × 1 页`；有循环时追 ` 循环30分钟`（用既有 humanizeSeconds）。
   - 空 keywords（无值）：显示 `默认矩阵 × 1 页`（前端新建时预填默认矩阵，但
     params 可能为空——此时摘要显示「默认矩阵」合理）。
3. **fb_group 摘要格式**：
   - provider：`brightdata` → `Bright Data`；`apify` → `Apify`；缺省/其他 →
     `Bright Data`（后端缺省 brightdata）。
   - `每群≤50帖`（posts_per_group 缺省 50）；`群数上限=10`（limit>0 时）或
     `群数不限`（limit 缺省/0）。
   - 组合：`provider=Bright Data 每群≤50帖 群数不限`；有循环追 ` 循环N`。
4. **复用既有 humanizeSeconds**（task-ui.tsx 内已有，勿重复定义）。
5. **测试/验证**：paramsSummary 是纯函数，但前端无单测基建（现有测试基建若覆盖
   则补断言；否则走 tsc + Step 4.5 手工冒烟）。验收以 tsc 全绿 + Step 4.5 冒烟
   渲染为准。**本 Step 只做 tsc + 自查**（可以用 node 直接跑一下纯函数做快速
   验证，可选——不强求）。
6. **只改 task-ui.tsx**（TASK_TYPE_OPTIONS + paramsSummary），不改其他文件。

## 代码库上下文

- `platform/web/src/pages/tasks/task-ui.tsx`：TASK_TYPE_OPTIONS 在 72-81 行（fb_post
  在 80 行）；paramsSummary 在 130 行起（wa_check 分支 137 行起、BATCH_TYPES 集合
  147-151 行、通用分支其后）；humanizeSeconds 在 ~120 行。
- 类型检查：`cd platform/web && npx tsc -b`。

## Commit 约束

- 只 `git add`：`platform/web/src/pages/tasks/task-ui.tsx`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 4.2 ...`。
