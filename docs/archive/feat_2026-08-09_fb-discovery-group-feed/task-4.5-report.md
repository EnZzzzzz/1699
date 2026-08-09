# Task 4.5 报告 — 前端运行时冒烟（fb_discover / fb_group）

- 时间：2026-08-09 23:03（北京时间）
- 执行者：Step 4.5 implementer
- 状态：**DONE**（18/18 断言通过，无前端代码 bug）

## 1. 冒烟方法与工具

- **环境复用**：vite dev http://127.0.0.1:3000（PID 30015）、backend http://127.0.0.1:8765，
  全程未重启（遵守约束，避免 start.sh nohup 超时坑）。vite proxy `/api` → 8765 验证 200。
- **工具**：playwright-core 1.62.1（npx 缓存 `~/.npm/_npx/e41f203b7505f1fb`）+ 系统缓存
  chromium-1228（`chromium_headless_shell-1228/chrome-headless-shell-mac-arm64`）。
  1.62.1 期望 chromium-1234，缓存无 1234 → 用 `executablePath` 直接指向 1228 headless shell
  启动（跳过 revision 校验，无网络下载）。启动参数 `--no-sandbox --disable-dev-shm-usage`。
- **脚本**：`/tmp/fb_smoke_web_smoke.mjs`（不入库）。断言辅助 `assert()` 计数，失败退出码 1；
  页面 console.error / pageerror 全部记录。

脚本关键片段：

```js
const EXE = process.env.HOME + '/Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell'
const browser = await chromium.launch({ executablePath: EXE, headless: true, args: ['--no-sandbox','--disable-dev-shm-usage'] })
// 表单类型下拉 = dialog 内第 2 个 combobox（第 1 个是「从模板加载」）
const typeSelect = () => dialog().locator('[role=combobox]').nth(1)
const pickType = async (label) => { await typeSelect().click(); await page.getByRole('option', { name: label }).click(); await page.waitForTimeout(150) }
// 创建任务捕获响应拿 task id
const respP = page.waitForResponse((r) => r.url().includes('/api/tasks') && r.request().method() === 'POST', { timeout: 10000 })
await dialog().getByRole('button', { name: '创建任务' }).click()
```

## 2. 验收证据（页面操作步骤与断言输出）

### 步骤 1：打开任务页
`goto /tasks` → 标题「任务管理」可见。截图 `01-tasks-list.png`。

### 步骤 2：新建 fb_discover 默认值
点「新建任务」→ 类型下拉选「Facebook 帖子发现」：

| 断言 | 结果 |
|---|---|
| keywords Textarea 预填默认矩阵 | ✔ 5 行，每行以 `site:facebook.com/groups` 开头 |
| 每词页数默认 1 | ✔ `#fb-discover-pages` value=`1` |
| hint 文案含「DDG SERP 单 IP 限流」 | ✔ |
| 类型 SelectTrigger class | `border-input data-[placeholder]:text-muted-foreground …`（含 h-8 font-medium 由 shadcn 基类提供） |

截图 `02-fb-discover-form.png`。

### 步骤 3：切 fb_group 默认值
类型下拉选「Facebook 群帖采集」：

| 断言 | 结果 |
|---|---|
| provider Select 默认 Bright Data（默认） | ✔ trigger 文案含「Bright Data」 |
| provider SelectTrigger 含 `h-8` + `font-medium` class | ✔ |
| 每群帖数默认 50 | ✔ `#fb-group-ppg` value=`50` |
| hint 文案含「Bright Data 免费层」 | ✔ |

截图 `03-fb-group-form.png`。

### 步骤 4：提交 fb_discover（自定义 1 词 × 1 页）
keywords 改写为 `site:facebook.com/groups 冒烟测试`（1 词，减副作用）→ 创建任务。

- POST /api/tasks → **id=92**，type=`fb_discover`，`{"keywords":"site:facebook.com/groups 冒烟测试","pages":1}`
- 列表行出现，类型标签「Facebook 帖子发现」✔、参数摘要「1 词 × 1 页」✔
- 截图 `04-list-fb-discover.png`

### 步骤 5：提交 fb_group（默认值）
- POST /api/tasks → **id=93**，type=`fb_group`，`{"provider":"brightdata","posts_per_group":50}`
- 列表行类型标签「Facebook 群帖采集」✔、摘要含「provider=Bright Data」「每群≤50帖」「群数不限」✔
- 进度列（batchProgress）：空进度不崩，状态列渲染「排队中」✔
- 截图 `05-list-fb-group.png`

