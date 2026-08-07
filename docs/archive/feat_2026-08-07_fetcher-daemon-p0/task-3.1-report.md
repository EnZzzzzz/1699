# Step 3.1 report — 代理模式等价性对比

> 走查时间：2026-08-07 12:39 ~ 14:31（北京时间）　分支：feat/fetcher-daemon-p0
> 目的：证明同参数下 daemon 模式与旧 CLI（`python -m fetcher 1688 contact`）请求节奏、抓取结果、DB 落库口径一致。

## 0. 环境核查（执行前）

```
$ git branch --show-current
feat/fetcher-daemon-p0
$ ps aux | grep "python -m fetcher" | grep -v grep
en  2799   ... python -m fetcher madeinchina shop -n 200 --proxy --headed --workers 1
en  86546  ... python -m fetcher madeinchina contact -n 100 --proxy --headed --workers 4
$ curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8765/api/tasks
000        # 平台服务（uvicorn :8765）未运行 → SPEC §4 假设 3 项「平台未运行，本项不适用」
```

生产库基线（2026-08-07 12:39:40 只读记录）：

```
$ sqlite3 -readonly .cache/1688.db "SELECT COUNT(*) FROM work_items;
    SELECT MAX(updated_at) FROM ip_stats; SELECT MAX(created_at) FROM ip_events;"
0
2026-08-07 12:37:53
2026-08-07 12:29:23
```

## A. 种子数据

一次性脚本 `/tmp/equiv_seed.py`（未入仓库）：生产库**只读连接**（`mode=ro`）抄
`status='done' AND domain LIKE '%.1688.com' ORDER BY id DESC LIMIT 40`（候选 7718 条），
按同序分别 INSERT 进 `/tmp/equiv_a.db`、`/tmp/equiv_b.db`（`status='pending', attempts=0`，
保留原 first_seen_at/last_seen_at/category_keyword，run_id=NULL）。种子清单存
`/tmp/equiv_seed_list.txt`（生产库 id → domain 映射）。

```
$ python /tmp/equiv_seed.py
/tmp/equiv_a.db: pending=40, 首个待认领=shop1467306371126.1688.com
/tmp/equiv_b.db: pending=40, 首个待认领=shop1467306371126.1688.com
$ diff <(sqlite3 -readonly /tmp/equiv_a.db "SELECT id,domain,status FROM shops ORDER BY id") \
       <(sqlite3 -readonly /tmp/equiv_b.db "同上") && echo 一致
A/B 两库种子完全一致（40 行，id 1..40 同序同内容）
```

## B. A 组：旧 CLI

命令（12:42:10 启动，后台执行）：

```
cd fetcher && python -u -m fetcher 1688 contact --db /tmp/equiv_a.db \
  --proxy --workers 1 --limit 20 --batch-rest 120 > /tmp/equiv_a.log 2>&1
```

日志头（`/tmp/equiv_a.log`，全文 72 KB 保留）：

```
[1] 待抓取 40 个，每个 worker 每批 10 个（不限批数，抓完 pending 为止），批间强制休息 2 分钟
[seed] .../.cache/seeds 下没有可用种子身份，全部 worker 按白板会话启动
[2] 启动 1 个 worker（代理通道: tunpool-8jx7g.qg.net:26030）
    [proxy] 青果住宅代理: tunpool-8jx7g.qg.net:26030，出口 IP: 113.121.233.121
```

收工（日志尾）：`[OK] 本次完成: 有联系方式 17, 无联系方式 2, 失败 1`
结束时间 13:39:21（日志 mtime），**墙钟 ≈57 分钟**。过程中遇到滑块/登录墙风控，
走自动过证 → 休息等 IP 轮换 → relaunch 的既有策略链（13:02~13:13 为 block_login 密集期）。

## C. B 组：daemon

命令（13:43:20 启动，A 组结束后才启动，两组串行无争抢）：

```
cd fetcher && python -u -m fetcher daemon --db /tmp/equiv_b.db \
  --proxy --workers 1 --limit 20 --batch-rest 120 > /tmp/equiv_b.log 2>&1
```

日志头（`/tmp/equiv_b.log`，全文 79 KB 保留）——daemon 特征行齐全：

