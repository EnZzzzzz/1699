# Step 5.2 全量回归 — 报告

**执行时间**: 2026-08-09（Phase 5 第二个 Step）
**执行者**: Claude (pi coding agent)
**状态**: **DONE** — 三组全绿，SPEC §10 验收 6 满足
**代码改动**: 零（纯回归验证，未改任何源文件）

---

## 1. 回归基线

- 分支：`feat/facebook-daemon-integration`
- 工作区含另一条工作线（daemon-headed-queues）未提交改动（runner.py、test_batch_tasks.py、start.sh 等），
  与本 feature 无关，回归前未触碰；本 Step 只 add report + ledger。
- feature 代码全部就位（Step 1.1–5.1 完成），本 Step 只验证不修改。

## 2. 三组回归命令与输出

### 2.1 fetcher 全测试组

命令：
```bash
cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests
```

输出摘要：
```
Ran 740 tests in 29.193s

OK
```

| 项 | 值 |
|---|---|
| 测试数 | 740 |
| 失败/错误 | 0 |
| 耗时 | 29.193s |
| 结论 | ✅ 全绿 |

涵盖 feature 相关：`test_cli_fb.py`（FbDiscover/FbGroup CLI）、`test_batch_enqueue.py`、
`test_batch_inherit.py`、fb_discover/fb_group 原子与任务测试；既有 FB 测试均通过未动。

### 2.2 平台测试组

命令：
```bash
cd platform/server && .venv/bin/python -m unittest discover -s tests
```

输出摘要：
```
Ran 72 tests in 0.319s

OK
```

| 项 | 值 |
|---|---|
| 测试数 | 72 |
| 失败/错误 | 0 |
| 耗时 | 0.319s |
| 结论 | ✅ 全绿 |

feature 相关用例确认在跑：`test_batch_tasks.py` 的 `FbBatchDispatchTest`（4 例：
defaults / explicit keywords+pages / group defaults / group explicit+limit）与
`FbBatchEnqueueTest`（4 例：empty→0、expand keywords×pages、同 query+page 幂等、
pages<1 视为 1）。

唯一警告（非失败）：`StarletteDeprecationWarning: Using httpx with starlette.testclient is
deprecated; install httpx2 instead` —— 依赖层弃用提示，与 feature 无关，既有现象。

### 2.3 前端 tsc

命令：
```bash
cd platform/web && npx tsc -b
```

输出：无报错，`EXIT=0`，耗时 3.098s。

| 项 | 值 |
|---|---|
| 类型检查 | 通过 |
| 退出码 | 0 |
| 耗时 | 3.098s |
| 结论 | ✅ 全绿 |

覆盖 Step 4.1–4.4 的 `lib/api.ts`、`task-ui.tsx`、`TaskFormDialog.tsx`、`Tasks.tsx` 改动。

## 3. 失败清单

无。三组零失败、零错误。

## 4. 验收判定（SPEC §10 验收 6）

| 验收要求 | 结果 | 证据 |
|---|---|---|
| fetcher 测试全绿（新增原子/Task/DB/CLI 测试 + 既有 FB 测试不动） | ✅ | 740 tests OK（29.193s） |
| 平台测试全绿 | ✅ | 72 tests OK（0.319s） |
| `npx tsc -b` 通过 | ✅ | EXIT=0（3.098s） |

## 5. 疑虑/观测

1. 平台测试的 `StarletteDeprecationWarning`（httpx→httpx2）为既有依赖弃用提示，非本 feature
   引入，不影响验收；可后续随依赖升级清理。
2. fetcher 测试尾部有 daemon 相关日志输出（wa_check 未注册跳过本地队列等），为既有
   daemon 测试探针日志，非失败。
3. 本 Step 为纯回归，无代码 review 面；feature 代码 review 已在前序 Step 完成。

## 6. ledger 追加

见 `ledger.md` 末尾一行（Step 5.2 执行记录）。

---
**结论**: 三组全绿，Step 5.2 DONE，验收 6 满足。