### 步骤 6：编辑回填 fb_discover（id=92）
点行内「编辑」：

| 断言 | 结果 |
|---|---|
| 对话框标题「编辑任务 #92 参数」 | ✔ |
| keywords 回填 `site:facebook.com/groups 冒烟测试` | ✔ |
| pages 回填 `1` | ✔ |
| 编辑模式类型下拉只读（disabled） | ✔ |

截图 `06-edit-backfill.png`。

### 汇总
```
==== RESULT: passed=18 failed=0 ====
```

## 3. 清理

- 两任务创建后均为 `pending`（批次类型入队仅发生在显式 `start`，代码核实
  `api/tasks.py start_task` → `enqueue_batch_for_task`），**未产生任何 work_items**。
- 冒烟后 `DELETE /api/tasks/92`、`DELETE /api/tasks/93` 均 200。
- DB 复核：tasks 总数恢复 12，`work_items WHERE batch_id IN (92,93)` = **0** 残留。

## 4. ledger.md 追加内容

```
## Step 4.5 前端冒烟记录（2026-08-09 23:03:43）
- 环境：vite :3000（PID 30015）、backend :8765 复用（未重启）
- 工具：playwright-core 1.62.1 + 系统缓存 chromium-1228 headless shell（executablePath 直启，
  无网络下载）；脚本 /tmp/fb_smoke_web_smoke.mjs（不入库）
- 操作：打开 /tasks → 新建 fb_discover（断言默认矩阵 5 行、每词页数=1、hint「DDG SERP 单 IP
  限流」）→ 切 fb_group（断言 provider 默认 Bright Data 且 trigger 含 h-8+font-medium、每群
  帖数=50、hint「Bright Data 免费层」）→ 提交自定义 1 词 fb_discover（断言类型标签「Facebook
  帖子发现」+ 摘要「1 词 × 1 页」）→ 提交默认 fb_group（断言标签「Facebook 群帖采集」+ 摘要
  「provider=Bright Data 每群≤50帖 群数不限」+ 状态列排队中渲染不崩）→ 编辑 fb_discover 回填
  （keywords/pages=1 正确、类型只读）。共 18 项断言全部通过（passed=18 failed=0）
- 创建的任务：id=92 fb_discover {keywords:"site:facebook.com/groups 冒烟测试",pages:1}、
  id=93 fb_group {provider:brightdata,posts_per_group:50}——创建即 pending 不入队（批次入队
  仅在显式 start 时发生），冒烟后 DELETE 两任务清理，DB 验证 0 残留 work_items
- 截图：/tmp/fb_smoke_web/01-tasks-list.png ~ 06-edit-backfill.png
- 验收判定：满足（PLAN checkbox 两项均达成）
- 观测：打开 Dialog 时出现 React 19 既存 ref 警告（shadcn Slot 组件，非本 Step 引入，改动前
  文件即存在）
```

## 5. 疑虑 / 观测

1. **React 19 ref 警告（既存，非本次引入）**：打开任一 Dialog 时 console 出现
   `Warning: Function components cannot be given refs … Check the render method of Primitive.button.SlotClone / Primitive.div.Slot`
   —— 来源是 shadcn `dialog.tsx`/`select.tsx`（Slot 组合）与 React 19 的已知兼容性提示；
   这两个文件最近一次改动在旧提交 `a1e5c8a`（P0 骨架期），与 fb_discover/fb_group 分支无关。
   不影响功能，未阻塞；是否治理可留给后续（升级 shadcn 组件或降级 React）。
2. **playwright 版本错配**：本地 playwright-core 仅 1.62.1（期望 chromium-1234），缓存浏览器为
   1228 → 以 executablePath 绕过 revision 校验，冒烟运行正常。若后续维护冒烟脚本建议统一版本。
3. 冒烟数据（id 92/93）已全部清理，无 DB 残留；未触碰既有 12 个任务。

## 6. PLAN checkbox 验收

- [x] vite dev 页面：新建 fb_discover/fb_group 任务（表单默认值正确、hint 展示）、
      列表显示类型标签与参数摘要、进度列渲染
- [x] 冒烟记录写入 ledger.md
- 结论：**页面操作全流程可用**，无前端代码 bug，DONE。
