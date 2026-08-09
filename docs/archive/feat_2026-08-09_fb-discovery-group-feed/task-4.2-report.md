# Task 4.2 报告 — task-ui.tsx 前端接线

## 结论

**DONE** — 两处改动完成，tsc 全绿，纯函数冒烟测试全过。

## 改了什么

仅改 `platform/web/src/pages/tasks/task-ui.tsx`：

### 1. TASK_TYPE_OPTIONS 追加两项（fb_post 之后）

```ts
{ value: 'fb_post', label: 'Facebook 帖子采集' },
{ value: 'fb_discover', label: 'Facebook 帖子发现' },
{ value: 'fb_group', label: 'Facebook 群帖采集' },
```

### 2. paramsSummary 追加两分支（wa_check 分支之后、BATCH_TYPES 检查之前，裁定 1）

- **fb_discover**：`N 词 × M 页`。
  - N = `p.keywords` 按 `\n` split → trim → 过滤空行后的数量；空 keywords 显示
    `默认矩阵 × M 页`（裁定 2）。
  - M = `p.pages`（number 且有限才生效，否则 1）。
  - 有循环追 `循环X`（复用既有 `repeatPart` / `humanizeSeconds`，裁定 4）。
- **fb_group**：`provider=Bright Data|Apify 每群≤N帖 群数上限=M|群数不限`。
  - provider：`apify` → `Apify`，其余（含缺省）→ `Bright Data`（后端缺省 brightdata）。
  - `每群≤N帖`：posts_per_group 缺省 50。
  - `群数上限=M`（limit>0）或 `群数不限`（limit 缺省/0）。
  - 有循环追 `循环X`。

两个分支均**未**加入 BATCH_TYPES 集合，通用 limit 摘要分支不受影响（fb_post 等
原有类型行为不变）。

## tsc 输出

```
cd platform/web && npx tsc -b
EXIT=0（无输出，全绿）
```

## 自查验证（可选，用 esbuild bundle + React stub 跑纯函数）

```
fb_discover 空           => 默认矩阵 × 1 页
fb_discover 2词1页+循环  => 2 词 × 1 页 循环30分钟
fb_discover 2词3页       => 2 词 × 3 页
fb_discover 1词单行      => 1 词 × 1 页
fb_group 默认            => provider=Bright Data 每群≤50帖 群数不限
fb_group apify+自定义    => provider=Apify 每群≤20帖 群数上限=10
fb_group brightdata+循环 => provider=Bright Data 每群≤50帖 群数不限 循环1分钟
fb_post 对照(通用BATCH分支) => 上限=200   # 确认 fb_discover/fb_group 未落入通用分支
TASK_TYPE_OPTIONS 尾部   => fb_post / fb_discover / fb_group 三项齐全
```

## 改动的文件

- `platform/web/src/pages/tasks/task-ui.tsx`（唯一代码改动，符合裁定 6「只改
  task-ui.tsx」）
- 本 brief / report（docs/ 下 Step 4.2 文档）

## 自查发现 / 疑虑

- 无功能性疑虑。仅两点说明：
  1. 本 Step 为纯字符串/标签逻辑改动，不涉及 DESIGN.md 约束的颜色 token、布局、
     组件样式，故无需走 tokens.css 流程。
  2. 前端无单测基建，冒烟渲染留给 Step 4.5（brief 裁定 5 一致）。