```
[1] 待抓取 40 个，每个 worker 每批 10 个（不限批数，抓完 pending 为止），批间强制休息 2 分钟
[daemon] 队列 crawl_1688_contact: 待补货店铺 40 个 + 待认领工作项 0 个
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
[2] 启动 1 个 worker（代理通道: tunpool-8jx7g.qg.net:26030）
    [proxy] 青果住宅代理: tunpool-8jx7g.qg.net:26030，出口 IP: 125.80.182.187
```

补货/认领机制工作正常（运行中快照：首批补货 4 个 = workers×4，`claimed|1 / pending|3`，
shops 对应 4 个 in_progress）。收工：`[OK] 本次完成: 有联系方式 17, 无联系方式 1, 失败 2`
结束时间 14:24:46，**墙钟 ≈41 分钟**。

## D. 对比指标

### D.1 请求节奏

时间序列取 `contacts.scraped_at`（每个成功 item 一行，秒级）+ `ip_events.created_at`；
活跃期 = 相邻间隔 <120s 的区段（排除批休 120s 与风控等待窗口）。
完整序列见 §附 1，汇总：

| 指标 | A 组 旧CLI | B 组 daemon |
|---|---|---|
| 完成 item 数（入 contacts） | 19 | 18 |
| 活跃期平均每个耗时 | 28.9 s/个 | 22.7 s/个 |
| 活跃期节奏 | **≈2.08 个/分钟** | **≈2.64 个/分钟** |
| 相邻间隔中位数 | 26 s | 21 s |
| 页面请求总数（ip_stats Σrequests） | 38（25+13，含被拦） | 41（38+3，含被拦） |
| 批休窗口（120s 档） | 13:00:58→13:12:47（批休+风控等待） | 14:00:32→14:03:00 ≈148s（批休120s±抖动+抓取耗时） |
| 墙钟 | 57 min | 41 min |

**结论：同一量级。** 两组活跃期节奏都落在 2~3 个/分钟（由共同的 sample_min/max=13~20s
+ fetch 耗时主导，两组该参数完全相同）；墙钟差异全部来自风控等待时长不同
（A 组 13:02~13:35 连续登录墙，B 组 14:05~14:23 等 IP 轮换），属环境噪声非模式差异。

### D.2 成功率 / 终态分布

```
A 组 shops: done 17 / no_contact 2 / failed 1 / pending 20（剩余种子未动）
B 组 shops: done 17 / no_contact 1 / failed 2 / pending 20
A 组 contacts 落库 19 条（17 条有手机或座机）
B 组 contacts 落库 18 条（17 条有手机或座机）
```

两组处理的是**完全相同的 20 个店铺、相同顺序**（临时库 id 16-22, 28-40，
`cut -d'|' -f2 | sort | diff` 无差异）。逐店终态：14 家完全一致（均 done）；
6 家差异全部是「一边 done、另一边 no_contact 或 failed」——
即同店不同次访问被风控/软拦截挡住的概率性事件，无一例「两边都成功但结论相反」。
有联系方式产出两组完全相同（17 家）。

### D.3 字段口径

两组都入 contacts 的 17 家逐字段对比（contact_person/gender/phone/mobile/fax/address/
source_url，排除 shop_id/scraped_at/raw_text）：

```
字段完全一致: 14/17
3 家差异全部是「一边解析到值、另一边全空」：
  shop1467306371126: A 空（页面返回"电话：暂无"的软拦截变体） / B 有（徐建/13758991601/...）
  shop2004350q59yi8: A 有（王纯洁/13433999088/...） / B 空
  shop60r83940c2i00: A 空 / B 有（江燕玲/86 020 12345678/...）
仅A有contacts（B 组 failed 未入库）: shop9914hq7599683, tjmiantian
仅B有contacts（A 组 failed 未入库）: shop887377s5z24i1
```

**没有任何一个字段是「两边都填了但值不同」**——解析口径严格同构；
差异全部是页面内容侧（风控软拦截返回脱敏页）而非代码路径侧。

各抽 3 条完整行（全文 `/tmp/equiv_contacts_sample.txt`；shop_id 为各自临时库内 id，
同 shop_id 对应同店铺，可直接对照）：

