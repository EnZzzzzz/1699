# Step 1.5 冒烟报告 — 发现层运行时冒烟（真实 DDG）

> 状态：**DONE**（2026-08-09 22:03）
> 临时 DB：`/tmp/fb_smoke_1786283975/1688.db`；daemon PID 80522；生产 daemon 34402 全程未受影响。

## 1. 执行过程与命令输出

### 1.1 环境确认

- 生产 daemon 34402（`--workers 1 --headed`）存活，未用 start.sh 起 daemon。
- 确认 CLI 支持 `--db` 参数（`fetcher daemon --help` 显示 `--db DB 数据库路径`）；ShopDB 构造参数 `db_path` 优先（fetcher/db.py:272），无环境变量歧义。

### 1.2 建临时库 + 预置 2 条 work_items

```bash
SMOKE=/tmp/fb_smoke_$(date +%s)   # → /tmp/fb_smoke_1786283975
mkdir -p "$SMOKE"
../platform/server/.venv/bin/python - <<'EOF'
from fetcher.db import ShopDB, _now
db = ShopDB(Path(smoke)/"1688.db")   # 初始化建表
db.conn.executemany("INSERT INTO work_items (queue, site, payload_json, requires, created_at) VALUES (?,?,?,?,?)", [
    ('discover_fb', None, json.dumps({"kind":"serp","engine":"ddg","query":"site:facebook.com/groups 外贸 whatsapp","page":1}, ensure_ascii=False), '["local"]', now),
    ('discover_fb', None, json.dumps({"kind":"serp","engine":"ddg","query":"site:facebook.com/groups 跨境电商 whatsapp","page":1}, ensure_ascii=False), '["local"]', now),
])
EOF
```

确认 2 行就绪（id 1/2，status=pending，requires=`["local"]`）。

### 1.3 起 daemon（后台，`--db` 显式传临时库）

```bash
nohup ../platform/server/.venv/bin/python -u -m fetcher daemon --db "$SMOKE/1688.db" \
  --queues discover_fb --local-workers 1 > "$SMOKE/daemon.log" 2>&1 &
```

**隔离确认（关键）**：启动日志显示
`[fb_discover] 队列待处理: 2`、`[daemon] 队列 discover_fb: 待补货店铺 0 个 + 待认领工作项 2 个`、
`[daemon] 启动重置：0 个 claimed 工作项 → pending`——读的是临时库而非生产库（对比上次事故的
「待补货店铺 3164 个」佐证）。`--db` 参数生效，`config_from_args` → `resolved_db_path()` 全链路一致。

### 1.4 观察（daemon.log 全文）

```
[fb_discover] 队列待处理: 2
[daemon] 队列 discover_fb: 待补货店铺 0 个 + 待认领工作项 2 个
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
[2] 启动 0 个 worker（直连）
[2] 另启动 1 个 local 消费者（无浏览器，wa_check 等非站点队列）
[claim] queue=discover_fb item=1 site=None @2026-08-09 21:59:37
...DDG 查询「site:facebook.com/groups 外贸 whatsapp」第 1 页
[finish] item=1 status=done @2026-08-09 22:00:39
[claim] queue=discover_fb item=2 site=None @2026-08-09 22:00:39
...DDG 查询「site:facebook.com/groups 跨境电商 whatsapp」第 1 页
[finish] item=2 status=done @2026-08-09 22:01:41
```

两条 item 顺序消费（local0），均 done，无 202/失败。

### 1.5 收尾

- `kill` → 3s 后进程仍在（SIGTERM 处理中有 10s 心跳循环），`kill -9` → 确认退出。
- 生产 daemon 34402 存活，生产库 consumer_status 三条心跳（local0/local1/w0）updated_at=22:02:00 正常（10s 心跳节奏）。本次冒烟全程写临时库，未覆盖生产心跳（对比上次事故已修复）。

## 2. 验收证据

### 2.1 fb_posts（真实行 + 内容）

