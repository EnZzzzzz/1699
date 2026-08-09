# Step 2.4 报告 — 群采集运行时冒烟

- 状态：**DONE**
- 日期：2026-08-09 22:26（北京时间）
- 执行人：Step 2.4 implementer（subagent）
- 环境：`platform/server/.venv/bin/python`（fetcher editable 安装，cwd=fetcher/ 下 import 正常）；生产 daemon PID 34402 全程在跑未受影响；无 BRIGHTDATA_API_KEY / APIFY_TOKEN

## 执行过程

### A 段 — 缺 key 真实链路（FATAL → 群 failed）

**0. 临时库建表 + 种子（/tmp/fb_group_smoke_A_1786285428/1688.db）**

```
ShopDB(Path(tmp)/"1688.db") 初始化建表
INSERT fb_groups (url=groups/676368063029200/, status='pending', source='ddg')
INSERT work_items (queue='crawl_fb_group', site=NULL, requires='["local"]',
                   payload={"url": ".../676368063029200/", "provider": "brightdata", "limit": 50})
→ seeded: work_items id=1 pending；fb_groups id=1 pending
```

**1. 起 daemon（不带 key 环境、无头，后台 + 日志重定向）**

```
python -m fetcher daemon --db /tmp/fb_group_smoke_A_1786285428/1688.db \
    --queues crawl_fb_group --local-workers 1        # PID 7771
```

**2. daemon.log（完整）**

```
[1] fb_groups 待采集 1 个（daemon 由 work_items 队列供货）
[daemon] 队列 crawl_fb_group: 待补货店铺 0 个 + 待认领工作项 1 个
[daemon] 启动重置：0 个 claimed 工作项 → pending，0 个 in_progress 店铺 → pending（逐 site: ）
[2] 启动 0 个 worker（直连）
[2] 另启动 1 个 local 消费者（无浏览器，wa_check 等非站点队列）
[claim] queue=crawl_fb_group item=1 site=None @2026-08-09 22:23:50
[finish] item=1 status=failed @2026-08-09 22:23:50
[OK] 本次完成: 有联系方式 0, 无联系方式 0, 失败 1
    fb_groups 1 行，fb_contacts 0 个号码
```

daemon 处理完 FATAL 后自行退出（LocalLoop FATAL 分支 on_giveup → break → Engine.run 返回），无需 kill。

**3. 落库查询**

```
fb_groups : {id:1, url:.../676368063029200/, group_id:'676368063029200', status:'failed',
             post_count:None, has_contact:None, last_crawled_at:None}   ← pending→failed ✓
work_items: {id:1, queue:'crawl_fb_group', status:'failed', claimed_by:'local0',
             claimed_at:'2026-08-09 22:23:50', finished_at:'2026-08-09 22:23:50',
             result_json:'{"reason": "缺少 Bright Data API key（传 api_key 或设环境变量 BRIGHTDATA_API_KEY）", "kind": "fatal"}'}
fb_contacts: 0 行
```

**链路还原**：work_items#1 pending→claimed(local0) → QueueRouter.fetch → FbGroupTask.fetch → `FetchFbGroupPosts.run` 缺 BRIGHTDATA_API_KEY → `ActionResult.fatal("缺少 Bright Data API key…")` → LocalLoop FATAL 分支 `task.on_giveup(ctx, item, result.detail, "fatal")` → QueueRouter.on_giveup → `FbGroupTask.on_giveup` → `mark_fb_group_failed(url)`（群 status=failed）→ `_finish(ctx,"failed",result={"reason":detail,"kind":"fatal"})`（work_items#1 终态 failed，detail 落 result_json）→ break 退出。**A 段验收 ✓**

### B 段 — mock done 链路（pending→done + fb_contacts 落号）

**方案**（report 说明）：monkeypatch 在 daemon 子进程内不传递（daemon 由 CLI 子进程启动），故采用 brief 建议的「python 冒烟脚本内 monkeypatch 后按真实 daemon 装配方式起 Engine/LocalLoop」：
- 临时脚本 `/tmp/fb_group_smoke_B_1786285428/smoke_b.py`（不入库）
- 种子：fb_groups 1 行 pending + work_items 1 行（crawl_fb_group，provider=brightdata，limit=10）
- monkeypatch `fetcher.atoms.facebook_group.FetchFbGroupPosts.run` → 返回 `ActionResult.success`，posts=构造 2 帖（帖1 含 cn_uncertain 号 13900001111 + declared_wa 号 8613900001111，帖2 无号）
- 装配与 `fetcher/cli/main.py::_run_daemon` 逐行一致：`build_parser().parse_args([...])` → `config_from_args` → `_build_registry(["crawl_fb_group"])` → `QueueRouter(registry)` → `Engine(cfg, task=router, site=None, local_workers=1, browser_workers=0, status_store=None)`（纯本地队列 → 无浏览器 worker）
- 与真实 daemon 唯一差异：进程边界（patch 不跨子进程，故同进程跑）+ ConsumerStatusStore 心跳（非验收项，略去）
- 主线程轮询 work_items 终态 → `engine.stop.set()` → join（Engine 等货 condvar 30s 自醒，实测 0.5s 即完成）

