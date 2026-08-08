# Smoke Step 4.2 — 冒烟分析

## 环境

- 命令：`python -m fetcher daemon --db /tmp/smoke_p3_42.db --workers 1 --limit 8 -n 1 --queues crawl_mic_shop --batch-rest 1 --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2`
- 临时库 `/tmp/smoke_p3_42.db`（空库启动）
- 直连、1 worker、1 batch、limit 8（每批最多 8 个工作项）
- Dummy cookie `madeinchina:direct`（1 条，避免 ensure_site 直连报错）

## 取证要点

### 1. 启动播种 ✅

```
[0] 播种 0 个 category item + 1 条 discover
```

category_progress 空 → `_seed_category_items` 经 `iter_active_categories` → 0 条未采完类目 → 无 category item 播种；`_seed_discover_item` 插 1 条 discover item（powered 幂等）。

验证：work_items 表中仅 1 条 pending discover item（daemon 日志第一行）。

### 2. 启动重置 ✅

```
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
```

- claimed item 回收 = 0（无残留）
- in_progress 重置 = 0：feeder 队列 topup=None，`reset_daemon_state` 正确跳过 `reset_in_progress`（逐 site 打印空——仅 contact 队列才参与）

验证：`reset_daemon_state` 新增 `if spec.topup is not None` 条件生效。

### 3. Discover 执行 ✅

discover item 被认领 → fetch 返回 `{"discover": True}` → on_success 执行类目提取：
- 浏览首页 `https://www.made-in-china.com/` + 市场导航页 `https://www.made-in-china.com/shichang/`
- 提取类目 → 逐条 INSERT category item

#### DB 取证（sqlite3 只读，2026-08-08 修复 I2 时补充）

```sql
-- work_items: category vs 其他 pending 计数
SELECT payload_json FROM work_items
WHERE queue='crawl_mic_shop' AND status='pending';
-- 按 kind 分组统计：
--   category: 1053
--   total pending: 1053
--   status=done: 2 (discover + jgdbj page 1)
--   status=pending: 1053
```

### 4. 类目页消费 ✅

category item `jgdbj`（激光打标机）被认领 → `_fetch_category` 抓取 market 页 → 提取 15 个供应商展厅 → shops 落库。

```
[OK] 本次采集: 1 页, 店铺 15 个（新增 15）
```

#### DB 取证

```sql
-- category_progress 推进值
SELECT keyword, name, next_page, pages_crawled, shops_found, exhausted, last_crawled_at
FROM category_progress WHERE keyword='jgdbj';
-- jgdbj|激光打标机|2|1|15|0|2026-08-08 18:14:13

-- shops 落库
SELECT COUNT(*) AS total, status FROM shops
WHERE domain LIKE '%made-in-china.com%' GROUP BY status;
-- 15|pending

-- 店铺采样
SELECT domain, name, status FROM shops ORDER BY id LIMIT 3;
-- jixie.cn.made-in-china.com|机械设备|pending
-- daxian0607.cn.made-in-china.com|2012-07-05|pending
-- pazhajicom.cn.made-in-china.com|2014-10-24|pending
```

### 5. Category progress 推进 ✅

`advance_category_page` 正确推进：
- next_page: 1→2
- pages_crawled: 0→1
- shops_found: 0→15
- exhausted=0（非空页）

### 6. 链式续喂 ✅

`on_success` 在 jgdbj 页 1 成功后 INSERT 同 payload 下一页 item（attempts=0）：

```sql
-- jgdbj 相关 work_items
SELECT payload_json, status FROM work_items
WHERE queue='crawl_mic_shop' AND payload_json LIKE '%jgdbj%';
-- kind=category keyword=jgdbj fmt=plain status=done     ← 页 1（已消费）
-- kind=category keyword=jgdbj fmt=plain status=pending   ← 页 2（链式续喂）
```

由于 `-n 1 --limit 8`，daemon 在完成第 1 批后退出，页 2 未被认领但 item 已插入。

### 7. 环境噪声

- 浏览器正常启动（CloakBrowser 二进制已存在）
- ensure_site 成功装载 dummy cookie → 无报错
- market 页面成功加载并提取类目列表（网络通畅）
- 无滑块/风控拦截（常规浏览行为）

## 结论

播种→discover→类目页消费→progress 推进 路径全部走通，`iter_active_categories` 统一查询与 `crawl_mic_shop` 注册表正确接入。feeder 队列不触发 `reset_in_progress` 的条件防护验证通过。
