# Step 3.4 平台冒烟报告（含 SPEC §6.5 start.sh 改动）

- 执行时间：2026-08-09 22:43–22:46（北京时间）
- 执行人：implementer（Step 3.4）
- 工作目录：/Volumes/DataDrive/proj/public/1699

## 1. start.sh 改动（SPEC §6.5）

在既有 `export WA_CHECK_ACCOUNTS=...` 行之后、daemon 启动之前追加（幂等 pass-through）：

```bash
# FB 群采集第三方 API key（fb_group 批次用；缺失时该群采集 FATAL → 批次 failed）
# key 由部署方在启动 shell 环境提供（.env 已 gitignore，不入库）；daemon 继承该环境
# （start.sh 的 nohup 子进程天然继承）。缺失时原子 FATAL 是既有行为，本期不新增凭证体系。
export BRIGHTDATA_API_KEY="${BRIGHTDATA_API_KEY:-}"
export APIFY_TOKEN="${APIFY_TOKEN:-}"
```

grep 证据：

```
$ grep -n "BRIGHTDATA_API_KEY\|APIFY_TOKEN\|WA_CHECK_ACCOUNTS" platform/start.sh
24:export WA_CHECK_ACCOUNTS=${WA_CHECK_ACCOUNTS:-xiaohao-4,xiaohao-5}
29:export BRIGHTDATA_API_KEY="${BRIGHTDATA_API_KEY:-}"
30:export APIFY_TOKEN="${APIFY_TOKEN:-}"
$ bash -n platform/start.sh && echo "syntax OK"
syntax OK
```

既有 `--headed` / `WA_CHECK_ACCOUNTS` 行未改动（合并而非覆盖）。`.env` 已在根 .gitignore
（第 18-19 行 `.env` / `.env.*`），key 不入库 ✓。

## 2. 重启（stop.sh 停旧 → start.sh 起新）

旧 daemon 34402（16:12 启动，facebook-daemon-integration 工作线产物）**不认新队列**
（daemon.log 无 discover_fb/crawl_fb_group 注册），按 brief 保守处理：stop.sh 停旧 →
start.sh 起新。

```
$ ./stop.sh
[停止] 后端 uvicorn (pid 34392) SIGTERM ...
[停止] 前端 vite (pid 34397) SIGTERM ...
[停止] 调度器 daemon (pid 34401) SIGTERM ...
[兜底] 清理残留 uvicorn 进程
[兜底] 清理残留 vite 进程
[兜底] 清理残留 fetcher daemon 进程
已全部停止。
```

- 观测①：daemon 子进程 34402 在 SIGTERM 后仍存活（pidfile 记父进程 34401），
  `pkill -f "fetcher.*daemon"` 兜底也未清掉，需 `kill -9 34402` 手动清除。这是 stop.sh
  已知的 pidfile=父进程特性（AGENTS.md §4 已注明「杀端口占用进程时按实际监听 pid」），
  非本 Step 引入。
- 观测②：首次 `./start.sh` 经 bash 工具调用时，工具等待长驻子进程退出导致 120s 超时
  并连带杀掉了刚启动的进程组。改用 `nohup ./start.sh > /tmp/start_smoke.out 2>&1 &
  < /dev/null` 完全脱离后正常（这是调用方式问题，非 start.sh 缺陷；start.sh 本身幂等
  无 bug）。

```
$ nohup ./start.sh ... &   # 脱离调用 shell
[启动] 后端 uvicorn :8765 ...       pid=30011
[启动] 前端 vite dev :3000 ...      pid=30015
[启动] 调度器 daemon（fetcher daemon --workers 1 --headed）... pid=30019
已就绪：前端 http://127.0.0.1:3000  后端 http://127.0.0.1:8765
```

新进程：uvicorn **30012** / daemon **30020** / vite **30051**（存活，冒烟全程未崩）。

新队列注册证据（daemon.log 最新 boot 段，line 32937 起）：

```
[daemon] 队列 crawl_1688_company: 待补货店铺 3246 个 + 待认领工作项 507 个
[daemon] 队列 wa_check: 待补货店铺 3246 个 + 待认领工作项 111 个
[daemon] 队列 discover_fb: 待补货店铺 3246 个 + 待认领工作项 0 个
[daemon] 队列 crawl_fb_group: 待补货店铺 3246 个 + 待认领工作项 0 个
[daemon] 启动重置：2 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
```

