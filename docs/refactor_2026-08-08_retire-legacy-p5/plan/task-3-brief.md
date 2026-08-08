# task-3-brief — Step 2.1 前端同步（wa 表单裁剪 + task-ui/api.ts 清理 + 导入 UI 删除）

> 本文件是你（implementer）需求的唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699
> 模型：deepseek-v4-flash。前置：Step 1.1/1.2 已完成（后端 parse 端点已删、TaskParams 已删
> interval/batch_rest_min/batch_rest_max、build_command retry_failed 分支已删）。

## 项目位置

「1688 采集平台调度器改造 P5」的前端同步 Step。后端契约已冻结（P5-1 完成），前端随之裁剪：
wa_check 表单只保留 limit + accounts（其余节奏字段后端已不消费）、删除「从命令导入」UI（parse
端点已删）、修复 api.ts 与后端的类型失配。

## 改动文件（仅这三个 + 一个后端注释）

### 1. `platform/web/src/lib/api.ts`

- 删 `parseCommand`（约 line 328-332）与 `TaskParseResult` interface（约 line 136-139，含上方注释）
- `TaskParams` 删 3 个字段：`interval`（约 119-120，含注释）、`batch_rest_min`（121）、
  `batch_rest_max`（122）
- `channels?: string` → `channels?: number`（约 line 98，后端是 int）
- 注释同步：
  - 约 line 88-92 的 wa_check 字段说明两行（「wa_check 使用 limit / accounts / sample_min /
    sample_max / batch_num / batch_rest_min / batch_rest_max（interval 为旧参数，向后兼容）」）
    → 改为「wa_check 只使用 limit / accounts；旧模板多余字段后端忽略（加载时忽略未知键）」
  - `TaskPreview` 注释（约 129-131）：「wa_check 为进程内任务，返回 null」已过时——现状
    wa_check 是批次类型，preview 返回 `{"cmd": null, "cmdline": "批次提交：wa_check"}`。
    改为「批次类型（含 wa_check）返回 cmd=null + 批次文案；yiwugo 返回真实命令行」
  - `retry_failed?: boolean` 注释（约 115）：「仅 1688_contact」可保留，但补充「已不映射
    CLI（build_command 分支已删），表单开关遗留」——或按你判断的最准确表述

### 2. `platform/web/src/pages/tasks/TaskFormDialog.tsx`

- **删「从命令导入」**：
  - state：`importOpen`/`importText`/`parsing`（约 115-117）
  - `handleParse`（约 402-411）
  - 打开时重置逻辑里的 `setImportOpen(false)`/`setImportText('')`（约 168-169）
  - JSX 折叠区（约 510-534，Collapsible 整块）
  - 清理不再使用的 import：`Wand2`（lucide）；`ChevronDown` 若高级参数折叠区还在用则保留
  - `applyImportedType` **保留**（模板加载还在用）
  - `ADVANCED_NUM_KEYS` 上方注释「命令导入 / 模板加载命中时…」去掉「命令导入」
- **wa 表单裁剪**（wa_check 分支只保留 limit + accounts）：
  - state：删 `waSampleMin`/`waSampleMax`/`waBatchNum`/`waRestMin`/`waRestMax`（约 101-105）；
    `waLimit`/`waAccounts`/`selectedAccounts` 保留
  - `fillFromParams`（约 153-158）：删 legacyInterval 回退与 5 个 setWa* 调用；`waLimit` 与
    accounts 回填保留（历史任务 params_json 含旧字段 batch_num/sample_min/…/interval，
    回填时忽略这些未知键——SPEC C3：fillFromParams 对未知键保持忽略，勿报错）
  - `buildParams` wa 分支（约 242-251）：删 numOrUndef 块与 sample/batch/rest 提交；
    只留 limit + accounts + repeat_interval 透传
  - `validate` wa 分支（约 318-340）：删 ranges（查号间隔/批间休息）与 waBatchNum 校验；
    只留 waLimit 校验
  - `paramsKey` 依赖数组（约 277-281）：删被裁 state
  - JSX（约 630-735）：删「每批查号数量」「查号间隔下限/上限」「批间休息下限/上限」三个区块
    （含对应 grid 与说明文字），只留「查号上限」+「查号账号」；布局调整使 limit 单列合理
  - 命令预览区注释（约 817「wa_check 返回 cmd=null + 说明文案」）同步为批次文案表述
- **channels 失配修复**（现存 bug：后端 int、前端发 string 会被 pydantic 拒）：
  - buildParams（约 267）：`params.channels = channels.trim()` → `params.channels = Number(channels.trim())`
    （trime 后非空才转 Number，NaN 场景沿用现有「非空才提交」逻辑，可加 isFinite 守卫）
  - fillFromParams（约 145）：`typeof p.channels === 'string'` → `typeof p.channels === 'number'`
    （后端返回 int）

