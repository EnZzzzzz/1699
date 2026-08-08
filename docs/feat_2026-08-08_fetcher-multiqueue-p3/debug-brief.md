# 调试任务 — 定位 worker 异常退出 'empty'/'failed' 根因

## 背景

P3 分支冒烟（docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/）发现：daemon 双队列直连冒烟时 worker 异常退出，异常消息为纯字符串 `'empty'`（run-4）或 `'failed'`（run-3），被 loop.run() 的 `except Exception as e: self.log(f"[X] worker 异常退出: {e}")` 吞掉无栈。这阻断了 P3-3 验收（1688 冷却 → 同 worker 认领 mic 的跨站填充完整取证）。

判断目标：**该 bug 是 P3 引入的回归，还是 main 分支预存问题**（implementer 声称 stash 回退 Step 3.3 改动后仍复现——但只回退了 Step 3.3，不能排除 Step 3.1/3.2 引入）。

## 方法（systematic-debugging）

### Phase 1 根因调查（先做这个）

1. 读冒烟日志了解崩溃时序：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/daemon-run-3.log`（1688 滑块墙 → relaunch → 崩 'failed'）与 `daemon-run-4.log`（mic 成功 1 请求 → 崩 'empty'）
2. **给 loop.run() 的 except 分支加 traceback 打印**（这是合理产品改进，不算越界）：`fetcher/fetcher/control/loop.py:273` 附近，`self.log(f"[X] worker 异常退出: {e}")` 前加 `import traceback; self.log(traceback.format_exc()[-2000:])` 或等价的栈打印（注意 self.log 对多行文本的处理——board.log 应能收多行，print 路径直接打印）
3. 跑复现冒烟拿栈：
   ```
   cd fetcher
   # 临时库：2 个 1688 店 + 2 个 mic 店 + mic dummy cookie（域 .cn.made-in-china.com 的 madeinchina:direct 桶 1 条）
   python -m fetcher daemon --db /tmp/dbg_p3.db --workers 1 --limit 4 -n 1 \
     --queues crawl_1688_contact crawl_mic_contact --batch-rest 1 \
     --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
     --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
     > /tmp/dbg_p3.log 2>&1
   ```
   - 环境铁律：--workers 1、直连、临时库 /tmp、+1 席以内（当前席位 0，安全）；直连 1688 滑块墙必现是已知环境噪声
   - 若 run-3 场景（1688 全 pending 无 mic）更易复现，可单独跑 `--queues crawl_1688_contact`
4. 从栈定位 raise 点（file:line + 代码路径）

### Phase 2 判断 P3 引入 vs 预存

- 栈指向 **P3 改动文件**（control/loop.py 的 release 分支、control/queue_router.py、strategy/strategies.py 的 swap_ip 两阶段）→ **P3 引入**（需修复，属本任务范围）
- 栈指向 **既有代码**（sites/*、atoms/slider.py、detect/*、net/browser.py 未改动部分）→ 疑似预存——**对照验证**：`git stash` 全部 P3 改动（fetcher/ 与 docs/）后在 main 上跑同参数单队列冒烟（main 用 `--queue crawl_1688_contact`，P0 CLI），看是否同样崩。若 main 也崩 → 预存 bug（如实记录栈，报告主 Agent 开 issue）；若 main 不崩 → 仍是 P3 引入（栈指向的既有代码是 P3 触发方式不同）

### Phase 3 处置

- P3 引入 → 修复（TDD：先写失败测试复现该异常，再修到绿；修复后全量 `cd fetcher && python -m pytest tests -q`）
- 预存 → 不修（用户指令：不擅自扩大范围），记录根因+栈，报告主 Agent 按 issue-create skill 记录
- 无论哪种：**traceback 打印保留**（产品改进），report 写明

## 汇报

报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-08_fetcher-multiqueue-p3/debug-worker-crash.md`：崩溃时序、traceback 全文、raise 点定位、P3/预存判定依据、处置结果（修复 commit 或预存记录）。回复 10 行以内：状态、根因一句话、判定（P3 引入/预存）、commit 或记录路径。
