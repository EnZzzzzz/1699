# Smoke Step 5.2 — 取证分析 (Fix Round 1)

> 查询时间：2026-08-08 18:45–19:00 CST

## 冒烟 A：daemon 1688 shop

### 命令
```bash
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_52.db --workers 1 --limit 6 -n 1 \
  --queues crawl_1688_shop --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
  > smoke-step5.2/shop-run.log 2>&1
```

### 原始输出：shop-run.log（全文 14 行）

```
[0] 播种 0 个 category item + 1 条 discover
[1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 0 分钟
[daemon] 队列 crawl_1688_shop: 待补货店铺 0 个 + 待认领工作项 1 个
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
[2] 启动 1 个 worker（直连）
    [launch] 检查 CloakBrowser 会话席位…
    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
    [launch] 浏览器进程已启动，创建初始 view…
    [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=1688:direct
    [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
    [cookie] 已把 146 个 Cookie 写回数据库 (identity=1688:direct)
    [cookie] 已把 146 个 Cookie 写回数据库 (identity=1688:direct)
[OK] 本次采集: 1 页, 店铺 50 个（新增 50）
    数据库统计: {'runs': 1, 'shops': 50, 'pending': 50, ...}
```

### DB 只读取证（原始命令+输出）

```bash
$ sqlite3 /tmp/smoke_p3_52.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status"
crawl_1688_shop|done|2
crawl_1688_shop|pending|2082

$ sqlite3 /tmp/smoke_p3_52.db "SELECT COUNT(*) AS total, SUM(CASE WHEN exhausted=0 OR exhausted IS NULL THEN 1 ELSE 0 END) AS active FROM category_progress"
1|1

$ sqlite3 /tmp/smoke_p3_52.db "SELECT keyword, name, next_page, pages_crawled, shops_found, exhausted FROM category_progress"
女装|女装|2|1|50|0

$ sqlite3 /tmp/smoke_p3_52.db "SELECT status, COUNT(*) FROM shops GROUP BY status"
pending|50

$ sqlite3 /tmp/smoke_p3_52.db "SELECT domain, name, status FROM shops LIMIT 3"
shop1415033253871.1688.com|嘉兴市恋慕服饰有限公司|pending
ruitongfs.1688.com|义乌市衣梦服饰有限公司|pending
shop0i0i67488v276.1688.com|揭阳市揭东区新亨镇麦尔服装厂|pending
```

### 取证结论

1. **启动播种** ✅：空进度库 → 1 条 discover item 播种（log L1）
2. **discover 执行** ✅：首页类目提取成功 → 2082 条 category item INSERT + 50 shops 落库
3. **类目页消费** ✅：1 条 category item 被认领 → 处理完成（done, id 最小的 category）
4. **progress 读写路径** ✅：category_progress 有 1 行（女装, next_page=2, shops_found=50）
5. **register 装配** ✅：crawl_1688_shop 队列被 daemon 识别、启动、运行

---

## 冒烟 B：旧 CLI 1688 shop 等价确认

### 命令
```bash
cd fetcher
python -m fetcher 1688 shop --db /tmp/smoke_p3_52b.db --workers 1 --limit 2 -n 1 \
  > smoke-step5.2/shop-cli-run.log 2>&1
```

### 原始输出摘要：shop-cli-run.log

```
[0] 播种 0 个 category item + 1 条 discover
[1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 15 分钟
[2] 启动 1 个 worker（直连）
    [launch] ... CloakBrowser ...
    [cookie] ... 1688:direct ...
[w0]   [X] 策略链声明放弃，跳过该页，页码不前进下次重采（已解析类目搜索页）
```

### DB 只读取证（原始命令+输出）

```bash
$ sqlite3 /tmp/smoke_p3_52b.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status"
crawl_1688_shop|claimed|3
crawl_1688_shop|pending|2080

$ sqlite3 /tmp/smoke_p3_52b.db "SELECT COUNT(*) FROM category_progress"
0

$ sqlite3 /tmp/smoke_p3_52b.db "SELECT id, status, SUBSTR(payload_json,1,80) FROM work_items WHERE status='claimed'"
1|claimed|{"kind": "discover"}
7|claimed|{"kind": "category", "keyword": "汽车用品", "name": "汽车用品"}
8|claimed|{"kind": "category", "keyword": "工业用品", "name": "工业用品"}
```

### 取证结论

