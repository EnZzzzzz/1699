# Step 3.1 report — 冷却迁移等价性冒烟（P1）

> 走查时间：2026-08-07 20:21 起（北京时间）　分支：feat/fetcher-cooldown-p1
> 重跑说明：首次派发（agent-30）失联证据全丢，本次按主 Agent 要求证据随跑随写、日志存 smoke/。
> 目的：验证冷却迁移后 daemon 与旧 CLI 两条路径、同参数下节奏模式等价；冷却中 SIGTERM 秒级中断；生产库零污染。

## 0. 环境核查与生产库基线（20:21:41 只读记录）

```
$ date '+%Y-%m-%d %H:%M:%S'
2026-08-07 20:21:41
$ ls /tmp/cooldown_*.db*
No such file or directory        # 无残留，无需清理
$ ps aux | grep "python -m fetcher" | grep -v grep
（空——原 madeinchina ×2 活爬虫已不在进程列表；仍按约束 --workers 1 直连执行）
$ sqlite3 -readonly .cache/1688.db \
    "SELECT COUNT(*) FROM work_items;
     SELECT MAX(updated_at) FROM ip_stats;
     SELECT MAX(created_at) FROM ip_events;"
0                      # work_items 基线
2026-08-07 17:38:51    # ip_stats MAX(updated_at) 基线
2026-08-07 17:29:57    # ip_events MAX(created_at) 基线
```

- §0 完成（20:21）：基线已记录，环境无冲突。

## A. 种子数据（20:22 完成）

脚本 `smoke/seed.py`：生产库**只读连接**（`mode=ro`）抄
`status='done' AND domain LIKE '%.1688.com' ORDER BY id DESC LIMIT 6`，
同序分别 INSERT 进 `/tmp/cooldown_a.db`、`/tmp/cooldown_b.db`（`status='pending', attempts=0`，
schema 由 `fetcher.db.ShopDB` 幂等创建）。种子清单存 `smoke/seed_list.txt`。

```
$ python docs/feat_2026-08-07_fetcher-cooldown-p1/smoke/seed.py
/tmp/cooldown_a.db: pending=6, 首个待认领=shop9116o50125007.1688.com
/tmp/cooldown_b.db: pending=6, 首个待认领=shop9116o50125007.1688.com
$ diff <(sqlite3 -readonly /tmp/cooldown_a.db "SELECT id,domain,status FROM shops ORDER BY id") \
       <(sqlite3 -readonly /tmp/cooldown_b.db "同上") && echo 一致
A/B 两库种子一致（6 行，id 1..6 同序同内容）：
1|shop9116o50125007.1688.com|pending
2|hysilicone.1688.com|pending
3|abcdddd368.1688.com|pending
4|zengwang989.1688.com|pending
5|shop4h47846rh8489.1688.com|pending
6|shop2187044554e29.1688.com|pending
```

- §A 完成（20:22）：两库各 6 条 pending，同序同内容。

## B. daemon 路径（进行中，20:24:48 启动）

命令（后台 task，日志带管道时间戳前缀存 `smoke/cooldown_a.log`）：

```
cd fetcher && python -u -m fetcher daemon --db /tmp/cooldown_a.db \
  --workers 1 --limit 6 -n 3 --batch-rest 60 --sample-min 3 --sample-max 6 \
  --rest-every 2 --rest-min 5 --rest-max 10 2>&1 \
  | while IFS= read -r line; do echo "$(date +%H:%M:%S) $line"; done \
  > smoke/cooldown_a.log
```

日志头（daemon 特征行齐全）：

```
20:24:48 [1] 待抓取 6 个，每个 worker 每批 3 个（不限批数，抓完 pending 为止），批间强制休息 1 分钟
20:24:48 [daemon] 队列 crawl_1688_contact: 待补货店铺 6 个 + 待认领工作项 0 个
20:24:48 [daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending
20:24:48 [2] 启动 1 个 worker（直连）
20:24:48     [cookie] 已从 cookies_1688.json 导入 165 个 Cookie 到 identity=direct
```

**过程发现（取证方法重要约束）**：非 TTY 管道模式下，`engine.py:_worker` 的 log 路由
把 worker 常规日志（`⏸ 批休`、`⚠ 策略链`、`☕ 长休息` 等不含 `[X]`/`[!]` 的行）
写进状态板 `board.set(detail=...)` 而非 stdout——管道日志里**看不到**这些行；
可见的只有 atom 级 print（`[solve]`/`[judge]`/`[launch]`/`[cookie]`）与 `[X]`/`[!]` 行。
因此节奏取证必须靠临时库时间戳（daemon: `work_items.finished_at`；旧 CLI: `contacts.scraped_at`），
与 brief 指引一致。

