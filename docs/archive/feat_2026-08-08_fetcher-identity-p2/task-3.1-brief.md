# Step 3.1 brief — 等价性冒烟（临时库 daemon 直连）

> 来源：PLAN.md Phase 3 Step 3.1。本文本记录冒烟步骤与验收证据要求（走查 Step，由主 Agent 执行、evidence 随跑随写）。

## 内容

### 前置准备
1. 临时库 `/tmp/ident_smoke.db`：清空重建（删旧文件 + -wal/-shm），`ShopDB` 打开建 schema + 触发 `_migrate`，插入 2 条 `shops` pending（含 url/domain 可抓字段，参照既有 shops 行形态）。
2. smoke 证据目录：`docs/feat_2026-08-08_fetcher-identity-p2/smoke/`（日志与 SQL 证据放这里，不放 /tmp）。

### 冒烟命令（用户裁定：--workers 1 直连、--db 临时库；有活爬虫在跑，不加 --headed 用默认 headless——PLAN 文本的 --headed 裁定为不适用本机环境，记录在报告）

```bash
cd fetcher && python -u -m fetcher daemon --db /tmp/ident_smoke.db --workers 1 --limit 2 > ../docs/feat_2026-08-08_fetcher-identity-p2/smoke/smoke_run.log 2>&1
```

### 验收证据（逐条取证据，随跑随写）

1. **cookies 表出现 `1688:direct` 桶**：`SELECT identity, COUNT(*) FROM cookies WHERE identity LIKE '1688:%' GROUP BY identity` → 含 `1688:direct`；**无裸 `direct` 新行**：`SELECT COUNT(*) FROM cookies WHERE identity='direct'` → 0（种子 JSON 导入应落到 `1688:direct` 而非裸 direct）。
2. **行为与 P1 一致**：日志口径（daemon 特征行：`[daemon] 启动重置`、`[cookie] identity=1688:direct，可用 N 个`、item 处理日志）；`contacts` 落库 2 行（或如实记录 item 实际结果）。
3. **平台正则兼容断言**（SPEC §4 假设 4，不改代码验证）：
   ```bash
   python3 -c "
   import re
   pat = re.compile(r'identity=([^\s)，、]+)')
   for s in ['identity=1688:1.2.3.4', 'identity=madeinchina:direct']:
       m = pat.search(s); print(s, '->', m.group(1) if m else None)
   "
   ```
   → 两者均完整匹配（冒号不在排除字符集）→ 平台侧零改动结论成立。
4. **生产库零污染**（基线对照法）：冒烟前后各跑一次只读基线快照（生产库 .cache/1688.db mode=ro：`SELECT COUNT(*), COUNT(DISTINCT identity) FROM cookies`），对比无因冒烟引入的变化；**注意**：本冒烟只用临时库，不打开生产库触发 _migrate——生产库的 _migrate 由首次新代码进程自然触发，属预期行为（部署窗口），记录在报告。

### 约束
- 只碰临时库 /tmp/ident_smoke.db 与 smoke/ 证据目录；生产库只读基线快照
- 不提交任何代码（本步无代码改动）；若有产出 commit 只限 docs
- 进程收尾：daemon 空队列挂起为既有设计（P1 已记录）——--limit 2 收工后若未退出，SIGTERM 收尾并记录

### 报告
`docs/feat_2026-08-08_fetcher-identity-p2/task-3.1-report.md`：命令/日志摘录/SQL 证据/基线对比/结论（SPEC §5 第 5 条 + 平台正则兼容 + 生产库零污染）。