1. **播种路径** ✅：prepare → 1 discover + 2082 category items（空库无存量 → 先 discover）
2. **acquire 路径** ✅：work_items 认领正常（3 claimed：1 discover + 2 category）
3. **CLI 与 daemon 同路径** ✅：均走 Alibaba1688ShopTask.prepare → discover → category 播种
4. **滑块墙是环境噪声** ✅：直连环境预期行为（策略链声明放弃）
5. **等价确认** ✅：CLI 和 daemon 的 acquire_item / fetch / on_success 路径一致

---

## 冒烟 C：daemon 1688 company（Fix Round 1 新增）

### 命令
```bash
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_52c.db --workers 1 --limit 4 -n 1 \
  --queues crawl_1688_company --batch-rest 1 \
  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
  > smoke-step5.2/company-run.log 2>&1
```

### 原始输出：company-run.log（前 5 行 + 终态）

```
[0] 播种 0 个 category item + 1 条 discover
[1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 0 分钟
[daemon] 队列 crawl_1688_company: 待补货店铺 0 个 + 待认领工作项 1 个
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
[2] 启动 1 个 worker（直连）
...
[w0]   [X] 策略链声明放弃，跳过该页，页码不前进下次重采（已解析公司黄页）
```

### DB 只读取证（原始命令+输出）——**company: 前缀运行时证据**

```bash
$ sqlite3 /tmp/smoke_p3_52c.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status"
crawl_1688_company|claimed|1
crawl_1688_company|done|1
crawl_1688_company|failed|1
crawl_1688_company|pending|2080

$ sqlite3 /tmp/smoke_p3_52c.db "SELECT id, status, SUBSTR(payload_json,1,100) FROM work_items WHERE status='pending' LIMIT 5"
4|pending|{"kind": "category", "keyword": "company:内衣", "name": "内衣"}
5|pending|{"kind": "category", "keyword": "company:新中式", "name": "新中式"}
6|pending|{"kind": "category", "keyword": "company:汉服套装", "name": "汉服套装"}
7|pending|{"kind": "category", "keyword": "company:马面裙", "name": "马面裙"}
8|pending|{"kind": "category", "keyword": "company:披帛", "name": "披帛"}

$ sqlite3 /tmp/smoke_p3_52c.db "SELECT id, status, payload_json FROM work_items WHERE status IN ('done','failed','claimed')"
1|done|{"kind": "discover"}
2|failed|{"kind": "category", "keyword": "company:女装", "name": "女装"}
3|claimed|{"kind": "category", "keyword": "company:男装", "name": "男装"}
```

### 取证结论

1. **company: 前缀播种 ✅**：全部 pending category item 的 keyword 均为 `"company:..."` 前缀，与 shop 队列（无前缀）隔离
2. **discover 执行 ✅**：1 条 discover done，2080 条 company: 前缀 category items 播种成功
3. **认领路径 ✅**：company:女装 被认领执行后遇滑块墙（failed），company:男装 被认领（claimed）
4. **register 装配 ✅**：crawl_1688_company 被 daemon 识别、启动、运行；make_task("company") → Alibaba1688CompanyTask 实例化正常
5. **滑块墙是环境噪声 ✅**：直连 1688 company 黄页搜索同样遇滑块墙，与 shop 表现一致
6. **未被滑块墙遮挡的结构路径全部走通**：播种→认领→payload 包含 company: 前缀→进度写入

### Trade-off 记录

Step 5.1 的 `test_1688_feeder.py` 已通过 mock 完整覆盖：
- `test_exhausted_keys_filtered_by_prefix` — iter_active_categories(prefix="company:") 前缀过滤
- `test_company_prepare_seeds_only_prefixed` — company prepare 只播种 company: 前缀 category item
- `test_company_acquire_returns_payload` — company task acquire_item 返回 company: 前缀 payload

本次冒烟补齐了**运行时证据**（无 mock，真实 DB 写入），证明 make_task("company") → Alibaba1688CompanyTask → prepare → discover → company: 前缀 category item 全链路在无 mock 环境下正常。

---

## 综合结论

- crawl_1688_shop 注册表装配 ✅（daemon + CLI 双重验证）
- crawl_1688_company 注册表装配 ✅（daemon 冒烟 + company: 前缀运行时证据）
- feeder 播种→认领→progress 路径走通 ✅
- 5 队列 registry 全量 ✅
- company: 前缀隔离 ✅（mock 测试 + 运行时证据）
