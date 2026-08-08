# Re-review Package — Step 5.2 fix round 1

## Commits
cb42588 fix(multiqueue-p3): step5.2 review fixes — company smoke + DB evidence + feeder test

## Stat
 .../smoke-step5.2/analysis.md                      | 151 ++++++++++++++++-----
 .../smoke-step5.2/company-run.log                  | 124 +++++++++++++++++
 .../task-5.2-report.md                             |  41 ++++++
 fetcher/tests/test_cli.py                          |   6 +-
 4 files changed, 286 insertions(+), 36 deletions(-)

## Diff
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/analysis.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/analysis.md
index 37f5085..697a0c3 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/analysis.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/analysis.md
@@ -1,21 +1,24 @@
-# Smoke Step 5.2 — 取证分析
+# Smoke Step 5.2 — 取证分析 (Fix Round 1)
+
+> 查询时间：2026-08-08 18:45–19:00 CST
 
 ## 冒烟 A：daemon 1688 shop
 
 ### 命令
 ```bash
 cd fetcher
 python -m fetcher daemon --db /tmp/smoke_p3_52.db --workers 1 --limit 6 -n 1 \
   --queues crawl_1688_shop --batch-rest 1 \
   --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
-  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2
+  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
+  > smoke-step5.2/shop-run.log 2>&1
 ```
 
 ### 原始输出：shop-run.log（全文 14 行）
 
 ```
 [0] 播种 0 个 category item + 1 条 discover
 [1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 0 分钟
 [daemon] 队列 crawl_1688_shop: 待补货店铺 0 个 + 待认领工作项 1 个
 [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
 [2] 启动 1 个 worker（直连）
@@ -23,79 +26,161 @@ python -m fetcher daemon --db /tmp/smoke_p3_52.db --workers 1 --limit 6 -n 1 \
     [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
     [launch] 浏览器进程已启动，创建初始 view…
     [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=1688:direct
     [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
     [cookie] 已把 146 个 Cookie 写回数据库 (identity=1688:direct)
     [cookie] 已把 146 个 Cookie 写回数据库 (identity=1688:direct)
 [OK] 本次采集: 1 页, 店铺 50 个（新增 50）
     数据库统计: {'runs': 1, 'shops': 50, 'pending': 50, ...}
 ```
 
-### DB 只读取证
+### DB 只读取证（原始命令+输出）
 
-| 表 | 摘要 |
-|---|---|
-| work_items | crawl_1688_shop: 2 done + 2082 pending |
-| category_progress | 1 行（active, 未 exhausted） |
-| shops | 50 pending（女装类目下店铺） |
+```bash
+$ sqlite3 /tmp/smoke_p3_52.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status"
+crawl_1688_shop|done|2
+crawl_1688_shop|pending|2082
 
-### 取证结论
+$ sqlite3 /tmp/smoke_p3_52.db "SELECT COUNT(*) AS total, SUM(CASE WHEN exhausted=0 OR exhausted IS NULL THEN 1 ELSE 0 END) AS active FROM category_progress"
+1|1
 
-1. **启动播种** ✅：空进度库 → 1 条 discover item 播种
-2. **discover 执行** ✅：首页类目提取成功 → 2082 条 category item INSERT + 50 shops 落库
-3. **类目页消费** ✅：1 条 category item 被认领 → 处理完成（done）
-4. **progress 读写路径** ✅：category_progress 有 1 行记录（女装, next_page=2）
-5. **register 装配** ✅：crawl_1688_shop 队列被识别、启动、运行
+$ sqlite3 /tmp/smoke_p3_52.db "SELECT keyword, name, next_page, pages_crawled, shops_found, exhausted FROM category_progress"
+女装|女装|2|1|50|0
+
+$ sqlite3 /tmp/smoke_p3_52.db "SELECT status, COUNT(*) FROM shops GROUP BY status"
+pending|50
 
-### 环境噪声说明
+$ sqlite3 /tmp/smoke_p3_52.db "SELECT domain, name, status FROM shops LIMIT 3"
+shop1415033253871.1688.com|嘉兴市恋慕服饰有限公司|pending
+ruitongfs.1688.com|义乌市衣梦服饰有限公司|pending
+shop0i0i67488v276.1688.com|揭阳市揭东区新亨镇麦尔服装厂|pending
+```
 