**8 条队列全量注册**（含新队列 discover_fb / crawl_fb_group，均 local 消费者），
daemon 日志无 key 相关报错 ✓（BRIGHTDATA_API_KEY/APIFY_TOKEN 缺失仅在该队列实际
消费时触发原子 FATAL，冒烟中 crawl_fb_group 未消费，符合预期）。

## 3. fb_discover 任务（API 创建 → start 入队 → 断言）

### 3.1 自定义 2 词 × 1 页（brief 冒烟步骤）

```
POST /api/tasks {"type":"fb_discover","params":{"keywords":"site:facebook.com/groups 外贸 whatsapp\nsite:facebook.com/groups 跨境电商 whatsapp","pages":1}}
→ HTTP 201，task id = 85
POST /api/tasks/85/start → {"ok":true,"queue":"discover_fb","items":2} HTTP 200
```

> 注：平台批次模型「start = 入队」（runner.py `enqueue_batch_for_task`，batch_id=task_id），
> create 只落 tasks 行，work_items 在 start 时生成。brief 步骤 4 的断言放在 start 后执行。

只读连接断言（`.cache/1688.db?mode=ro`）：

```
SELECT id, queue, site, batch_id, requires, status,
       json_extract(payload_json,'$.engine'), json_extract(payload_json,'$.query'),
       json_extract(payload_json,'$.page') FROM work_items WHERE batch_id=85 AND queue='discover_fb'

count = 2
{'id': 25619, 'queue': 'discover_fb', 'site': None, 'batch_id': 85, 'requires': '["local"]', 'status': 'pending', 'engine': 'ddg', 'query': 'site:facebook.com/groups 外贸 whatsapp', 'page': 1}
{'id': 25620, 'queue': 'discover_fb', 'site': None, 'batch_id': 85, 'requires': '["local"]', 'status': 'pending', 'engine': 'ddg', 'query': 'site:facebook.com/groups 跨境电商 whatsapp', 'page': 1}
```

断言：2 条 ✓（2 词 × 1 页）；requires=`["local"]` ✓；engine=`ddg` ✓；query 逐词正确 ✓；
page=1 ✓；site=NULL ✓。

### 3.2 默认矩阵 5 词 × 1 页（PLAN checkbox 原样路径）

```
POST /api/tasks {"type":"fb_discover","params":{"keywords":"<SPEC §7.4 默认 5 词矩阵>","pages":1}}
→ HTTP 201，task id = 89
POST /api/tasks/89/start → {"ok":true,"queue":"discover_fb","items":5} HTTP 200
```

```
count = 5
25622 site:facebook.com/groups 外贸 whatsapp          engine=ddg page=1
25623 site:facebook.com/groups 跨境电商 whatsapp      engine=ddg page=1
25624 site:facebook.com/groups china sourcing whatsapp engine=ddg page=1
25625 site:facebook.com/groups 货代 微信              engine=ddg page=1
25626 site:facebook.com/groups 亚马逊卖家 微信        engine=ddg page=1
（全部 requires=["local"]、site=NULL、status=pending）
```

断言：**5 条** ✓（默认矩阵 × 1 页，与 PLAN 完全一致）。

## 4. fb_group 任务（API 创建 → start 入队 → 断言）

### 4.1 空表防御路径（生产库 fb_groups 空 → 0 条）

```
POST /api/tasks {"type":"fb_group","params":{"provider":"brightdata","posts_per_group":50}}
→ HTTP 201，task id = 86
POST /api/tasks/86/start → {"ok":true,"queue":"crawl_fb_group","items":0} HTTP 200
```

断言：work_items queue='crawl_fb_group' batch_id=86 → **0 条** ✓（fb_groups 表存在但
无 pending 行；表缺失防御路径由 Step 3.2 单测覆盖）。

### 4.2 手动种子路径（brief 可选：INSERT 1 条 pending → 断言 1 条）

```
INSERT INTO fb_groups (url, group_id, name, source, status, first_seen_at)
VALUES ('https://www.facebook.com/groups/smoke34001/', 'smoke34001', 'smoke-3.4-test-group', 'smoke_test', 'pending', '2026-08-09 22:44:30')
→ seeded id = 1

POST /api/tasks {"type":"fb_group","params":{"provider":"brightdata","posts_per_group":50}}
→ HTTP 201，task id = 88
POST /api/tasks/88/start → {"ok":true,"queue":"crawl_fb_group","items":1} HTTP 200
```