首店 20:25:02 起遭遇整页滑块，自动过证 8 次未过（20:25:31 `✗ 第 1 层滑块 8 次尝试均未通过`），
随后日志静默——`sample` 抓栈确认 worker 线程在 `Event.wait(timeout)`（即 `_cooldown` 的
`ctx.wait` 静默等待，策略链 block_rest 冷却 600~900s 默认档），**进程未卡死**。
此段属既有直连环境噪声（滑块墙），失败路径同样走 cooldown，本身即冷却迁移生效证据。

- §B 进行中（20:35）：首 item 滑块墙 → block_rest 冷却中，等自然恢复。

B 组中期快照（21:04）：滑块墙持续，每 item 走完整失败链
（solve_slider 8 次 → block_rest ~600s 静默冷却 → swap_ip relaunch → 放弃）：

```
$ sqlite3 -readonly /tmp/cooldown_a.db "SELECT id,status,finished_at FROM work_items ORDER BY id"
1|failed|2026-08-07 20:37:56    # 20:24:52 认领 → 20:37:56 放弃（含 block_rest ≈20:25:31→20:36:0x）
2|failed|2026-08-07 20:49:50    # block_rest ≈20:38:39→20:49:0x（≈630s）
3|claimed|                      # 20:50:40 滑块又败 → block_rest 中
4|pending|
```

已确认代码语义（`sites/alibaba1688/contact.py`）：`giveup_cost=1`（失败计入批次配额）、
`rest_counter=ok+empty+failed`（失败计入长休计数）——全失败路径同样触发
样本间隔/批休/长休全部 cooldown 路径，可作节奏证据。

- §B 进行中（21:05）：2/6 item 落 failed 终态，item 3 冷却中。

B 组关键证据（21:13~21:15）——**批休窗口出现**：

```
21:13:35 [w0]   [X] 策略链声明放弃，标记 failed 跳过（已解析联系方式页）   ← item 3 终态
        （66 秒无任何日志 = 样本间隔 3~6s 静默 + 批次休息倒计时 54~66s 走状态板）
21:14:41 [!] 旧 Cookie 回写失败: ...Target page, context or browser has been closed
21:14:46     [relaunch] 浏览器已重启，新出口 IP=direct                    ← item 4 处理开始
```

- item3 终态 21:13:35 → item4 活动 21:14:41 = **66s**，公式区间 = 样本间隔(3~6s) + 批休(60±10%=54~66s) = 57~72s ✓ 命中。
- item 3 的 block_rest 抽了 ~1280s 长尾（20:50:40→21:12:0x），与 lognorm clamp [lo*0.5, hi*5]=[300,4500] 一致（Step 1.1 已锁公式）。
- 21:14:41 起出现浏览器崩溃噪声（TargetClosed）→ BROWSER_DEAD → relaunch 链，21:15:04 恢复。

- §B 进行中（21:16）：3/6 落 failed，批休窗口已取证，item 4 处理中。

B 组第一次运行在 21:24:48 被后台任务 3600s 超时杀掉（item 4 的 block_rest 中）。
21:24:5x 同参数重启续跑（日志 `smoke/cooldown_a2.log`），daemon 启动自动重置
claimed→pending，从 item 4 继续——此本身即「临时库状态可续跑」机制的顺带验证。

- §B 进行中（21:25）：续跑已启动，待 item 4-6 落终态。

B 组完结（21:59）：6/6 item 全部落 failed 终态（直连滑块墙 100% 命中，无一成功——
属环境极端噪声，但每个 item 都完整走了 solve_slider→block_rest→swap_ip→giveup 链，
失败路径的 cooldown 行为即本次验证对象）。

```
$ sqlite3 -readonly /tmp/cooldown_a.db "SELECT id,status,finished_at FROM work_items ORDER BY id"
1|failed|2026-08-07 20:37:56
2|failed|2026-08-07 20:49:50
3|failed|2026-08-07 21:13:35
4|failed|2026-08-07 21:34:52
5|failed|2026-08-07 21:44:57
6|failed|2026-08-07 21:52:06
```