```sql
SELECT id, url, group_id, group_name, keyword, source, status, first_seen_at FROM fb_posts;
-- 1 行：
-- id=1, url=https://www.facebook.com/groups/676368063029200/posts/1442991693033496/
-- group_id=676368063029200, group_name='中国进出口外贸资源交流群（Export trade） | 【最新WhatsApp官方API群发】'
-- keyword='site:facebook.com/groups 外贸 whatsapp', source='ddg', status='pending', first_seen_at='2026-08-09 22:00:39'
```

帖 permalink 真实、keyword/source 溯源完整、group_name 已去 " | Facebook" 后缀。

### 2.2 fb_groups（真实行 + 内容，共 18 行，source 全为 'ddg'）

| id | url | group_id | name（节选） |
|---|---|---|---|
| 1 | https://www.facebook.com/groups/whatspphaiwai | whatspphaiwai | WhatsApp海外业务拓展交流群 |
| 2 | https://www.facebook.com/groups/1893321791187353 | 1893321791187353 | 外贸出口跨境电商交流群 |
| 3 | https://www.facebook.com/groups/212418609907268 | 212418609907268 | 外贸SOHO集中营，工厂资源交流群 |
| 4 | https://www.facebook.com/groups/676368063029200 | 676368063029200 | 中国进出口外贸资源交流群…（item1 帖的派生群） |
| 5 | https://www.facebook.com/groups/2594515050649556 | 2594515050649556 | 跨境外贸工厂进出口群… |

数字 gid 与 slug gid 均正确解析。item2（跨境电商）结果与 item1 大量同 URL，被
`INSERT OR IGNORE`（url UNIQUE）去重——符合设计（幂等，不重复落库）。

### 2.3 item 状态流转 + 消费间隔

| item | claimed_at | finished_at | 终态 | claimed_by | 耗时 |
|---|---|---|---|---|---|
| 1（外贸 whatsapp） | 21:59:37 | 22:00:39 | done | local0 | 62s |
| 2（跨境电商 whatsapp） | 22:00:39 | 22:01:41 | done | local0 | 62s |

- 间隔：两次 claimed 差 62s、两次 finish 差 62s → **≥60s 达标**（原子 MIN_SAMPLE_FLOOR=60 生效）。
- 流转：pending → claimed（claimed_at 21:59:37）→ done（finished_at 22:00:39），结果完整。

### 2.4 consumer_status（临时库内，隔离确认）

```json
{'consumer_id': 'local0', 'kind': 'local', 'current_queue': None,
 'cooldowns_json': '{}', 'updated_at': '2026-08-09 22:01:47'}
```

心跳写在临时库，未触碰生产库 local0 行。

## 3. ledger.md 追加内容

见 `docs/feat_2026-08-09_fb-discovery-group-feed/ledger.md` 末尾「## Step 1.5 冒烟记录（2026-08-09 22:03，DONE）」：
临时 DB / daemon 命令与 PID / item 消费时间线 / 间隔 62s / 落库 1 帖 + 18 群 / 限流观测无 202 / 验收判定满足。

## 4. 疑虑与观测

- **无 202 触发**：两条查询首次即 200 真实结果。协调者 spike 曾实测「2 连查后第 3 次 202」，本次 62s 节奏留足余量；但 18 群 + 1 帖中 item2 几乎全为 item1 去重结果，未验证「第二次独立查询后第 3 连查」的限流边界（冒烟仅 2 条 item，符合 brief 范围）。
- **SIGTERM 退出不即时**：kill 后 3s 仍在（10s 心跳循环间隙），需 kill -9；属 daemon 心跳循环正常行为，非缺陷。
- **item2 落库 0 新增**（全部去重）：符合 INSERT OR IGNORE 幂等设计，不影响验收（fb_posts/fb_groups ≥1 行真实新增已满足）。
- **fetch 耗时 62s/item**：包含 DDG HTTP + 节奏等待（uniform(60,…)），与设计节奏一致。