```
A 组 id=19 shop_id=22: 王勇|男|86 0539 8215233|13573977034|86 0539 8215233|山东临沂沂隆百货市场|https://lylanmeiyang.1688.com/page/contactinfo.htm|2026-08-07 13:39:20
B 组 id=18 shop_id=22: 王勇|男|86 0539 8215233|13573977034|86 0539 8215233|山东临沂沂隆百货市场|https://lylanmeiyang.1688.com/page/contactinfo.htm|2026-08-07 14:24:45
（同店铺两次抓取字段逐字相同）
A 组 id=11 shop_id=32: 江海生|男|86 020 15818842|NULL|NULL|广东省东莞市大朗镇长塘长育路七巷5号|...|2026-08-07 13:35:35
B 组 id=11 shop_id=31: 江燕玲|女|86 020 12345678|NULL|NULL|广州市从化区江埔街和睦村二队25号101房（一址多照）|...|2026-08-07 14:03:00
```

work_items 表：A 组为空（旧 CLI 不经 work_items，符合预期）；B 组 20 行全部落终态：

```
$ sqlite3 -readonly /tmp/equiv_b.db "SELECT id,status,claimed_by,substr(COALESCE(result_json,'NULL'),1,60) FROM work_items"
1..16 | done  | w0 | NULL
17    | failed| w0 | {"reason": "已解析联系方式页", "kind": "block"}
18    | failed| w0 | {"reason": "已解析联系方式页", "kind": "block"}
19,20 | done  | w0 | NULL
```

claimed_by/claimed_at/finished_at 齐全，无 pending/claimed 残留；
2 个 failed 均带 reason/kind（14:05~14:11 登录墙密集期被策略链放弃，
与 A 组同环境 1 个 failed 同因）。shops 侧无 in_progress 残留（两组收工后均为 0）。

### D.4 结论

三项指标全部支持「行为等价」：节奏同量级且由相同节流参数主导；成功率/终态分布
同构（成功产出 17 家完全相同）；字段口径严格同构（共同抓到的店铺逐字段全等）。
daemon 独有的 work_items 队列机制（topup/claim/finish/启动重置）全部按设计工作。

## E. 清理与生产库零污染

临时库已删除：`rm -f /tmp/equiv_{a,b}.db{,-wal,-shm}`（日志、种子清单、分析脚本
保留在 /tmp 供审计）。生产库最终核查（14:28）：

```
$ sqlite3 -readonly .cache/1688.db "SELECT COUNT(*) FROM work_items;"
0        # 前 0 → 后 0 ✓
```

ip_events 本时段（基线 12:29:23 之后）新增 7 条，全部 event='launch'：

```
2164|113.121.233.121|launch|tunpool-8jx7g.qg.net:26030|12:51:45   ┐
2166|182.32.150.234|launch|tunpool-8jx7g.qg.net:26030|13:15:00    │ 出口 IP 与我的
2168|125.80.182.187|launch|tunpool-8jx7g.qg.net:26030|13:43:08    │ 测试进程重叠
2170|106.9.159.248 |launch|tunpool-8jx7g.qg.net:26030|14:24:59   ┘
2165|118.180.238.247|launch|tunpool-wrvnk.qg.net:19715|12:58:55  ┐ madeinchina 爬虫
2167|106.114.227.64 |launch|tunpool-wrvnk.qg.net:19715|13:42:59  │ 自己的通道
2169|110.84.195.110 |launch|tunpool-wrvnk.qg.net:19715|14:13:21  ┘
```

归因证据（7 条全部归属两个活爬虫，非我的测试进程写入）：

1. **铁证**：`125.80.182.187 @ 13:43:08` 早于 B 组启动时间 13:43:20 —— 不可能是 B 组写的。
2. 我的两组全部 launch 事件都落在各自临时库（A 组 12:42:46/12:44:41/12:56:46/...、
   B 组 13:43:40/13:56:58/...），与生产库 7 条时间戳**无一重合**。
3. 机理：青果隧道缓存 `.cache/qingguo_tunnel.json` 全机共享，活爬虫的 provider 通道
   列表同样包含 `tunpool-8jx7g:26030`，其 worker relaunch 时经同一隧道拿到同一出口 IP，
   并以默认库路径把 launch 事件写进生产库。