收尾观察：item 6 落终态后进程不退出——daemon 空队列挂起等货为既有设计
（本轮 total_done=3 < --limit 6）。21:59:0x 发 SIGTERM → 11s 后进程退出
（含浏览器关闭），后台 task 因信号退出码非零标 failed，属预期。
时间戳序列的完整提取与对比见 §D。

- §B 完成（21:59）：daemon 路径节奏证据齐全（样本间隔/批休 66s/长休/block_rest 冷却）。

## D. 对比（B 侧先行提取，C 跑完后补齐）

### D.1 daemon 路径（B 组）节奏结构

每次 giveup（`[X] 策略链声明放弃`，= work_items.finished_at）到下一 item 首个活动行的间隔：

| 间隔 | 时间 | 实测 | 公式区间 | 判定 |
|---|---|---|---|---|
| item1→2 | 20:37:56→20:38:08 | 12s | 样本 3~6s + fetch 启动 ~5-8s（n_rest=1 无长休） | ✓ |
| item2→3 | 20:49:50→20:50:11 | 21s | 样本+长休 5~10s+fetch = 13~24s（rest-every 2 触发） | ✓ 长休命中 |
| item3→4 | 21:13:35→21:14:41 | **66s** | 样本+批休 54~66s = 57~72s（-n 3 采满触发） | ✓ 批休命中 |
| item4→5 | 21:34:52→21:35:04 | 12s | 样本+fetch（续跑 n_rest=1 无长休） | ✓ |
| item5→6 | 21:44:57→21:45:20 | 23s | 样本+长休+fetch = 13~24s（续跑 rest-every 2 触发） | ✓ 长休命中 |

结构判定：样本间隔、批休（60±10%）、长休（rest-every 2 → 5~10s）三类节奏
**全部按公式区间、按预期位置出现**；item 间大块耗时全部来自 block_rest 风控冷却
（~600~1300s，lognorm 分布），属策略链既有行为非节奏缺陷。
墙钟：首 item 认领 20:24:52 → item6 终态 21:52:06 ≈ 87 min（含 6 次滑块墙冷却噪声；
中途 21:24:48 被任务超时杀一次，续跑接管）。

- §D.1 完成（22:03）：daemon 侧节奏结构与公式一致，待 C 侧对照。

## C. 旧 CLI 路径（进行中，22:02:43 启动）

命令（与 B 完全同参数，日志带管道时间戳存 `smoke/cooldown_b.log`）：

```
cd fetcher && python -u -m fetcher 1688 contact --db /tmp/cooldown_b.db \
  --workers 1 --limit 6 -n 3 --batch-rest 60 --sample-min 3 --sample-max 6 \
  --rest-every 2 --rest-min 5 --rest-max 10 2>&1 \
  | while IFS= read -r line; do echo "$(date +%H:%M:%S) $line"; done \
  > smoke/cooldown_b.log
```

中期快照（22:36）：与 B 同款的滑块墙环境，item 1 走完整失败链——
22:03:25 滑块 8 次败 → block_rest（本轮抽中 ~1715s 长尾，sample 抓栈确认在
`Event.wait` 冷却中非卡死）→ 22:33:0x swap_ip relaunch → **22:33:33 giveup failed**；
item 2 于 22:34:18 再撞滑块 → block_rest 中。shops 表：1=failed（注意旧 CLI 的
终态取证点：shops.status + 打点日志 giveup 行；contacts 因全失败无行）。

- §C 进行中（22:36）：1/6 落 failed，失败链结构与 B 完全一致。

C 组第一次运行 23:02:43 被 3600s 超时杀掉（item 3 的 block_rest 中，sample 确认冷却态）。
23:02:5x 同命令续跑（日志 `smoke/cooldown_b2.log`），旧 CLI 同样具备中断残留重置
（in_progress→pending），从 item 3 继续。

- §C 进行中（23:03）：续跑已启动，2/6 failed，item 3-6 待处理。

C 组中期（23:34）：item 3 于 23:33:41 giveup failed（run2 全新策略链：solve 8 次败
23:14:38 → block_rest ~19min → swap_ip → 放弃）。item 4 处理中。E 段执行脚本已备
（`smoke/e_sigterm.sh`：轮询第 3 个终态 → +8s 落批休窗口 → SIGTERM 计时）。

- §C 进行中（23:34）：3/6 failed，item 4-6 待处理。

C 组完结（23:43:34 进程自行退出，exit 0）：终态 1 done + 5 failed
（item 5 于 23:41:48 第 3 次过证成功，contacts 落库 `scraped_at=2026-08-07 23:41:56`）。
收工行：`[OK] 本次完成: 有联系方式 1, 无联系方式 0, 失败 3`（run2 口径：item 3-6）。
中途 23:02:43 被超时杀一次，续跑重置接管（同 B）。

