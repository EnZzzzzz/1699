# Fix Round 1 — Step 3.3（resume implementer p3-3-step3）

你的 Step 3.3 任务 review 判定「通过（需小幅修正）」。reviewer 原文：docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-review.md

## 发现清单（逐字，按优先级）

### C1（Critical）— loop.py:485 `_bound_site` 仅在 plugin 非空时设置，与旧语义不一致

`_bind_item_site` 中 `plugin is not None` 块内才设 `_bound_site`；若 sites dict 无该 key，每次 item 都会重复查找。修复：在 plugin 判断之外无条件恢复 `self._bound_site = site_name`（与旧语义对齐——进入该方法即记录已绑定，防止重复查找）。

### C2（Critical）— task-3.3-report.md 把 P3 引入的 bug 错误标记为「预存 bug」

报告「自查发现 1」写「预存 bug：……确认非本次引入」——但 debug-worker-crash.md 已 traceback 定位：根因是 QueueRouter.make_stats() 返回 {"done":0}（P3 Step 3.1 新增组件），KeyError('empty'/'failed') 是 **P3 引入**，且已被 ca35d5e 修复。更新报告：注明根因已定位为 P3 引入、已修复（commit ca35d5e），删除「预存」断言。

### I3（Important）— 补跑完整跨站填充 end-to-end 冒烟取证

现有冒烟只有「不同批次间的站点切换」单向证据，缺 brief 要求的「1688 冷却期间同 worker 认领 mic item」与「1688 冷却到期恢复认领」双向证据。QueueRouter bug 已修复（ca35d5e），现在可跑完整取证：

```
cd fetcher
# 临时库：2 个 1688 店 + 2 个 mic 店 + mic dummy cookie（madeinchina:direct 桶，域 .cn.made-in-china.com）
python -m fetcher daemon --db /tmp/smoke_p3_33b.db --workers 1 --limit 6 -n 1 \
  --queues crawl_1688_contact crawl_mic_contact --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
  > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/daemon-run-5.log 2>&1
```

取证要求（写入 smoke-step3.3/analysis.md 补节）：
1. **1688 冷却让出**：1688 item 滑块墙失败 → 策略冷却登记（block_rest 让出型）→ 日志可见冷却登记/让出痕迹
2. **冷却期间同 worker 认领 mic**：1688 冷却未到期时，worker 认领并处理 mic item（认领顺序日志可证：1688 处理后 → mic 处理在冷却窗口内）
3. **反向恢复**：1688 冷却到期 → 再次认领 1688 item
4. 若滑块墙导致 1688 item 直接 giveup（非冷却路径），改用**双 1688 店 + 手动在库中把其中一店标记为冷却中**不可行——就如实记录取证到的时序；必要时调整参数（如 --block-rest-min 2 --block-rest-max 3 放大冷却窗）重试一两次，不要无限调参
5. 环境铁律：--workers 1、直连、临时库 /tmp、+1 席以内；滑块墙全 failed 是环境噪声

### M5（Minor）— import traceback 移文件顶部

loop.py except 块内的 `import traceback` 移到文件顶部 import 区。

### M6（Minor）— traceback 截断 [-3000:] 改 [-5000:]

保留根因（异常在末尾）的同时多留上下文。

## 要求

1. 修复 C1/C2 + I3 冒烟取证 + M5/M6
2. 重跑聚焦测试 + 全量（cd fetcher && python -m pytest tests -q）
3. 修复报告**追加**到 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md 末尾（每条：改了什么、覆盖测试、命令、输出）
4. scoped commit（fetcher/fetcher/control/loop.py、fetcher/tests/、docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/、task-3.3-report.md 等）

## 汇报
回复 10 行以内：修复 commit sha + 标题、一行测试总结、冒烟取证要点（跨站认领时序）、report 已追加确认。