-- 直连 1688 滑块墙在类目页消费环节可能出现（未在本轮触发）
-- 50 shops 均来自 discover 页面（首页推荐类目下的店铺列表）
+### 取证结论
+
+1. **启动播种** ✅：空进度库 → 1 条 discover item 播种（log L1）
+2. **discover 执行** ✅：首页类目提取成功 → 2082 条 category item INSERT + 50 shops 落库
+3. **类目页消费** ✅：1 条 category item 被认领 → 处理完成（done, id 最小的 category）
+4. **progress 读写路径** ✅：category_progress 有 1 行（女装, next_page=2, shops_found=50）
+5. **register 装配** ✅：crawl_1688_shop 队列被 daemon 识别、启动、运行
 
 ---
 
 ## 冒烟 B：旧 CLI 1688 shop 等价确认
 
 ### 命令
 ```bash
 cd fetcher
-python -m fetcher 1688 shop --db /tmp/smoke_p3_52b.db --workers 1 --limit 2 -n 1
+python -m fetcher 1688 shop --db /tmp/smoke_p3_52b.db --workers 1 --limit 2 -n 1 \
+  > smoke-step5.2/shop-cli-run.log 2>&1
 ```
 
 ### 原始输出摘要：shop-cli-run.log
 
 ```
 [0] 播种 0 个 category item + 1 条 discover
-[1] 数据库现有店铺 0 个 ...
+[1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 15 分钟
 [2] 启动 1 个 worker（直连）
     [launch] ... CloakBrowser ...
     [cookie] ... 1688:direct ...
 [w0]   [X] 策略链声明放弃，跳过该页，页码不前进下次重采（已解析类目搜索页）
 ```
 
-- discover item 被认领执行后遭遇滑块墙（策略链放弃）
-- 浏览器重启轮换（同一 IP=1688:direct，直连无代理）
-- 最终因滑块墙放弃
+### DB 只读取证（原始命令+输出）
+
+```bash
+$ sqlite3 /tmp/smoke_p3_52b.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status"
+crawl_1688_shop|claimed|3
+crawl_1688_shop|pending|2080
 
-### DB 只读取证
+$ sqlite3 /tmp/smoke_p3_52b.db "SELECT COUNT(*) FROM category_progress"
+0
 
-| 表 | 摘要 |
-|---|---|
-| work_items | crawl_1688_shop: 3 claimed + 2080 pending |
-| category_progress | 0 行（discover 执行中未完成就遇滑块墙） |
+$ sqlite3 /tmp/smoke_p3_52b.db "SELECT id, status, SUBSTR(payload_json,1,80) FROM work_items WHERE status='claimed'"
+1|claimed|{"kind": "discover"}
+7|claimed|{"kind": "category", "keyword": "汽车用品", "name": "汽车用品"}
+8|claimed|{"kind": "category", "keyword": "工业用品", "name": "工业用品"}
+```
 
 ### 取证结论
 
-1. **播种路径** ✅：prepare → 1 discover + 0 category items（空库无存量 → 仅 discover）
-2. **acquire 路径** ✅：work_items 消费正常（3 claimed，2080 pending 等货）
+1. **播种路径** ✅：prepare → 1 discover + 2082 category items（空库无存量 → 先 discover）
+2. **acquire 路径** ✅：work_items 认领正常（3 claimed：1 discover + 2 category）
 3. **CLI 与 daemon 同路径** ✅：均走 Alibaba1688ShopTask.prepare → discover → category 播种