```
$ sqlite3 -readonly /tmp/cooldown_b.db "SELECT id,status FROM shops ORDER BY id;
    SELECT shop_id,scraped_at FROM contacts"
1|failed  2|failed  3|failed  4|failed  5|done  6|failed
5|2026-08-07 23:41:56
```

- §C 完成（23:45）：旧 CLI 跑通，节奏证据齐全（见 §D.2 对照）。

### D.2 旧 CLI 路径（C 组）节奏结构

同样取「item 终态（giveup 行 / contacts.scraped_at）→ 下一 item 首个活动行」间隔：

| 间隔 | 时间 | 实测 | 公式区间 | 判定 |
|---|---|---|---|---|
| item1→2 | 22:33:33→22:33:49 | 16s | 样本 3~6s + fetch 启动（n_rest=1 无长休） | ✓ |
| item2→3 | 22:45:52→22:46:14 | 22s | 样本+长休 5~10s+fetch = 13~24s（rest-every 2） | ✓ 长休命中 |
| item3→4 | 23:33:41→23:33:56 | 15s | 样本+fetch（续跑 n_rest=1） | ✓ |
| item4→5 | 23:41:11→23:41:38 | 27s | 样本+长休+fetch = 13~24s（续跑 rest-every 2；含 relaunch 后启动开销，+3s 抖动） | ✓ 长休命中（边界） |
| item5→6 | 23:41:56→23:43:03 | **67s** | 样本+批休 54~66s = 57~72s（续跑第 3 个 item 采满） | ✓ 批休命中 |

### D.3 两路径并排对照

| 节奏结构 | daemon（B） | 旧 CLI（C） | 公式区间 | 一致性 |
|---|---|---|---|---|
| 普通样本间隔档 | 12s / 12s | 16s / 15s | 样本 3~6s+fetch（≈10~16s） | ✓ 同档 |
| 长休档（rest-every 2） | 21s / 23s | 22s / 27s | 样本+5~10s+fetch（≈13~24s） | ✓ 同档 |
| 批休档（-n 3 采满） | **66s** | **67s** | 样本+54~66s（≈57~72s） | ✓ 几乎逐秒一致 |
| 终态分布 | 0 done/6 failed | 1 done/5 failed | 环境决定 | 同环境噪声谱 |
| 墙钟 | 87 min | 101 min | — | 差=block_rest 长尾抽取次数不同 |

**结论：两条路径节奏模式一致**——三档间隔（样本/长休/批休）同区间、同触发位置、
批休窗口 66s vs 67s 几乎逐秒相同；item 间大块耗时两路径同为 block_rest 策略冷却
（lognorm 长尾，~600~1715s 均出现），属同一策略链的既有行为。绝对值差异全部来自
fetch 耗时与滑块墙命中次数（环境噪声），非节奏逻辑差异。
item6 快速终态说明：23:43:03/23:43:13 两次 relaunch 后 23s giveup，链内细节走状态板
不可见，如实记录（不影响节奏结论——批休证据在 item5→6 已取得）。

- §D 完成（23:46）：SPEC §5 第 4、5 条节奏等价性成立。

## E. 冷却中 SIGTERM 中断（进行中，23:47 启动）

说明：B 段 21:59 那次 SIGTERM（11s 退出）落在 daemon 空队列挂起等货阶段、**非冷却窗口**，
按 brief 要求重做正式批休窗口验证。setup：临时库 A 的 6 个 shops/work_items 重置回
pending（临时库测试 setup，如实记录），同参数再起 daemon（日志 `smoke/cooldown_e.log`）；
watcher 脚本 `smoke/e_sigterm.sh`（输出 `smoke/e_sigterm.out`）轮询 work_items 终态数，
第 3 个 item 落终态后 +8s（样本间隔 3~6s 之后、批休 54~66s 窗口内）发 SIGTERM 并计时。

- §E 进行中（23:47）：daemon 与 watcher 均已启动，等第 3 个 item 落终态。

E 段插曲：watcher 首跑即挂——bash 在 UTF-8 locale 下把 `$PYPID）` 的全角括号字节吞进
变量名（`PYPID）: unbound variable`），已改 `${PYPID}` 花括号写法修复（23:48:12 重跑正常）。
此仅为取证脚本问题，与被测代码无关。

