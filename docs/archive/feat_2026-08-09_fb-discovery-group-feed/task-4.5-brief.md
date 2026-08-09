# Step 4.5 — 前端运行时冒烟

> 这是你的需求唯一来源。PLAN Step 4.5 原文 + 环境事实抄录如下。

## PLAN Step 4.5 原文（验收以 checkbox 为准）

- [ ] vite dev 页面：新建 fb_discover/fb_group 任务（表单默认值正确、hint 展示）、
      列表显示类型标签与参数摘要、进度列渲染
- [ ] 冒烟记录写入 ledger.md
- 预估 15min；验收：页面操作全流程可用

## 环境事实（协调者已验证）

1. **vite dev 已在运行**（PID 30015，http://127.0.0.1:3000，HMR 生效——前端代码已
   是 Step 4.1-4.4 最新）；**后端已在运行**（http://127.0.0.1:8765）。直接复用，
   **不要重启**（重启会触发 start.sh 的 nohup 超时坑）。
2. **Playwright 浏览器已缓存**（~/Library/Caches/ms-playwright 有 chromium-1228），
   但 platform/web 无 playwright 包依赖。方案：写临时 Node 脚本（/tmp 下）用
   playwright-core + 系统 chromium 启动无头浏览器操作页面；或用 `npx playwright`
   （需网络下载，慎用）。先检查 `npx playwright --version` 是否可用。
3. **页面路径**：任务列表页 http://127.0.0.1:3000/tasks（若有其他路由，从页面导航
   找「新建任务」按钮）。SSE/API 走 8765（vite proxy 配置应已就绪）。
4. **冒烟要点**（对应 PLAN checkbox）：
   - 打开任务页 → 点新建 → 类型下拉选「Facebook 帖子发现」→ 断言 Textarea 预填
     默认矩阵五行（§7.4）、每词页数默认 1、hint 文案含「DDG SERP 单 IP 限流」；
   - 类型切「Facebook 群帖采集」→ 断言 provider Select 默认 Bright Data（h-8
     font-medium 的视觉属性可经 DOM class 断言）、每群帖数默认 50、hint 含
     「Bright Data 免费层」；
   - 提交 fb_discover 任务（默认矩阵 × 1 页）→ 断言列表出现该任务、类型标签
     「Facebook 帖子发现」、参数摘要「5 词 × 1 页」；
   - 提交 fb_group 任务（默认值）→ 断言列表类型标签「Facebook 群帖采集」、摘要
     含「每群≤50帖」；进度列（batchProgress）渲染不崩（空进度显示占位即可）。
   - 编辑模式回填：点已建 fb_discover 任务编辑 → 断言 keywords/pages 回填正确。
   - 注意：**创建任务会真的入队**（后端真实库）——用后删除任务或接受少量残留
     work_items（fb_discover 默认矩阵会入队 5 条 discover_fb；daemon 可能真去抓
     DDG——冒烟建议用自定义 1 词 keywords 减少副作用，或在冒烟后把任务/批次
     停掉）。报告写明创建了什么、如何清理。
5. **截图**：playwright 脚本可截图保存到 /tmp/fb_smoke_web/，报告引用路径（可选但
   推荐——验收证据）。

## 冒烟记录要求（追加到 ledger.md）

```
## Step 4.5 前端冒烟记录（<日期时间>）
- 环境：vite <pid> :3000、backend :8765 复用
- 操作：<新建两类型任务 → 断言默认值/hint/摘要/进度列 → 编辑回填，关键步骤与输出>
- 创建的任务：<id + type + params>，清理方式：<停掉/删除>
- 截图：<路径>
- 验收判定：<满足/不满足>
```

## 你的工作

1. 用 playwright 脚本（/tmp 下，不入库）驱动页面完成上述冒烟；脚本写清楚断言。
   若 playwright 不可用（无包/无网络），退而用 curl + API 断言 + 页面 HTML/JS 静态
   检查，但报告必须说明方法限制。
2. 冒烟记录追加到 ledger.md 并 commit（只 add ledger.md 与 report，禁止 -A）。
3. 完整证据写入 report（含脚本输出/截图路径/API 响应）。
4. 发现前端代码 bug → 停下 BLOCKED 上报（不自己修——修复循环是主 Agent 的职责）。

工作目录：/Volumes/DataDrive/proj/public/1699

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-4.5-report.md`：
- 冒烟方法与工具、脚本关键片段
- **验收证据**：页面操作步骤与断言输出（默认值/hint/摘要/进度列/编辑回填）、截图路径
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
