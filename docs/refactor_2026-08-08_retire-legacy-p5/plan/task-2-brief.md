# task-2-brief — Step 1.2 cmdparse + 死字段删除

> 本文件是你（implementer）需求的唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699
> 模型：deepseek-v4-flash。前置：Step 1.1 已完成（wa_tasks 与进程内机械已删，分支 refactor/retire-legacy-p5）。

## 项目位置

「1688 采集平台调度器改造 P5 退役旧路径」的 Step 1.2（P5-1 后半）：cmdparse「从命令导入」链路
已名存实亡（解析产出的参数对批次模型无效），TaskParams 三个死字段无人消费，本次删除。

## 删除清单（照单执行，不扩大不缩小）

1. 删除文件：`platform/server/app/cmdparse.py`（整个文件，169 行）
2. `platform/server/app/api/tasks.py`：
   - 删 `CommandParse` pydantic 模型（约 line 174-175）
   - 删 `@router.post("/tasks/parse")` 端点 `parse_task_command`（约 177-186）
   - `TaskParams` 删 3 个字段：`interval`（约 118-119，含注释）、`batch_rest_min`（约 121）、
     `batch_rest_max`（约 122）
3. `platform/server/app/runner.py` `build_command`：
   - 删 `if task_type == "1688_contact" and params.get("retry_failed") is True: cmd.append("--retry-failed")`
     （约 line 142-143，1688_contact 已是批次类型、永不走 build_command，死分支）
   - docstring 里对应说明行「retry_failed=true 且 1688_contact→--retry-failed；」同步删

## 保留面（不动）

- `/tasks/preview` 端点两个活分支：批次文案分支（BATCH_TYPE_NAMES，返回「批次提交：queue」）
  与 yiwugo build_command 真实命令行分支——都保留。
- `TaskParams.retry_failed` 字段本身保留（前端 1688_contact 表单开关还在用，仅删 build_command 里的死分支）。
- TaskParams 其余字段（batch_num/sample_min/sample_max/accounts/limit/repeat_interval 等）不动。
- runner 的 Timer 全套、subprocess 机械、批次/sweeper 全套（Step 1.1 已确认保留面）。

## 环境与约束

- pytest 用 `platform/server/.venv/bin/python -m pytest`。
- 只跑聚焦测试；commit 前跑 `platform/server` 下全量 `tests/`（基线 56 passed）。
- 禁止碰：fetcher/、scraper/、util/、docs/、platform/web/（前端归 Step 2.1）。
- 不要写生产库 `.cache/1688.db`。
- 活服务在 8765 跑旧代码，**不要动它**。

## 冒烟验收（临时实例，不碰活服务）

preview 端点两个活分支的运行时验证，用临时 uvicorn + 临时库副本：

1. `cp /Volumes/DataDrive/proj/public/1699/.cache/1688.db /tmp/p5_step12_preview.db`（副本，只读用途）
2. 写一个临时启动脚本（如 `/tmp/p5_step12_launcher.py`）：先 `import app.db; app.db.DB_PATH = "/tmp/p5_step12_preview.db"`，
   再 `from app.main import app`，最后 `uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")`。
   用 `.venv/bin/python` 跑，后台起，等端口就绪（sleep/轮询）。
3. curl 两个分支（输出落 plan 目录）：
   - 批次分支：`curl -s -X POST http://127.0.0.1:8766/api/tasks/preview -H 'Content-Type: application/json' -d '{"type":"1688_contact","params":{"limit":100}}'`
     → 期望 `{"cmd":null,"cmdline":"批次提交：crawl_1688，100 条"}`
   - yiwugo 分支：`curl -s -X POST .../api/tasks/preview -H ... -d '{"type":"yiwugo_search","params":{"limit":50}}'`
     → 期望含 `python -m fetcher yiwugo search`
   - 对照组（wa_check 现走 build_command 会 422，属预期行为变化，记录即可非缺陷）：
     `-d '{"type":"wa_check","params":{}}'` → 期望 422
4. 杀掉临时 uvicorn（kill 实际监听 pid）。三组输出写进 report。

## commit

- scoped add：`git add platform/server/app/cmdparse.py platform/server/app/api/tasks.py platform/server/app/runner.py`
  （cmdparse.py 是删除，用 git rm 或 git add -A）
- commit message：`refactor(p5): 删除 cmdparse 从命令导入链路与 TaskParams 死字段`
- 只 commit 本 Step 涉及文件。

## 验收标准

- [ ] 平台 pytest 全绿（56 passed 基线附近，净变化应接近零——本 Step 无测试依赖 cmdparse/死字段）
- [ ] `app/` 下 grep `cmdparse\|parse_command\|CommandParse\|/tasks/parse` 零命中
- [ ] `app/` 下 grep `interval\|batch_rest_min\|batch_rest_max` 零命中（注意 repeat_interval 含 interval 子串，
      用 `\binterval\b` 或排除 repeat_interval；runner.py 的 `("batch_rest", "--batch-rest")` 与
      batch_rest_min/max 不同，勿误伤）
- [ ] runner.py 无 `retry_failed` 残留（仅限 build_command 区域；TaskParams.retry_failed 字段保留属预期）
- [ ] 临时 uvicorn 冒烟三组 curl 输出落 plan 目录
