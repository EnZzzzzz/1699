# Step 3.1 brief — 等价性冒烟（冷却迁移 P1）

> 来源：PLAN.md Phase 3 Step 3.1 + SPEC §5 第 4、5 条。本文本是你的需求唯一来源。**走查类 Step：report 必须含真实命令输出与日志时间戳证据。**

## 目的

验证冷却迁移后行为等价：daemon 与旧 CLI 两条路径、同参数，节奏模式一致（样本间隔/批休/长休落在公式区间）；冷却中 SIGTERM 秒级中断。

## 环境约束（主 Agent 勘察，必须遵守）

- 本机有活爬虫（madeinchina × 2），CloakBrowser 席位部分被占：**只许 `--workers 1` 直连**，不耗代理；启动等席位是正常现象。
- **绝对不许写生产库 `.cache/1688.db`**（只读 SELECT 可以）；用 `/tmp/cooldown_a.db`、`/tmp/cooldown_b.db` 两个临时库。

## 步骤

### A. 种子数据

生产库只读抄 6 条真实 1688 店铺（status='done'，domain LIKE '%.1688.com'，ORDER BY id DESC LIMIT 6），分别预置进两个临时库（status='pending'，两库同 6 条同序）。

### B. daemon 路径

```
cd fetcher && python -u -m fetcher daemon --db /tmp/cooldown_a.db --workers 1 --limit 6 -n 3 --batch-rest 60 --sample-min 3 --sample-max 6 --rest-every 2 --rest-min 5 --rest-max 10
```

（小参数是为了在 6 条内强制触发批休×1、长休、样本间隔全部路径；注意 --sample-min/max 被改小是**测量需要**，对比时旧 CLI 用完全相同的参数。）

日志存 `/tmp/cooldown_a.log`。从日志/临时库提取每个 item 的完成时间戳序列，列表：相邻间隔应落在 sample 区间（3~6s+wid 错峰 + fetch 耗时），第 3 条后应出现批休窗口（60±10% = 54~66s）。

### C. 旧 CLI 路径

```
cd fetcher && python -u -m fetcher 1688 contact --db /tmp/cooldown_b.db --workers 1 --limit 6 -n 3 --batch-rest 60 --sample-min 3 --sample-max 6 --rest-every 2 --rest-min 5 --rest-max 10
```

日志存 `/tmp/cooldown_b.log`，同样提取时间戳序列。

### D. 对比

两条路径的时间戳序列表并排：样本间隔区间、批休窗口、长休触发（rest-every 2 → 每 2 个一次 5~10s 长休）、总耗时。结论：节奏模式是否一致（同区间、同结构；绝对值允许 fetch 耗时差异）。

### E. 冷却中 SIGTERM 中断

用临时库 A 再跑一次同参数 daemon，**在批休 60s 窗口内**（观察日志出现「批次休息」倒计时后）发 SIGTERM：预期秒级中断（远小于 60s），进程干净退出。记录从 kill 到退出的耗时与日志尾部。

### F. 清理

删临时库；核查生产库零污染（`SELECT COUNT(*) FROM work_items;` 与 ip_stats/ip_events 的 MAX 时间戳前后对照，归因方法参照 docs/archive/feat_2026-08-07_fetcher-daemon-p0/task-3.1-report.md §E）。

## 验收

- [ ] SPEC §5 第 4 条：daemon 小参数跑通，节奏模式（样本间隔/批休/长休区间）与公式一致
- [ ] SPEC §5 第 5 条：旧 CLI 同参数不回归，两条路径节奏模式一致
- [ ] 冷却中 SIGTERM 立即中断（远小于 60s 的证据）
- [ ] 生产库零污染

## 约束

- 不改任何代码。发现行为不等价（某等待缺失/时长错误/中断失效）→ BLOCKED 上报，附两条路径的对照证据——这是本 P1 的核心验收，不许硬凑。
- 两组跑数各约 3~8 分钟，正常。
