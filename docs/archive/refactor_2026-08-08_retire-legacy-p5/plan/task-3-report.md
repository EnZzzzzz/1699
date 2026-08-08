# task-3-report — Step 2.1 前端同步（wa 表单裁剪 + task-ui/api.ts 清理 + 导入 UI 删除）

> 状态：DONE。改动 4 个文件、2 个 commit（前端 + 后端注释分开），tsc 零错误，grep 零残留，
> playwright 真实浏览器走查 4 项截图全部通过。

## 1. 改了什么

### 1.1 `platform/web/src/lib/api.ts`
- 删 `parseCommand` 方法与 `TaskParseResult` interface（含「命令解析结果」注释块）
- `TaskParams` 删 3 个字段：`interval`（含旧参数注释）、`batch_rest_min`、`batch_rest_max`
- `channels?: string` → `channels?: number`（后端为 int）
- 注释同步：
  - wa_check 字段说明 →「wa_check 只使用 limit / accounts；旧模板多余字段后端忽略（加载时忽略未知键）」
  - `TaskPreview` 注释 →「批次类型（含 wa_check）返回 cmd=null + 批次文案；yiwugo 返回真实命令行」
  - `retry_failed` 注释补充「已不映射 CLI（build_command 分支已删），表单开关遗留」

### 1.2 `platform/web/src/pages/tasks/TaskFormDialog.tsx`
- 删「从命令导入」整链路：state（importOpen/importText/parsing）、handleParse、打开重置逻辑、
  JSX 折叠区（Collapsible 整块）；清理 import：`Wand2`、`Textarea`（仅导入区使用）；`ChevronDown` 保留
  （高级参数折叠区仍用）；`applyImportedType` 保留（模板加载用），注释去掉「导入」字样
- wa 表单裁剪：删 waSampleMin/waSampleMax/waBatchNum/waRestMin/waRestMax 5 个 state 及
  fillFromParams/buildParams/validate/paramsKey/JSX 中全部对应逻辑；只留 limit + accounts +
  repeat_interval 透传；JSX 改为 limit 单列（`max-w-xs`）+ 账号区
- fillFromParams 对历史任务旧字段（batch_num/sample_min/…）保持忽略（SPEC C3），不报错
- channels 失配修复：`fillFromParams` 判 `typeof p.channels === 'number'`（后端返回 int）；
  `buildParams` 非空才 `Number()` 提交，NaN 丢弃（isFinite 守卫）
- 命令预览区注释同步为「批次类型（含 wa_check）返回 cmd=null + 批次文案」

### 1.3 `platform/web/src/pages/tasks/task-ui.tsx`
- `paramsSummary` wa_check 分支删 interval/sample/batchNum/rest 读取与展示，只留 limit + accounts +
  repeatPart；连带删除不再使用的 `range()` 辅助函数
- 兜底分支删 `if (p.retry_failed === true) parts.push('重试失败')`
- 顶部注释同步为「wa_check：上限=500 账号=xiaohao-1；批次类型：上限=200 循环30分钟」

### 1.4 `platform/server/app/api/tasks.py`（一行注释，Step 1.2 遗留 Minor）
- `retry_failed` 注释「true 且 1688_contact → --retry-failed」→「前端 1688_contact 表单开关遗留，
  不映射 CLI」

### 保留面（未动）
- 模板加载/保存/管理 UI 与 handleLoadTemplate
- 批次采集类型表单（batchLimit + repeat_interval）
- yiwugo 等 subprocess 完整表单（BASIC/RHYTHM/RETRY/MISC、代理通道、开关）
- `TaskParams` 中 batch_num/sample_min/sample_max 类型定义（yiwugo 仍用）

## 2. tsc 输出

```
platform/web 下 npx tsc -b → exit=0，零错误（改动后共跑 3 次，均 0）
```

## 3. grep 自查（src/ 下）

| 模式 | 结果 |
|---|---|
| `parseCommand\|TaskParseResult\|从命令导入` | 零命中 |
| `batch_rest_min\|batch_rest_max` | 零命中 |
| `interval`（排除 repeat_interval） | 零命中（仅剩 repeat_interval 相关） |

## 4. 走查证据（playwright，真实浏览器 http://127.0.0.1:3000，截图落 plan/smoke-step2.1/）

| # | 场景 | 结果 | 截图 |
|---|---|---|---|
| 1 | 新建 → WhatsApp 查号：仅「查号上限」+「查号账号」，无每批数量/查号间隔/批间休息/从命令导入 | PASS | `smoke-step2.1/1-wa-new-form.png` |
| 2 | 编辑历史任务 #73（wa_check，params 含 batch_num=200/sample_min=14/batch_rest_min=600/accounts=["xiaohao-4"]）：表单正常渲染（limit 空、xiaohao-4 勾选），无报错，不展示已删字段 | PASS | `smoke-step2.1/2-wa-edit-task73.png` |
| 3 | 新建 → yiwugo_search（展开高级参数）：每批数量/取样区间/代理通道等全在 | PASS | `smoke-step2.1/3-yiwugo-full-form.png` |
| 4 | 新建 → 1688_contact（批次类型）：采集上限 + 循环间隔，无高级参数 | PASS | `smoke-step2.1/4-batch-1688-contact.png` |

走查脚本：`plan/smoke-step2.1/walkthrough.py`（可重跑）。脚本内断言覆盖：
字段存在/缺失（body 文本）、limit 输入值为空、xiaohao-4 复选框勾选态。

## 5. commits

- `b9ee35d` refactor(p5): 前端同步——wa 表单裁剪 + 删从命令导入 UI + api.ts 类型失配修复
  （3 个前端文件）
- `63e758d` chore(p5): 同步 TaskParams.retry_failed 注释（build_command 分支已删）
  （tasks.py 单文件）

截图/脚本等证据未进 commit（docs 提交归 Step 4.1）。

## 6. 疑虑

- 无阻塞性疑虑。两点观察：
  1. vite HMR 日志有一条「Could not Fast Refresh (TASK_TYPE_OPTIONS export incompatible)」，
     属 vite 对非组件导出的已知警告，走查用全新页面加载，已确认新代码生效。
  2. 走查中未验证「保存 wa_check 任务后 preview 返回批次文案」这一细节（预览区注释已同步，
     后端 P5-1 已确认返回 `{"cmd": null, "cmdline": "批次提交：wa_check"}`，见 task-2-smoke.txt）。