**运行输出（节选）**

```
[seed] work_items id=1 pending, fb_groups id=1 pending
[patch] FetchFbGroupPosts.run <- fake_run（返回 2 帖构造数据）
[1] fb_groups 待采集 1 个（daemon 由 work_items 队列供货）
[daemon] 队列 crawl_fb_group: 待补货店铺 0 个 + 待认领工作项 1 个
[2] 启动 0 个 worker（直连）
[2] 另启动 1 个 local 消费者（无浏览器，wa_check 等非站点队列）
[claim] queue=crawl_fb_group item=1 site=None @2026-08-09 22:24:42
[mock] FetchFbGroupPosts.run provider=brightdata url=https://www.facebook.com/groups/676368063029200/ limit=10
[finish] item=1 status=done @2026-08-09 22:24:42
[poll] work_items 终态: done（0.5s）
[OK] 本次完成: 有联系方式 1, 无联系方式 0, 失败 0
    fb_groups 1 行，fb_contacts 2 个号码
```

**落库查询（验收证据）**

```
fb_groups : {id:1, url:.../676368063029200/, status:'done', post_count:2,
             has_contact:1, last_crawled_at:'2026-08-09 22:24:42'}      ← pending→done + 三字段回写 ✓
fb_contacts（2 行新增）:
  {id:1, number:'13900001111', bucket:'cn_uncertain', wa_source:None,
   post_url:'.../groups/676368063029200//posts/1442991693033496/', group_id:'676368063029200'}   ← 帖1 溯源 ✓
  {id:2, number:'8613900001111', bucket:'declared_wa', wa_source:'declared',
   post_url:'.../groups/676368063029200//posts/1442991693033496/', group_id:'676368063029200'}   ← 帖1 溯源 + wa_source ✓
  （帖2 无号码 → 不落号，符合预期）
work_items: {id:1, queue:'crawl_fb_group', status:'done', claimed_by:'local0',
             claimed_at:'2026-08-09 22:24:42', finished_at:'2026-08-09 22:24:42', result_json:None}
```

**链路还原**：work_items#1 pending→claimed(local0) → FbGroupTask.fetch 调（被 patch 的）原子 → OK → LocalLoop on_success → QueueRouter.on_success → `FbGroupTask.on_success`：逐帖 `save_fb_contacts(post_url, group_id, phones)`（帖1 两号入 fb_contacts，INSERT OR IGNORE 按 number 去重）→ `mark_fb_group_done(url, 2, True)`（status=done + post_count=2 + has_contact=1 + last_crawled_at）→ `_finish(ctx,"done")`（work_items#1 终态 done）。**B 段验收 ✓**

## 验收结论

两段各走通一轮完整状态机：A pending→claimed→failed（kind=fatal，reason=缺 key detail）；B pending→claimed→done。B 段 fb_contacts 落号 2 行证据完整（post_url 帖级溯源、group_id 正确、declared_wa→wa_source='declared' 与 cn_uncertain→NULL 分桶语义正确）。**验收标准满足。**

## ledger.md 追加内容

（已 commit `de4dd6d`，9 行追加，见 ledger.md「## Step 2.4 冒烟记录（2026-08-09 22:26，DONE）」节；commit 仅含 ledger.md，1 file changed）

## 疑虑 / 观测

1. **原子 FATAL 日志可观测性**（非阻塞）：`FetchFbGroupPosts.run` 的 FATAL 分支不写 `ctx.log`，daemon 日志链只有 `[claim]`→`[finish] status=failed`，FATAL 的 detail 文本仅落 `work_items.result_json`。链路完整可验证，但运维侧从日志看不到失败原因（需查库）。属可观测性优化点，非本次缺陷。
2. **B 段 mock 帖 URL 双斜杠**：`groups/676368063029200//posts/...` 是 mock 数据用 `GROUP_URL + "/posts/…"` 拼接所致（GROUP_URL 以 `/` 结尾）；真实 BD/Apify 帖 url 由接口返回，不会双斜杠。非代码缺陷。
3. **隔离确认**：A/B 两段均只读/写各自 /tmp 临时库；生产库 .cache/1688.db 未触碰，生产 daemon 34402 全程在跑无异常日志；无浏览器窗口弹出（local 消费者，符合预期）。
4. B 段未启用 ConsumerStatusStore 心跳（非验收项）；A 段为真实 daemon 全量装配（含心跳），`consumer_status local0` 心跳仅写临时库，未与生产同键冲突（生产 local0 心跳在生产库，两库分离）。

## 参考

- 临时脚本：`/tmp/fb_group_smoke_B_1786285428/smoke_b.py`
- 临时库：`/tmp/fb_group_smoke_A_1786285428/1688.db`、`/tmp/fb_group_smoke_B_1786285428/1688.db`
- 冒烟日志：`/tmp/fb_group_smoke_A_1786285428/daemon.log`