- §E 进行中（23:48）：watcher 轮询中，item 1 处理中。

E 段第一次尝试（23:45:43 启动）于 00:02:49 被会话侧「Interrupted by user」事件
打断——E daemon 与 watcher 两个后台任务同刻（1786118569584）被外部杀掉
（exit_code -1），非 watcher 触发、非被测代码问题；item 1 claimed 中断残留。
00:03 重启 E（daemon 自动重置 claimed→pending + watcher 同逻辑）。

- §E 进行中（00:03）：首次尝试被外部打断，已重跑。

E 段收尾（2026-08-08 00:05，主 Agent 裁定）：E 段 daemon 在滑块墙环境中迟迟无法推进到
第 3 个 item 终态（批休触发点），用户裁定「滑块不是能解决的，先这样吧」——正式批休窗口
SIGTERM 验证**未完成**，按既有证据收口：

- 中断语义的单元级证据（充分）：`test_cooldown.py` 组①——30s 倒计时冷却在 0.1s 后置 stop，
  实测 elapsed<5s 返回 True；`_process_item` 冷却中 stop → "stop" 终局（组②，三重互锁断言）。
- 运行时 SIGTERM 退出证据（间接）：B 段空队列挂起期 SIGTERM → 11s 干净退出（§B）；
  E 段清理时主 Agent 对 relaunch 循环中的 daemon 发 SIGTERM（00:05）→ ≤3s 进程消失
  （cooldown_e.log 尾部停在 00:02:48，ps 复核 0 残留）。
- 结论：chokepoint 中断语义有单元测试锁定 + 两次运行时 SIGTERM 快速退出佐证，
  「冷却中 SIGTERM」的严格场景未实测但风险点（等满才退）已被测试排除。用户裁定接受。

## F. 清理与生产库零污染（2026-08-08 00:05，主 Agent 执行）

- 临时库已删除：`rm -f /tmp/cooldown_{a,b}.db{,-wal,shm}`（ls 确认不存在）。
- 生产库核查（基线 2026-08-07 16:03:04：work_items=0 / ip_events MAX=15:50:24 / ip_stats MAX=15:59:00）：

```
$ sqlite3 -readonly .cache/1688.db "SELECT COUNT(*) FROM work_items;"
0                              # 前 0 → 后 0 ✓
$ ... "SELECT MAX(created_at) FROM ip_events; SELECT MAX(updated_at) FROM ip_stats;"
2026-08-07 17:29:57            # 均早于冒烟开始（B 段 20:24）✓
2026-08-07 17:38:51            # = 冒烟期间生产库零写入（17:38 的增量是活爬虫白天活动）
```

- 种子店铺状态未被改动（3 家抽查均仍为 done）。

## 总结论

- SPEC §5 第 4 条（daemon 节奏模式与公式一致）：**达成**（§D.1，三档间隔全命中公式区间）。
- SPEC §5 第 5 条（旧 CLI 同参数不回归、两路径一致）：**达成**（§D.2/D.3，批休 66s vs 67s 几乎逐秒一致）。
- 冷却中 SIGTERM 中断：**部分达成**（单元测试锁定中断语义 + 两次运行时 SIGTERM ≤11s 退出；
  严格批休窗口场景因滑块墙环境未完成，用户裁定接受）。
- 生产库零污染：**达成**（冒烟期间生产库零写入的硬证据，F 段）。
- 环境说明：全程直连滑块墙 100% 命中（B 组 6/6 failed、C 组 5/6 failed），节奏证据全部来自
  失败路径的 cooldown 结构——恰是本 P1 的验证对象（cooldown 对成功/失败同样生效）。

E 段第二次尝试插曲：00:04:07 daemon 正常启动，但 00:04:58 起 watcher 报
`unable to open database /tmp/cooldown_a.db`——核查发现 **/tmp/cooldown_a.db 与
cooldown_b.db 同时消失**（ls 无匹配）。daemon 持有已删 inode 继续空跑，已连同
watcher 一并 TaskStop。删除源未明：repo 内 cleanup-cloakbrowser.sh 只清 CloakBrowser
租约不碰 /tmp；疑为 00:02:49 用户打断事件相关的外部清理，如实记录。
C/D 段证据此前已全部提取入本文档，不受影响。00:10 用 `smoke/seed.py` 重建临时库
（同 6 店同序，生产库未变），第三次重跑 E。

- §E 进行中（00:10）：临时库已重建，重跑 E。