### 3. `platform/web/src/pages/tasks/task-ui.tsx`

- `paramsSummary` wa_check 分支（约 142-156）：删 `interval` 读取与展示、`sample`/`batchNum`/
  `rest` 展示；保留 limit + accounts + repeatPart。文件顶部注释（约 127「wa_check：上限=500
  间隔=2~5s 批=10次」）同步
- 兜底分支（约 185）：删 `if (p.retry_failed === true) parts.push('重试失败')`

### 4. `platform/server/app/api/tasks.py` 一行注释同步（Step 1.2 遗留 Minor，主 Agent 已裁决）

- 约 line 117 `retry_failed: bool | None = None # true 且 1688_contact → --retry-failed`
  → 该行为已删，注释改为「前端 1688_contact 表单开关遗留，不映射 CLI」

## 保留面（不动）

- 模板加载 UI（从模板加载/保存/管理）、handleLoadTemplate
- 批次采集类型表单（batchLimit + repeat_interval）
- yiwugo 等 subprocess 类型的完整表单（BASIC/RHYTHM/RETRY/MISC 字段、代理通道、开关）
- `TaskParams` 里的 batch_num/sample_min/sample_max 字段类型定义（yiwugo 还在用，后端也保留）
- TaskFormDialog 其余逻辑（预览防抖、校验、保存模板等）

## 环境与约束

- 前端目录 `platform/web`；提交前跑 `npx tsc -b` 零错误。
- 活服务：后端 8765（旧代码）、前端 vite dev 3000（LIVE，HMR 会自动热载新代码）。**不要重启或
  停止它们**；走查直接对 3000 进行。
- 禁止碰：fetcher/、scraper/、util/、docs/、后端逻辑（除第 4 条注释）、DESIGN.md 铁律
  （本 Step 是删字段，不新增组件；若动到 JSX 布局，遵守 tokens/间距/圆角规范，参考 DESIGN.md）。

## 走查验收（必须真实打开浏览器）

用 playwright（conda python 已装：`/opt/miniconda3/bin/python`，浏览器已缓存）对
http://127.0.0.1:3000 走查并截图，截图落 plan 目录 `smoke-step2.1/`：

1. 任务管理页 → 新建任务 → 选「WhatsApp 查号」：表单只显示「查号上限」+「查号账号」，
   无每批数量/查号间隔/批间休息字段，无「从命令导入」按钮 → 截图
2. 编辑历史任务（生产库 task id=73，wa_check，params 含 batch_num=200/sample_min=14/
   batch_rest_min=600/accounts=["xiaohao-4"] 等旧字段）：表单正常渲染（limit 空、账号勾选
   xiaohao-4），不报错，不展示已删字段 → 截图
3. 新建任务 → 选 yiwugo_search：完整表单正常（每批数量/取样区间/代理通道等都在）→ 截图
4. 新建任务 → 选 1688_contact（批次类型）：limit + 循环间隔表单正常 → 截图
5. 截图用 playwright 的 page.screenshot，参考 P4 走查（docs/archive/.../smoke-step3.2/）

提示：vite HMR 已热载新代码；若页面异常先确认 3000 无编译错误（curl http://127.0.0.1:3000 或
看 vite 日志 platform/logs/web.log）。编辑历史任务通过任务列表的操作列进入。

## commit

- commit A（前端）：`git add platform/web/src/lib/api.ts platform/web/src/pages/tasks/TaskFormDialog.tsx platform/web/src/pages/tasks/task-ui.tsx`
  message：`refactor(p5): 前端同步——wa 表单裁剪 + 删从命令导入 UI + api.ts 类型失配修复`
- commit B（后端注释）：`git add platform/server/app/api/tasks.py`
  message：`chore(p5): 同步 TaskParams.retry_failed 注释（build_command 分支已删）`
- 走查截图等证据文件先落 plan 目录（docs 提交归 Step 4.1，不要进 commit A/B）

## 验收标准

- [ ] `npx tsc -b` 零错误（platform/web 下）
- [ ] src/ 下 grep `parseCommand\|TaskParseResult\|从命令导入` 零命中
- [ ] src/ 下 grep `batch_rest_min\|batch_rest_max` 零命中；`interval` 仅剩 repeat_interval 相关
- [ ] 走查 4 项截图落 plan 目录（wa 新表单 / 历史任务含旧字段 / yiwugo 全表单 / 批次表单）
- [ ] 后端 tasks.py 注释 commit 单独提交
