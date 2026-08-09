# Step 1.5 — 发现层运行时冒烟（真实 DDG）

> 这是你的需求唯一来源。PLAN Step 1.5 原文 + 环境事实抄录如下。

## PLAN Step 1.5 原文（验收以 checkbox 为准）

- [ ] 起 daemon（`python -m fetcher daemon --queues discover_fb --local-workers 1`，
      临时 DB 或生产库视环境），手工 INSERT 2 条 work_items（默认矩阵前 2 词 × 1 页）
- [ ] 观察：2 条 item 顺序消费、间隔 ≥60s、fb_posts/fb_groups 出现真实增量
      （若 202 触发，验证退避后继续）
- [ ] 冒烟记录（结果 + 实际耗时 + 限流观测）写入 ledger.md
- 预估 30min（含等待节奏）；验收：fb_posts 或 fb_groups ≥1 行真实新增（202 场景
      下以退避后成功为准）；冒烟记录完整

## 环境事实（协调者已验证，勿重复调查）

1. **DDG 当前可达**：2026-08-09 协调者实测 `https://html.duckduckgo.com/html/?q=site%3Afacebook.com%2Fgroups+%E5%A4%96%E8%B4%B8+whatsapp&s=10` → 200、33KB、含 result__a、无 anomaly。但你执行时可能已在限流窗口（spike 实测约 2 连查后第 3 次 202、封禁窗口约 4 分钟）——202 时原子会退避 uniform(180,240)s 后返回 BLOCKED，item 走 on_giveup 不落库，**下一轮由平台重开**；冒烟判定以「退避后成功」为准。
2. **daemon 全局有头运行**（start.sh DAEMON_ARGS 含 --headed）：但你只起 discover_fb 单队列（local 消费者），**不弹浏览器窗口**。不要用 start.sh 起 daemon——直接 `python -m fetcher daemon ...`（避免拉起全量队列和平台）。
3. **用临时 DB——必须用 `--db` CLI 参数**（**不用**环境变量 FETCHER_DB_PATH：已证实
   daemon 的 `config_from_args` 只读 `args.db`，`resolved_db_path()` 不读环境变量，
   环境变量无效会直连生产库——Step 1.5 首次冒烟已踩过这个坑，见 ledger）。冒烟命令
   统一带 `--db "$SMOKE/1688.db"`，**绝不碰生产库 .cache/1688.db**。
4. **测试基建已就绪**：venv 在 platform/server/.venv/bin/python；fetcher 测试全绿（Step 1.1-1.4 已完成）。
5. **work_items 的 requires 列**：手工 INSERT 时 requires 必须为 `'["local"]'`，否则 local 消费者领不到（LocalLoop resources={"local"}，eligible_queues 检查 `q.requires <= ctx.resources`）。

## 冒烟步骤（精确）

1. 建临时目录与 DB 路径：
   ```
   SMOKE=/tmp/fb_smoke_$(date +%s)
   mkdir -p "$SMOKE"
   cd /Volumes/DataDrive/proj/public/1699/fetcher
   DB_FLAG="--db $SMOKE/1688.db"   # daemon 只认 --db，不认环境变量（已证实）
   ```
2. 预置 2 条 work_items（默认矩阵前 2 词 × 1 页，query 带 site: 前缀）：
   ```sql
   -- 用 python 脚本或 sqlite3 执行。**初始化与查询都显式传同一临时 DB 路径**：
   -- platform/server/.venv/bin/python -c "from fetcher import ShopDB; from pathlib import Path;    --   db=ShopDB(Path('$SMOKE/1688.db')); ..."（ShopDB 构造参数优先，避免环境变量歧义）
   INSERT INTO work_items (queue, site, payload_json, requires, created_at)
   VALUES
     ('discover_fb', NULL, '{"kind":"serp","engine":"ddg","query":"site:facebook.com/groups 外贸 whatsapp","page":1}', '["local"]', '<now>'),
     ('discover_fb', NULL, '{"kind":"serp","engine":"ddg","query":"site:facebook.com/groups 跨境电商 whatsapp","page":1}', '["local"]', '<now>');
   ```
   注意：先初始化 ShopDB（建表）再 INSERT；created_at 用北京时间字符串。
3. 起 daemon（后台）：
   ```
   nohup ../platform/server/.venv/bin/python -m fetcher daemon $DB_FLAG --queues discover_fb --local-workers 1 > "$SMOKE/daemon.log" 2>&1 &
   echo $! > "$SMOKE/daemon.pid"
   ```
4. 观察（轮询）：
   - `tail -f "$SMOKE/daemon.log"` 看消费进度（[local0] 日志）
   - 查 work_items 状态流转（pending→claimed→done/failed）
   - 查 fb_posts / fb_groups 行数与内容（source='ddg'、keyword 溯源）
   - 记录两条 item 的消费时间戳，验证间隔 ≥60s（原子节奏下限）
5. 收尾：`kill $(cat "$SMOKE/daemon.pid")`；等 2 秒确认退出。
6. 若 202 限流：观察退避日志（原子 wait uniform(180,240)），等待后确认是否成功；
   若连续 2 批全 BLOCKED（两条 item 都 failed）→ 记录限流观测，冒烟判定「受限流影响
   未完成」，按 SPEC §8.2 熔断判定上报（不要自作主张换引擎）。

## 冒烟记录要求（写入 ledger.md）

把以下内容**追加**到 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/ledger.md`：

```
## Step 1.5 冒烟记录（<日期时间>）
- 临时 DB：<路径>
- daemon：--db <临时路径> --queues discover_fb --local-workers 1，<PID>，有头观察：无浏览器窗口弹出
- item 消费：item1 <时间> <query> → <outcome>；item2 <时间> → <outcome>
- 间隔：<实际秒数>（下限 60s 达标/未达标）
- 落库：fb_posts 新增 <n> 行（source='ddg'，keyword=...）；fb_groups 新增 <n> 行
- 限流观测：<202 触发与否、退避情况>
- 验收判定：<满足/不满足 + 原因>
```

## 你的工作

1. 按上述步骤执行（命令输出全程保留在 report 文件）。
2. 验证 brief 验收标准（fb_posts 或 fb_groups ≥1 行真实新增；间隔 ≥60s；记录完整）。
3. **不需要 commit 代码**（本 Step 无代码改动）——但 ledger.md 的冒烟记录需要
   commit（只 add ledger.md，禁止 -A）。若你发现代码 bug 需要修，停下上报
   BLOCKED（不要自己修代码——那是主 Agent 协调修复循环的职责）。
4. 完整证据写入 report 文件（含命令输出、DB 查询结果、日志片段）。

工作目录：/Volumes/DataDrive/proj/public/1699

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-1.5-report.md`：
- 执行过程与命令输出
- **验收证据**：fb_posts/fb_groups 查询结果（真实行数 + 内容）、item 状态流转、
  消费间隔、日志片段
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题，如无代码改动则 "docs only"）
- 一行验收结论
- 疑虑（如有）
- report 路径
