# Step 2.4 brief — 直连冒烟

> 来源：PLAN.md Phase 2 Step 2.4。本文本是你的需求唯一来源。这是走查/冒烟类 Step：**report 必须含真实命令输出证据**，口头声明不算数。

## 内容

在真实环境跑通 daemon 完整链路（真实浏览器、真实 1688 访问、直连无代理）：

### A. 准备工作

1. 确认 CLI 有 `--db` 参数（`add_common_args` 里找；`RunConfig.resolved_db_path()` 默认指向项目 `.cache/1688.db`）。**绝对不许用生产库 `.cache/1688.db` 跑冒烟**——用 `/tmp/daemon_smoke.db` 之类的临时路径。
2. 用 python/sqlite3 往临时库预置 2 条 shops pending 种子数据（表结构读 `fetcher/fetcher/db.py` SCHEMA；domain 用真实 1688 店铺域名，可以从生产库 `.cache/1688.db` 只读 SELECT 两条 done 的 shop 抄 domain/name/url，只读不谢写；status='pending'，first_seen_at 等必填列按 SCHEMA 填）。

### B. 主冒烟：跑 2 条

```
cd fetcher && python -m fetcher daemon --db /tmp/daemon_smoke.db --limit 2 --workers 1 --headed
```

（`--headed` 有头便于观察；如出现滑块，auto_solve 默认开，观察即可；若 headed 在当前环境起不来，退 `--headless` 并在 report 说明。）

预期：daemon 启动 → reset 日志（0 行）→ top-up 补货 2 条 → 消费者逐条抓取 → `--limit 2` 收工退出。

跑完后核查（SQL 输出贴进 report）：
- work_items：2 行 done，finished_at 非空
- shops：2 行 done（或 no_contact——该店铺确实无联系方式时也算正常终态，report 说明实际值）
- contacts：落库记录，字段口径正常

### C. 空队列挂起 + 信号退出

用同一临时库再启动一次（已无 pending shops）：

```
cd fetcher && python -m fetcher daemon --db /tmp/daemon_smoke.db --workers 1
```

观察 ≥60s：进程不退出、无滚动日志空转（CPU≈0 可用 `ps -o %cpu -p <pid>` 抽测两次）。然后发 SIGTERM（`kill <pid>`），预期 30s 内干净退出（消费者 wait 自醒查 stop → 浏览器关闭 → 进程退）。记录退出耗时与日志尾部。

### D. 清理

临时库删除；确认生产库 `.cache/1688.db` 无烟雾数据（你本就不该碰它，核查一下 work_items 表无本测试产生的行——注意 daemon 启动的 reset 只动你 --db 指定的库）。

## 验收

- [ ] 2 条 work_items done、shops 落终态、contacts 落库（SQL 证据）
- [ ] 空队列挂起 ≥60s 不退出、CPU≈0（ps 证据）
- [ ] SIGTERM 后 30s 内干净退出（日志证据）
- [ ] 全程未写生产库

## 约束

- 不改任何代码。发现 bug → 停下以 BLOCKED/DONE_WITH_CONCERNS 上报，附完整日志。
- 若环境缺依赖（playwright 浏览器未装等）导致无法冒烟，先按项目既有方式确认（fetcher/README.md / `python -m fetcher 1688 contact --help` 能跑通说明环境 OK），确认是环境问题则 BLOCKED 上报，不要尝试装依赖。
- 冒烟全程可能 5~15 分钟，正常。
