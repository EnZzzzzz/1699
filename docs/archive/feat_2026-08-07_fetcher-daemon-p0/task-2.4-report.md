# Step 2.4 report — daemon 直连冒烟

> 走查日期：2026-08-07（北京时间，机器本地时区即 +8）。分支 feat/fetcher-daemon-p0。
> 全程临时库 `/tmp/daemon_smoke.db`，未写生产库 `.cache/1688.db`（核查证据见 D 段）。
> 原始日志：`/tmp/daemon_smoke_b.log`（B 段，740 行）、`/tmp/daemon_smoke_c.log`（C 段）。

## A. 准备

1. `--db` 参数确认存在（`add_common_args`，daemon parser 也带）：

   ```
   $ cd fetcher && python -m fetcher daemon --help
   ...
     --workers WORKERS
     --db DB [--no-auto-solve]
   ```

2. 种子数据：从生产库**只读**抄两条真实 done 店铺：

   ```
   $ sqlite3 "file:.cache/1688.db?mode=ro" \
     "SELECT domain,name,url,status FROM shops WHERE status='done' AND domain LIKE '%1688.com' ORDER BY id DESC LIMIT 5;"
   shop9116o50125007.1688.com|余姚市灵格塑料厂|...|done
   hysilicone.1688.com|东莞市石排汉鹰硅胶制品厂|...|done
   ```

   用 `ShopDB("/tmp/daemon_smoke.db").upsert_shops(...)` 预置 2 条 pending：

   ```
   inserted: 2
   id=1 shop9116o50125007.1688.com status=pending attempts=0 first_seen_at=2026-08-07 12:24:37
   id=2 hysilicone.1688.com          status=pending attempts=0 first_seen_at=2026-08-07 12:24:37
   ```

## B. 主冒烟：跑 2 条

命令：

```
cd fetcher && python -m fetcher daemon --db /tmp/daemon_smoke.db --limit 2 --workers 1 --headed
```

- 启动时间 12:24:37，进程退出约 12:28:40，**exit=0**（后台任务输出 `exit=0`）。
- `--headed` 正常起来（CloakBrowser Chromium 150，有头窗口可见），无需退 `--headless`。
- 日志要点（`/tmp/daemon_smoke_b.log`）：

  ```
  [1] 待抓取 2 个，每个 worker 每批 10 个（不限批数，抓完 pending 为止），批间强制休息 15 分钟
  [daemon] 队列 crawl_1688_contact: 待补货店铺 2 个 + 待认领工作项 0 个
  [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
  [2] 启动 1 个 worker（直连）
      [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=direct
      [license] 服务端 5/5 个会话席位被占用... 20s 后重查...   （×8，约 3 分钟等席位）
      [launch] 浏览器进程已启动，创建上下文并注入 Cookie…
  [solve] 第 1/8 次尝试：回放 83 点轨迹，距离 258px（剩余未用轨迹 8 条）
  [solve] ✓ 第 1 次尝试通过
  ```

  链路顺序符合预期：reset（0 行）→ prepare → top-up 2 条 → 消费者逐条抓取 → `--limit 2` 收工退出。
  注：启动后约 3 分钟无动作是 **CloakBrowser  license 席位满（5/5，本机还有其他爬虫在跑）每 20s 重查**导致，不是 daemon 卡死；等到席位后正常启动浏览器。期间出现一次滑块，auto_solve 第 1 次尝试即通过。

- 跑完 SQL 核查（`sqlite3 file:/tmp/daemon_smoke.db?mode=ro`）：

  work_items — 2 行 done、finished_at 非空 ✅

  ```
  1|crawl_1688_contact|done|w0|2026-08-07 12:27:41|2026-08-07 12:28:13
  2|crawl_1688_contact|done|w0|2026-08-07 12:28:32|2026-08-07 12:28:38
  ```

  shops — 2 行 done（两家店都抓到了联系方式，非 no_contact）✅

  ```
  1|shop9116o50125007.1688.com|done|attempts=1
  2|hysilicone.1688.com|done|attempts=1
  ```

  contacts — 2 条落库，字段口径正常 ✅

  ```
  shop_id=1 陈珊珊  mobile=15867852403                       scraped_at=2026-08-07 12:28:13
  shop_id=2 余彦    phone=86 0769 83061642  mobile=13790257138
                    address=广东东莞石排镇福隆屋吓新二街20号101室  scraped_at=2026-08-07 12:28:38
  ```

  附带：临时库 ip_stats `direct|requests=3|ok=2|blocks=1`、ip_events 1 行、cookies 173 行
  —— 统计/Cookie 也都写进了 --db 指定的临时库，没串库。