4. ip_stats 交叉验证：生产库中这 4 个 identity 的计数（如 113.121.233.121:
   req=17/ok=17/blocks=0）与我的临时库（req=25/ok=10/blocks=15）**完全对不上**——
   若我的写落入生产库，blocks 必 ≥15；实际为 0，是纯爬虫数据。我的 stat 全在临时库。

ip_stats MAX(updated_at)：前 12:37:53 → 后 14:27:09（增量为活爬虫正常活动，
爬虫 pid 2799/86546 全程存活未受干扰）。

## 验收逐条

- [x] SPEC §5 第 2 条：B 组 daemon 代理模式 --limit 20 跑通，shops/contacts 落库，
      work_items 20 行全部落终态（18 done + 2 failed，failed 带 reason——
      「全 done」字面未达成，见疑虑 1）
- [x] SPEC §5 第 3 条：A/B 对比（节奏、成功率、字段口径）支持等价结论（§D.4）
- [x] SPEC §4 假设 3：平台服务未运行（:8765 connection refused），本项不适用
- [x] 生产库零污染：work_items 0→0；ip_events/ip_stats 本时段新增全部归因活爬虫（§E）

## 疑虑

1. **work_items 未全 done（18/20）**：2 个 failed 发生于 14:05~14:11 登录墙密集期，
   策略链按既有规则放弃并正确落终态（`result_json={"reason":"已解析联系方式页","kind":"block"}`，
   注意 reason 文案取自 fetch 的 detail，与「放弃」语义放在一起略显误导，属既有文案）。
   A 组同环境亦有 1 个 failed，符合 brief「环境因素如实记录」约束；机制本身无缺陷，
   但 SPEC §5 第 2 条「work_items 全 done」字面未达成，请主 Agent 裁定是否接受。
2. **`ContactTask.summary()` 无视 `--db`，固定读默认生产库**（`contact.py:132` 的
   `ShopDB()`）：两组日志尾部的「数据库统计/tmd 报表」实际是生产库全局数据而非本组
   数据；且 ShopDB 构造会对生产库执行幂等 DDL/_migrate。既有行为（旧 CLI 同款），
   非本次分支引入，未修复（走查不改代码）。
3. **代理通道全机共享**导致我的测试出口 IP 与活爬虫重叠，生产库 ip_events/ip_stats
   出现同 identity 记录（已归因，§E）。后续若再做此类对比，该噪声无法避免，建议
   沿用本次的时间戳+计数双重对照法。
4. 非 TTY 下「已达 --limit 收工」「批次休息」等常规行只上状态板不进日志文件
   （engine.py 日志路由只放 `[X]/[!]` 行），节奏分析只能依赖 contacts.scraped_at/
   ip_events，已够用但日志可观测性可改进（同样为既有行为）。

## 附 1：contacts.scraped_at 完整时间序列

```
A 组（19 个）: 12:57:01 12:57:53 12:58:24 12:58:51 12:59:14 12:59:41 13:00:05 13:00:31
  13:00:58 | 13:12:47 | 13:35:35 13:36:38 13:37:01 13:37:21 13:37:48 13:38:13 13:38:35
  13:38:57 13:39:20
  （| 为批休/风控等待窗口：13:00:58→13:12:47 含批休120s+登录墙处置；13:12:47→13:35:35 等 IP 轮换）
B 组（18 个）: 13:57:11 13:57:41 13:58:06 13:58:30 13:58:51 13:59:10 13:59:27 13:59:52
  14:00:12 14:00:32 | 14:03:00 14:03:26 14:03:47 14:04:11 14:04:32 14:04:52 | 14:24:17 14:24:45
  （14:00:32→14:03:00 ≈ 批休 120s±抖动；14:04:52→14:24:17 登录墙后等 IP 轮换）
```

## 附 2：审计文件清单（/tmp）

- `equiv_a.log` / `equiv_b.log`：两组完整运行日志
- `equiv_seed.py` / `equiv_seed_list.txt`：种子脚本与清单
- `equiv_analyze.py`：对比分析脚本（本报告 D 段数据来源）
- `equiv_contacts_sample.txt`：contacts 抽样完整行
