# Step 3.1 brief — 代理模式等价性对比

> 来源：PLAN.md Phase 3 Step 3.1 + SPEC §5 第 2、3 条。本文本是你的需求唯一来源。**走查类 Step：report 必须含真实命令输出与 SQL 证据。**

## 目的

证明：同参数下 daemon 模式与旧 CLI（`python -m fetcher 1688 contact`）的请求节奏、抓取结果、DB 落库口径一致（事件序列允许日志格式差异；SPEC §3.3 已裁定的 cold_start 店铺首页差异不算差异项）。

## 环境约束（主 Agent 已勘察，必须遵守）

- 本机有两个 madeinchina 爬虫在跑（`python -m fetcher madeinchina`，pid 2799/86546），CloakBrowser 席位（共 5）部分被占。**两边都只能用 `--workers 1`**，把席位与通道占用压到最低；若启动时席位满，等席位是正常现象（日志每 20s 重查），耐心等。
- 生产库 `.cache/1688.db` 正在被活爬虫写——**绝对不许用作测试库**，也不许对它做任何写操作（只读 SELECT 可以）。
- daemon 与旧 CLI 的启动 reset 语义会重置 in_progress——所以两边各用独立临时库：`/tmp/equiv_a.db`（旧 CLI）、`/tmp/equiv_b.db`（daemon）。
- 主 Agent 裁定：为压缩墙钟时间，两边的 `--batch-rest` 都从默认 900 等值改为 120（两边参数完全相同，比较有效性不变；PLAN 要求的是「相同节奏参数」，等值缩放满足）。除此项外全部用默认值。

## 步骤

### A. 种子数据

从生产库**只读**抄 40 条 1688 店铺（status='done' 的，domain LIKE '%.1688.com'，ORDER BY id DESC LIMIT 40），分别预置进两个临时库（每库 40 条，status='pending'；用 `ShopDB(path).upsert_shops(...)` 或 SQL，字段按 `fetcher/fetcher/db.py` SCHEMA）。两库种子内容完全一致（同 40 条、同序）。

### B. A 组：旧 CLI

```
cd fetcher && python -u -m fetcher 1688 contact --db /tmp/equiv_a.db --proxy --workers 1 --limit 20 --batch-rest 120
```

跑完（--limit 20 收工自动退出），日志存 `/tmp/equiv_a.log`。

### C. B 组：daemon

```
cd fetcher && python -u -m fetcher daemon --db /tmp/equiv_b.db --proxy --workers 1 --limit 20 --batch-rest 120
```

跑完，日志存 `/tmp/equiv_b.log`。

两组顺序执行（不要并行，避免席位/通道争抢干扰节奏测量）。跑之前 `date` 记录起止时间。

### D. 对比指标（全部贴 SQL/命令输出）

1. **请求节奏**：从日志或 ip_stats/ip_events 提取每组的页面请求时间序列，算「活跃期每分钟请求数」（排除批休 120s 窗口）；两组应落在同一量级（各自给出数值与简表）。
2. **成功率/终态分布**：两组 shops 的 status 分布（done/no_contact/failed 各多少）；contacts 落库条数。
3. **字段口径**：两组 contacts 各抽查 3 条完整行（除 shop_id/scraped_at 外字段应同构）；work_items 表只有 B 组有（20 行 done）。
4. **结论**：三项指标是否支持「行为等价」。

### E. 清理

删除临时库与 wal/shm；核查生产库零污染：`SELECT COUNT(*) FROM work_items;` 应为 0，ip_stats/ip_events 无本时段新增 direct/代理记录（记录核查前后的 MAX(updated_at) 对照）。

## 验收

- [ ] SPEC §5 第 2 条：B 组 daemon 代理模式 --limit 20 跑通，work_items 全 done，shops/contacts 落库
- [ ] SPEC §5 第 3 条：A/B 对比（节奏、成功率、字段口径）支持等价结论
- [ ] SPEC §4 假设 3 回填：冒烟期间平台服务（若本机 uvicorn 在跑，端口 8765）各页面无异常——用 `curl -s localhost:8765/api/...` 挑 2-3 个只读接口验证即可；若平台没在跑，记录「平台未运行，本项不适用」
- [ ] 生产库零污染证据

## 约束

- 不改任何代码。发现 bug → BLOCKED/DONE_WITH_CONCERNS 上报，附日志。
- 两组都失败于同一环境因素（如代理不可用、1688 全量滑块）→ 这仍是有效对比数据，如实记录，不要硬凑成功。
- 全程预计 30~60 分钟，正常。两组启动时等席位不算异常。
