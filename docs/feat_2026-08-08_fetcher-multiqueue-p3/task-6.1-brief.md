# Task 6.1 Brief — 跨站填充端到端冒烟（全量 5 队列验收取证）

> 来源：PLAN.md P3-6 Step 6.1 全文 + SPEC §7 验收标准。本文件是本次任务的唯一需求来源。

## 目标

SPEC §7 验收标准的运行时取证（命令 + 日志摘录 + 计数落 plan 目录 report）：

1. **端到端跨站填充**：单通道 daemon（--workers 1）日志显示 madeinchina 冷却登记后、到期前，同 worker 认领并执行 1688 工作项；反向同样成立（双向）
2. **预算合规**：日志中 ip_req 簿记显示同 (site,IP) 请求数不超各 task 的 `ip_request_budget`（mic shop=60、mic contact=80、1688 shop/company=12）
3. **无重复认领**：claim 无重复认领（日志无重域名/DB work_items 无重复处理）

## 冒烟设计

环境铁律：--workers 1、直连、临时库 /tmp、CloakBrowser +1 席以内（冒烟前查席位，满则等待或报告）；直连 1688 滑块墙近乎必现是环境噪声，取结构证据。

**主冒烟（全量 5 队列，或按环境可用子集）**：

```
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_61.db --workers 1 --limit 12 -n 1 \
  --queues crawl_1688_contact crawl_mic_contact crawl_mic_shop crawl_1688_shop crawl_1688_company \
  --batch-rest 1 --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 3 --sample-max 3 --rest-every 0 --block-rest-min 2 --block-rest-max 3 \
  > docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/run.log 2>&1
```

- 临时库预置：1688 店 2 个 + mic 店 2 个（shops 表）+ mic dummy cookie（madeinchina:direct 桶）；1688 shop/company 队列靠播种（空进度库 → discover）
- **--sample-min 3 --sample-max 3**：mic item 成功后 sample_interval 让出型冷却 3s——冷却窗口内 1688 队列可认领 → 「冷却登记后到期前同 worker 执行另一站 item」的严格证据（Step 3.3 取证缺口的补全）

**取证要点（report/analysis）**：

1. **双向跨站填充**：
   - 方向 1：1688 item 处理（失败/成功）→ mic item 认领（1688 冷却窗口内，时间戳可证）
   - 方向 2：mic item done → sample_interval 让出（mic 冷却 3s）→ 冷却窗口内 1688 item 认领 → 3s 后 mic 恢复认领
   - 时间戳序列摘录进 report（关键行原文）
2. **预算合规**：从日志 tmd/簿记或 DB ip_stats/ip_events 取数——各 (site,IP) 的请求数 vs 该 site task 预算（若直连滑块墙导致请求少，说明「未超预算」成立即可，附数据）
3. **无重复认领**：DB work_items 查询（无同 item 双 claimed/finished）；或日志认领序列无同 domain 撞车
4. **DB 只读取证**（Step 4.2/5.2 教训）：sqlite3 命令 + 输出原文贴入（work_items 状态分布、category_progress、shops 落库）
5. 运行时长控制：预期 5 分钟内收工（--limit 12）；超 10 分钟取证当前输出后收尾

**次冒烟（如主冒烟环境受限）**：降级为双队列（crawl_1688_contact + crawl_mic_contact）同参数——验收 1 的核心证据（双向跨站填充）用双队列即可证；5 队列的装配正确性由注册表单测 + 各队列单队列冒烟（Step 4.2/5.2 已做）背书。report 说明降级原因。

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试基线 512 passed
- 冒烟日志写 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/`（run.log + analysis.md + DB 取证，随跑随写）
- 参考：Step 3.3 的跨站手递手取证模式（smoke-step3.3/analysis.md）、Step 5.2 的 DB 取证格式
- 不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/、docs/feat_2026-08-07_apify-provider-pairing-login/

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step6.1/`、`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md`
- 工作区有他人未提交改动，**绝不碰绝不带**，不要 `git add -A`

## 验收

1. 双向跨站填充时间戳证据（方向 1 + 方向 2 摘录）
2. 预算合规数据（各 site 请求数 vs 预算）
3. 无重复认领证据（DB 查询）
4. DB 只读取证原文
5. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-6.1-report.md`：命令、时间戳摘录、计数、环境说明、降级说明（如有）