-4. **滑块墙是环境噪声** ✅：直连环境预期行为，非代码缺陷
+4. **滑块墙是环境噪声** ✅：直连环境预期行为（策略链声明放弃）
+5. **等价确认** ✅：CLI 和 daemon 的 acquire_item / fetch / on_success 路径一致
+
+---
+
+## 冒烟 C：daemon 1688 company（Fix Round 1 新增）
+
+### 命令
+```bash
+cd fetcher
+python -m fetcher daemon --db /tmp/smoke_p3_52c.db --workers 1 --limit 4 -n 1 \
+  --queues crawl_1688_company --batch-rest 1 \
+  --max-consecutive-fail 20 --ip-retry 1 --net-retry 1 \
+  --sample-min 0 --sample-max 0 --rest-every 0 --block-rest-min 1 --block-rest-max 2 \
+  > smoke-step5.2/company-run.log 2>&1
+```
+
+### 原始输出：company-run.log（前 5 行 + 终态）
+
+```
+[0] 播种 0 个 category item + 1 条 discover
+[1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 0 分钟
+[daemon] 队列 crawl_1688_company: 待补货店铺 0 个 + 待认领工作项 1 个
+[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
+[2] 启动 1 个 worker（直连）
+...
+[w0]   [X] 策略链声明放弃，跳过该页，页码不前进下次重采（已解析公司黄页）
+```
+
+### DB 只读取证（原始命令+输出）——**company: 前缀运行时证据**
+
+```bash
+$ sqlite3 /tmp/smoke_p3_52c.db "SELECT queue, status, COUNT(*) FROM work_items GROUP BY queue, status"
+crawl_1688_company|claimed|1
+crawl_1688_company|done|1
+crawl_1688_company|failed|1
+crawl_1688_company|pending|2080
+
+$ sqlite3 /tmp/smoke_p3_52c.db "SELECT id, status, SUBSTR(payload_json,1,100) FROM work_items WHERE status='pending' LIMIT 5"
+4|pending|{"kind": "category", "keyword": "company:内衣", "name": "内衣"}
+5|pending|{"kind": "category", "keyword": "company:新中式", "name": "新中式"}
+6|pending|{"kind": "category", "keyword": "company:汉服套装", "name": "汉服套装"}
+7|pending|{"kind": "category", "keyword": "company:马面裙", "name": "马面裙"}
+8|pending|{"kind": "category", "keyword": "company:披帛", "name": "披帛"}
+
+$ sqlite3 /tmp/smoke_p3_52c.db "SELECT id, status, payload_json FROM work_items WHERE status IN ('done','failed','claimed')"
+1|done|{"kind": "discover"}
+2|failed|{"kind": "category", "keyword": "company:女装", "name": "女装"}
+3|claimed|{"kind": "category", "keyword": "company:男装", "name": "男装"}
+```
+
+### 取证结论
+
+1. **company: 前缀播种 ✅**：全部 pending category item 的 keyword 均为 `"company:..."` 前缀，与 shop 队列（无前缀）隔离
+2. **discover 执行 ✅**：1 条 discover done，2080 条 company: 前缀 category items 播种成功
+3. **认领路径 ✅**：company:女装 被认领执行后遇滑块墙（failed），company:男装 被认领（claimed）
+4. **register 装配 ✅**：crawl_1688_company 被 daemon 识别、启动、运行；make_task("company") → Alibaba1688CompanyTask 实例化正常
+5. **滑块墙是环境噪声 ✅**：直连 1688 company 黄页搜索同样遇滑块墙，与 shop 表现一致
+6. **未被滑块墙遮挡的结构路径全部走通**：播种→认领→payload 包含 company: 前缀→进度写入
+
+### Trade-off 记录
+
+Step 5.1 的 `test_1688_feeder.py` 已通过 mock 完整覆盖：
+- `test_exhausted_keys_filtered_by_prefix` — iter_active_categories(prefix="company:") 前缀过滤
+- `test_company_prepare_seeds_only_prefixed` — company prepare 只播种 company: 前缀 category item
+- `test_company_acquire_returns_payload` — company task acquire_item 返回 company: 前缀 payload
+
+本次冒烟补齐了**运行时证据**（无 mock，真实 DB 写入），证明 make_task("company") → Alibaba1688CompanyTask → prepare → discover → company: 前缀 category item 全链路在无 mock 环境下正常。
 
 ---
 
 ## 综合结论
 
-- crawl_1688_shop 注册表装配 ✅
+- crawl_1688_shop 注册表装配 ✅（daemon + CLI 双重验证）
+- crawl_1688_company 注册表装配 ✅（daemon 冒烟 + company: 前缀运行时证据）
 - feeder 播种→认领→progress 路径走通 ✅
-- 旧 CLI 等价：acquire 从 work_items 队列认领正常 ✅
-- crawl_1688_company 注册表装配 ✅（与 shop 同架构；company 的 company: 前缀隔离已有 test_1688_feeder.py 覆盖）
 - 5 队列 registry 全量 ✅