## C. 空队列挂起 + SIGTERM 退出

命令（同库，无 pending 店铺）：

```
cd fetcher && python -u -m fetcher daemon --db /tmp/daemon_smoke.db --workers 1
```

日志（`/tmp/daemon_smoke_c.log`）：

```
[OK] 没有待抓取的店铺。统计: {... 'pending': 0, 'done': 2 ...}
[daemon] inner.prepare 报告队列暂空，继续常驻等货
[daemon] 队列 crawl_1688_contact: 待补货店铺 0 个 + 待认领工作项 0 个
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
[2] 启动 1 个 worker（直连）
    [launch] 浏览器进程已启动，创建上下文并注入 Cookie…
（之后无任何滚动日志 —— 不空转）
```

- 挂起证据：daemon python 进程（pid 91157）存活 2 分 17 秒不退出，
  两次 `ps -o %cpu -p 91157` 抽测（间隔 5s）均 `0.0`。✅
- SIGTERM：`kill 91157` 后 **12s 干净退出**（< 30s 要求），日志尾部为正常 summary
  （tmd 报表），无异常堆栈。✅
- 退出后 `ps aux | grep "[f]etcher daemon"` = 0；B 段浏览器 profile（veQgOx）已消失，
  无残留进程。

### C 段操作备注（测量修正）

第一次启动用了 shell 复合命令 `cd fetcher && python ... &`，`$!` 拿到的是 subshell（91156）
而非 python 本体（91157），首次 kill 杀错了进程。修正后直接对 python 本体重测，
上列挂起时长/CPU/退出耗时均为对 91157 的实测值。期间 daemon 无人为干预地持续挂起，
反而把挂起观察拉长到了 2 分钟以上。

## D. 清理

- 临时库已删除：

  ```
  $ rm -f /tmp/daemon_smoke.db{,-wal,-shm}
  $ ls /tmp/daemon_smoke.db
  ls: /tmp/daemon_smoke.db: No such file or directory
  ```

- 生产库无污染（全部只读核查，时间戳均早于冒烟）：

  ```
  $ sqlite3 "file:.cache/1688.db?mode=ro" "SELECT COUNT(*) FROM work_items;"
  0
  $ ... "SELECT domain,status FROM shops WHERE domain IN (两种子域名);"
  hysilicone.1688.com|done          ← 种子本来就是 done，未被改动
  shop9116o50125007.1688.com|done
  $ ... "SELECT identity,requests,updated_at FROM ip_stats WHERE identity='direct';"
  direct|8|2026-08-04 21:37:15      ← 冒烟前的旧值，本次直连统计没写进生产库
  $ ... "SELECT COUNT(*),MAX(created_at) FROM ip_events WHERE identity='direct';"
  7|2026-08-04 21:37:15             ← 同上
  ```

## 验收对照

- [x] 2 条 work_items done、shops 落终态（done×2）、contacts 落库（SQL 证据见 B）
- [x] 空队列挂起 ≥60s 不退出、CPU≈0（ps 证据见 C）
- [x] SIGTERM 后 12s 干净退出（< 30s，日志尾部正常）
- [x] 全程未写生产库（D 段核查）

## 异常现象与疑虑（均已核实影响面，非阻塞）

1. **`ContactTask.summary()` 忽略 `--db`，读的是默认生产库**
   （`fetcher/fetcher/sites/alibaba1688/contact.py:132` `db = ShopDB()` 无参）。
   表现：B/C 两段结尾打印的「数据库统计 / tmd 报表」是生产库数据（报表里大量
   代理 IP、整体 14605→14617 次请求——增量来自本机并行的其他爬虫，非本冒烟）。
   影响：**只读**，未产生任何生产库写入（D 段证据）。且这是 contact 任务既有行为，
   非 daemon 改动引入（普通 CLI `--db` 跑 contact 同样如此）。建议后续 Step 顺手修
   （改成 `ShopDB(config.resolved_db_path())`，summary 签名需能拿到 config 或 db path）。

2. **license 席位等待**：B 段启动时 CloakBrowser 服务端 5/5 席位被占（本机其他爬虫
   占用 + 残留租约），等了约 3 分钟才启动浏览器。日志有清晰说明，属环境噪音非 bug；
   但冒烟排查时容易误判为 daemon 卡死，值得知道。

3. **stdout 缓冲**：非 tty 重导向下 daemon 输出块缓冲，运行中途看日志文件是空的
   （B 段退出后才落盘 740 行）。C 段加 `-u` 解决。运维上建议后续考虑 logging/flush，
   非本次范围。
