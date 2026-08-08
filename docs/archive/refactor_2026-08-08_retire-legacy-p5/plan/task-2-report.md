# task-2-report — Step 1.2 cmdparse + 死字段删除

> implementer 完成报告。需求来源：同目录 `task-2-brief.md`。分支：`refactor/retire-legacy-p5`。

## 一、实现了什么（删除清单逐项）

| # | 删除项 | 位置 | 状态 |
|---|---|---|---|
| 1 | `cmdparse.py` 整个文件（169 行） | `platform/server/app/cmdparse.py` | ✅ git rm，已删 |
| 2a | `CommandParse` pydantic 模型 | `app/api/tasks.py`（原约 171-174） | ✅ 已删 |
| 2b | `@router.post("/tasks/parse")` 端点 `parse_task_command`（含函数内 `from app.cmdparse import ...` 延迟导入） | `app/api/tasks.py`（原约 175-186） | ✅ 已删 |
| 2c | `TaskParams` 三字段：`interval`（含两行注释）、`batch_rest_min`、`batch_rest_max` | `app/api/tasks.py`（原约 118-122） | ✅ 已删 |
| 3a | `build_command` 死分支 `if task_type == "1688_contact" and params.get("retry_failed") is True: cmd.append("--retry-failed")` | `app/runner.py`（原约 142-143） | ✅ 已删 |
| 3b | docstring 对应行「retry_failed=true 且 1688_contact→--retry-failed；」 | `app/runner.py`（原约 120） | ✅ 已删 |

**保留面核验（未动）**：`/tasks/preview` 批次分支（BATCH_TYPE_NAMES）与 yiwugo build_command 分支均保留；
`TaskParams.retry_failed` 字段保留（前端 1688_contact 表单开关在用，Step 2.1 处理）；batch_num/sample_min/sample_max/
accounts/limit/repeat_interval 等字段未动；runner Timer 全套、subprocess 机械、批次/sweeper 全套未动。

## 二、测试输出

聚焦测试（`-k "task or preview or runner"`）：`25 passed, 31 deselected in 0.28s`

全量测试（`platform/server/tests/`，基线 56 passed）：

```
======================== 56 passed, 1 warning in 0.37s =========================
```

净变化零（无测试依赖 cmdparse/死字段，与验收预期一致）。唯一 warning 为既有
StarletteDeprecationWarning（httpx/testclient），与本次改动无关。

## 三、冒烟 curl 输出（临时 uvicorn 8766 + /tmp 库副本）

证据文件：`plan/task-2-smoke.txt`（完整原文），摘要如下：

```
[1] 批次分支 1688_contact  limit=100
    {"cmd":null,"cmdline":"批次提交：crawl_1688_contact，100 条"}   HTTP 200
[2] yiwugo build_command 分支  limit=50
    {"cmd":[".../.venv/bin/python","-m","fetcher","yiwugo","search","--limit","50"],
     "cmdline":"python -m fetcher yiwugo search --limit 50"}        HTTP 200
[3] 对照组 wa_check（brief 预期 422）
    {"cmd":null,"cmdline":"批次提交：wa_check"}                     HTTP 200
[4] 补充对照：未知类型 not_a_type
    {"detail":"未知任务类型 'not_a_type'，可选: [...]"}             HTTP 422
```

临时实例已按实际监听 pid 杀掉，8766 端口已释放；生产库 `.cache/1688.db` 未写、8765 活服务未动。

### 冒烟与 brief 预期的两处偏差（均非缺陷，记录在案）

1. **[1] 队列名**：brief 内联预期写「crawl_1688，100 条」，代码实际队列名为 `crawl_1688_contact`
   （`runner.py BATCH_TYPES["1688_contact"]["queue"]`）。批次分支行为（cmd:null + 批次描述 + limit）完全符合预期，
   只是 brief 对队列名写得简化了。
2. **[3] wa_check 预期 422 未出现**：brief 写「wa_check 现走 build_command 会 422」，但 Step 1.1 之后
   `wa_check` 已注册进 `BATCH_TYPES`（runner.py:57），preview 走批次分支返回 200 `批次提交：wa_check`。
   这恰好证明 wa_check 已彻底脱离 build_command 旧路径，行为变化比 brief 预期更彻底；「记录即可非缺陷」，
   此处如实记录。422 路径由 [4] 未知类型对照验证仍工作正常。

## 四、改动文件

```
D platform/server/app/cmdparse.py        （删除，169 行）
M platform/server/app/api/tasks.py       （-21 行：3 字段 + CommandParse + /tasks/parse 端点）
M platform/server/app/runner.py          （-3 行：死分支 + docstring 行）
```

仅 commit 本 Step 涉及文件（scoped add，含 docs/ 下 SPEC/brief/smoke 证据按 ledger 惯例随附）。

## 五、自查结果（验收标准逐条）

- [x] 平台 pytest 全绿：56 passed（基线持平）
- [x] `app/` grep `cmdparse\|parse_command\|CommandParse\|/tasks/parse` 零命中
- [x] `app/` grep `batch_rest_min\|batch_rest_max` 零命中；`interval` 仅剩 preserved 的
      Timer/sweeper 局部变量（读 `repeat_interval`，如 `_next_restart_at`、`_schedule_restart`），
      非死字段 `TaskParams.interval`，属保留面（runner Timer 全套）
- [x] `runner.py` 无 `retry_failed` 残留；`tasks.py` 的 `TaskParams.retry_failed` 字段保留（预期）
- [x] 临时 uvicorn 冒烟三组 curl 输出落 `plan/task-2-smoke.txt`

## 六、疑虑

1. `TaskParams.retry_failed` 字段（tasks.py 117 行）注释仍写「true 且 1688_contact → --retry-failed」，
   该行为已随 build_command 死分支删除。字段本身按 brief 保留（前端在用），注释轻微过期——
   属 Step 2.1（前端表单开关退役）后一并清理的范畴，本 Step 照单未动。
2. `preview` 端点对批次类型返回 `cmd:null`，对非批次类型返回真实命令；`wa_check` 现走批次分支属 Step 1.1
   迁移的自然结果，若后续有前端依赖 preview 的 `cmd` 字段对 wa_check 做展示，需留意（暂未发现引用）。