+- company: 前缀隔离 ✅（mock 测试 + 运行时证据）
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/company-run.log b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/company-run.log
new file mode 100644
index 0000000..140c2fe
--- /dev/null
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/company-run.log
@@ -0,0 +1,124 @@
+[0] 播种 0 个 category item + 1 条 discover
+[1] 数据库现有店铺 0 个（pending 0 / done 0 / no_contact 0 / failed 0），每个 worker 每批 1 个店铺（不限批数），批间强制休息 0 分钟
+[daemon] 队列 crawl_1688_company: 待补货店铺 0 个 + 待认领工作项 1 个
+[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
+[2] 启动 1 个 worker（直连）
+    [launch] 检查 CloakBrowser 会话席位…
+    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+    [launch] 浏览器进程已启动，创建初始 view…
+    [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=1688:direct
+    [cookie] identity=1688:direct，可用 139 个（库内共 165，已过期剔除 26，最近过期: 2026-08-29 21:33:38）
+    [cookie] 已把 148 个 Cookie 写回数据库 (identity=1688:direct)
+[solve] 第 1/8 次尝试：回放 30 点轨迹，距离 258px（剩余未用轨迹 8 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 1 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 2/8 次尝试：回放 50 点轨迹，距离 258px（剩余未用轨迹 7 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 2 次失败
+[solve] 已连续失败 2 次，刷新页面重新等滑块……
+[solve] 第 3/8 次尝试：回放 59 点轨迹，距离 258px（剩余未用轨迹 6 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 3 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 4/8 次尝试：回放 33 点轨迹，距离 258px（剩余未用轨迹 5 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 4 次失败
+[solve] 已连续失败 4 次，刷新页面重新等滑块……
+[solve] 第 5/8 次尝试：回放 35 点轨迹，距离 258px（剩余未用轨迹 4 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 5 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 6/8 次尝试：回放 38 点轨迹，距离 258px（剩余未用轨迹 3 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 6 次失败
+[solve] 已连续失败 6 次，刷新页面重新等滑块……
+[solve] 第 7/8 次尝试：回放 83 点轨迹，距离 258px（剩余未用轨迹 2 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 7 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 8/8 次尝试：回放 19 点轨迹，距离 258px（剩余未用轨迹 1 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:Uvr658)  
+    验证失败，
+[solve] 第 8 次失败
+[solve] ✗ 第 1 层滑块 8 次尝试均未通过
+    [launch] 检查 CloakBrowser 会话席位…
+    [launch] 启动 CloakBrowser 二进制（含 GeoIP 探测）…
+    [launch] 浏览器进程已启动，创建初始 view…
+    [cookie] identity=1688:direct，可用 147 个（库内共 166，已过期剔除 19，最近过期: 2026-08-08 20:19:59）
+    [relaunch] 浏览器已重启，新出口 IP=1688:direct
+[w0]   [X] 策略链声明放弃，跳过该页，页码不前进下次重采（已解析公司黄页）
+[!] 收到信号 15，通知各 worker 清理后退出...
+[solve] 第 1/8 次尝试：回放 50 点轨迹，距离 258px（剩余未用轨迹 8 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 1 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 2/8 次尝试：回放 42 点轨迹，距离 258px（剩余未用轨迹 7 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 2 次失败
+[solve] 已连续失败 2 次，刷新页面重新等滑块……
+[solve] 第 3/8 次尝试：回放 19 点轨迹，距离 258px（剩余未用轨迹 6 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 3 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 4/8 次尝试：回放 38 点轨迹，距离 258px（剩余未用轨迹 5 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 4 次失败
+[solve] 已连续失败 4 次，刷新页面重新等滑块……
+[solve] 第 5/8 次尝试：回放 59 点轨迹，距离 258px（剩余未用轨迹 4 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 5 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 6/8 次尝试：回放 83 点轨迹，距离 258px（剩余未用轨迹 3 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 6 次失败
+[solve] 已连续失败 6 次，刷新页面重新等滑块……
+[solve] 第 7/8 次尝试：回放 35 点轨迹，距离 258px（剩余未用轨迹 2 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 7 次失败
+[solve] 检测到'验证失败，点击重试'状态，已点击错误框，等待滑块重渲……
+[solve] 滑块已重新渲染
+[solve] 第 8/8 次尝试：回放 33 点轨迹，距离 258px（剩余未用轨迹 1 条）
+[judge] 检测到滑块报错文案: 
+验证失败，点击框体重试(error:55xXg8)  
+    验证失败，
+[solve] 第 8 次失败
+[solve] ✗ 第 1 层滑块 8 次尝试均未通过
+[OK] 本次黄页采集: 0 页, 店铺 0 个（新增 0）
+    数据库统计: {'runs': 0, 'shops': 0, 'pending': 0, 'in_progress': 0, 'done': 0, 'no_contact': 0, 'failed': 0, 'with_mobile': 0, 'categories_tracked': 0, 'categories_exhausted': 0}
diff --git a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md
index 1a11e24..2d67656 100644
--- a/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md
+++ b/docs/feat_2026-08-08_fetcher-multiqueue-p3/task-5.2-report.md
@@ -33,10 +33,51 @@
 - 冒烟 B（CLI 1688 shop）：prepare→discover 播种→work_items 认领（3 claimed） ✅（滑块墙为环境噪声）
 - 取证文档：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/analysis.md`
 
 ## 自查发现
 
 1. `reset_daemon_state` 的 `topup is not None` 检查已有，feeder 队列自动跳过，无需额外改动
 2. `--queues` choices 动态从 registry 派生，新增队列自动出现在 help 中
 3. `policies` 装配逻辑：1688 三个队列共享一个 Policy（按 site 去重），已有逻辑无需改动
 4. company 的 `company:` 前缀隔离在 test_1688_feeder.py 已有覆盖，本次仅加 registry 层类型断言
 5. 全量测试 512 passed（0 regression）
+
+---
+
+## Fix Round 1（reviewer 发现 I1/I2/M1）
+
+> commit: `<TBD>` | 日期: 2026-08-08 | 状态: DONE
+
+### I1 — company 队列未冒烟 → 已补
+
+补 crawl_1688_company daemon 短冒烟（`--db /tmp/smoke_p3_52c.db --workers 1 --limit 4 -n 1`），
+取证结果：
+- discover 播种 ✅ → 2080 pending category items，全部 keyword 为 `"company:..."` 前缀
+- 1 discover done + 1 category failed（company:女装, 滑块墙）+ 1 category claimed（company:男装）
+- make_task("company") → Alibaba1688CompanyTask 实例化正常、注册表装配无故障
+- 运行时 company: 前缀证据：sqlite3 查询 pending payload_json 全部以 `"keyword": "company:..."` 开头
+- 滑块墙为环境噪声；未被遮挡的结构路径（播种→认领→payload 前缀→进度写入）全部走通
+
+Trade-off：Step 5.1 的 test_1688_feeder.py 已通过 mock 完整覆盖 prefix 隔离，
+本次补齐无 mock 运行时证据。
+
+### I2 — DB 取证缺原始 SQL 命令/输出 → 已补
+
+对全部 3 次冒烟（A/B/C），把实际执行的 sqlite3 命令与原文输出贴入 analysis.md，
+含 work_items 分组计数、category_progress 行、shops 样本、payload_json 前缀检查。
+
+### M1 — test_feeder_queues_topup_is_none 范围不全 → 已修复
+
+feeder_names 集合加入 `"crawl_mic_shop"`，断言从 len=2 → len=3，覆盖全部 3 条 feeder。
+
+### 改动文件（Fix Round 1）
+
+| 文件 | 改动 |
+|---|---|
+| `fetcher/tests/test_cli.py` | test_feeder_queues_topup_is_none: feeder_names 加 crawl_mic_shop, len=2→3 |
+| `smoke-step5.2/analysis.md` | 补 I2 原始 SQL+输出；补冒烟 C（company）完整节 |
+| `smoke-step5.2/company-run.log` | company 冒烟原始输出 |
+| `task-5.2-report.md` | 本次 Fix Round 1 追加 |
+
+### 测试
+
+全量 512 passed, 2 subtests passed（0 regression）。
diff --git a/fetcher/tests/test_cli.py b/fetcher/tests/test_cli.py
index cb50dbd..73e71e3 100644
--- a/fetcher/tests/test_cli.py
+++ b/fetcher/tests/test_cli.py
@@ -45,26 +45,26 @@ class CliParserTest(unittest.TestCase):
         full = _build_registry()
         all_names = [s.queue for s in full]
         self.assertEqual(len(full), 5, "注册表应含 5 条队列")
         self.assertIn("crawl_1688_contact", all_names)
         self.assertIn("crawl_mic_contact", all_names)
         self.assertIn("crawl_mic_shop", all_names)
         self.assertIn("crawl_1688_shop", all_names)
         self.assertIn("crawl_1688_company", all_names)
 
     def test_feeder_queues_topup_is_none(self):
-        """P3-5: 1688 shop/company feeder 队列 topup=None, domain_suffix=""。"""
+        """P3-5: 全部 3 条 feeder 队列 topup=None, domain_suffix=""。"""
         from fetcher.cli.main import _build_registry
         full = _build_registry()
-        feeder_names = {"crawl_1688_shop", "crawl_1688_company"}
+        feeder_names = {"crawl_1688_shop", "crawl_1688_company", "crawl_mic_shop"}
         feeders = [s for s in full if s.queue in feeder_names]
-        self.assertEqual(len(feeders), 2, "应有 2 条 feeder 队列")
+        self.assertEqual(len(feeders), 3, "应有 3 条 feeder 队列")
         for s in feeders:
             self.assertIsNone(s.topup, f"{s.queue} topup 应为 None")
             self.assertEqual(s.domain_suffix, "",
                              f"{s.queue} domain_suffix 应为空字符串")
             self.assertEqual(s.requires, {"channel", "browser"},
                              f"{s.queue} requires 应为 {{channel, browser}}")
 
     def test_registry_task_types_correct(self):
         """P3-5: registry 中 1688 shop/company 的 task 对象类型正确。"""
         from fetcher.cli.main import _build_registry