只读断言：

```
count = 1
{'id': 25621, 'queue': 'crawl_fb_group', 'site': None, 'batch_id': 88, 'requires': '["local"]',
 'payload': {'url': 'https://www.facebook.com/groups/smoke34001/', 'provider': 'brightdata', 'limit': 50}}
source fb_groups row: {'id': 1, 'url': 'https://www.facebook.com/groups/smoke34001/', 'status': 'in_progress'}
```

断言：1 条 ✓；payload `{"url","provider":"brightdata","limit":50}` ✓（posts_per_group=50
→ limit=50）；源行 pending→**in_progress** ✓（BEGIN IMMEDIATE 单事务消费互斥）。

**清理（生产库）**：冒烟后删除种子行 + 其派生 work_items，断言库恢复：

```
DELETE FROM fb_groups WHERE id=1 AND source='smoke_test'
DELETE FROM work_items WHERE batch_id=88 AND queue='crawl_fb_group'
→ fb_groups 剩余 0 行；batch 88 剩余 0 行；batch 85（真实任务数据，stopped）保留 2 行
```

## 5. 启动/停止流转验证

| 任务 | 类型 | create | start | stop | 终态 | progress_json |
|---|---|---|---|---|---|---|
| 85 | fb_discover（2 词） | 201 | running, items=2 | ok | **stopped** | total=2, stopped=2 |
| 86 | fb_group（空表防御） | 201 | running, items=0 | ok | **stopped** | total=0, stopped=0（零项停止兜底） |
| 88 | fb_group（种子 1 群） | 201 | running, items=1 | ok | **stopped** | total=1, stopped=1 |
| 89 | fb_discover（默认矩阵） | 201 | running, items=5 | ok | **stopped** | total=5, stopped=5 |

- start：`POST /api/tasks/<id>/start` → status=running + 入队（stop_requested=0）✓
- stop：`POST /api/tasks/<id>/stop` → stop_requested=1 + pending 项压 stopped（sweeper
  兜底），sweeper 派生终态 stopped ✓（86 零项走「无 work_items + stop_requested →
  stopped」兜底分支）
- 全部 4 任务最终 stopped，progress 计数与入队数一致 ✓

## 6. 验收判定

**满足**：

- [x] 重启后端 + 起 daemon 全量（8 队列含 discover_fb/crawl_fb_group 注册）
- [x] API 创建 fb_discover（默认矩阵 × 1 页）→ work_items **5 条**，requires=["local"]、
      engine="ddg"、query 逐词正确、page=1（另有自定义 2 词路径断言 2 条）
- [x] API 创建 fb_group → 空表防御 0 条 + 手动种子 1 条（payload/源行 in_progress 断言）
- [x] 两类型任务可创建/启动/停止，入队断言正确
- [x] SPEC §6.5 start.sh pass-through 两行已追加（grep + syntax 验证），.env gitignore 确认

## 7. 疑虑 / 观测

1. **daemon 未实际消费新队列**：discover_fb/crawl_fb_group 均为 local 消费者，daemon
   调度按冷却/优先级进行，冒烟期间（约 4 分钟）尚未 claim 这两队列的 pending 项
   （1688/mic 重队列在前）。「可创建/启动/停止 + 入队」是本期验收；消费链路
   （DDG 裸抓 / BD key FATAL）已在 Step 1.5 / 2.4 用临时库验证，本期不重复。
2. **stop.sh 子进程残留**：daemon 子进程在 SIGTERM 后存活需 kill -9 手动补刀（pidfile
   记父进程所致，AGENTS.md 已注明该特性，非本 Step 缺陷）。
3. **bash 工具等待长驻子进程**：start.sh 经工具调用会挂到超时并把新起进程一起杀掉；
   需 nohup 脱离调用 shell。这是 harness 调用方式问题，start.sh 幂等逻辑本身正确。
4. 生产库仅做了种子行 INSERT/DELETE（已按 brief 清理并复核），tasks 表留下 4 条
   smoke 任务记录（85/86/88/89，均 stopped）作为冒烟证据，未删除。
5. 任务 86（空表防御）start 后 items=0、无 stop_requested 时 sweeper 不动（保持
   running）；手动 stop 后按零项兜底转 stopped——符合 `_derive_batch_status` 文档化
   语义。
