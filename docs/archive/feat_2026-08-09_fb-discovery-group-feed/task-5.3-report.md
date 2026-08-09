# Task 5.3 Report — 文档同步

> Step 5.3：同步 AGENTS.md（队列数 7→9、批次模型补两类型）+ docs/channel-research/facebook-groups.md（§10/§12「未做」清单更新）。
> 纯文档、零代码；改动前已核对实现（9 条队列、BATCH_TYPES fb_discover/fb_group、FetchDdgSerp/FbDiscoverTask/FbGroupTask 均在码）。

## 改了什么

### 1. AGENTS.md（两处）

| 位置 | old → new |
|---|---|
| §1 项目结构（daemon 行） | 「多队列调度（7 条 work_items 队列：1688/madeinchina 双站 contact + shop/company feeder + wa_check + crawl_fb_post）」→「多队列调度（9 条 work_items 队列：1688/madeinchina 双站 contact + shop/company feeder + wa_check + crawl_fb_post + discover_fb + crawl_fb_group）」（新增一行，保持行内列表风格） |
| §5 批次类模型清单 | 「（1688/madeinchina 采集、wa_check、fb_post 均走此模型）」→「（1688/madeinchina 采集、wa_check、fb_post、fb_discover、fb_group 均走此模型）」 |

其余内容未动（daemon 有头、WA_CHECK_ACCOUNTS 等 daemon-headed-queues 工作线并入的既有改动保留）。

### 2. docs/channel-research/facebook-groups.md（两处）

| 位置 | old → new |
|---|---|
| §10「未做（2026-08-09 二期落地后更新）」段 | →「已做（2026-08-09 三期落地后更新）」：发现层已换 **DDG html 端点自建**落地（`docs/feat_2026-08-09_fb-discovery-group-feed/`，fetcher 侧 FetchDdgSerp 原子 + FbDiscoverTask + discover_fb 队列 + 平台 fb_discover 批次）；群 feed 已接队列（FbGroupTask + crawl_fb_group + 平台 fb_group 批次）；其余二期项（落库 fb_posts/fb_contacts、crawl_fb_post + FbPostTask、fb_post 批次+前端、wa_check 双源衔接）均已落地并冒烟通过；Apify SERP 路线仍为非目标（自建优先） |
| §12「未做（2026-08-09 更新）」段 | →「已做（2026-08-09 三期落地后更新）」：二期接入（runner BATCH_TYPES fb_post、crawl_fb_post 队列、落库、前端任务类型）已完成；三期发现层已自建落地（DDG SERP，见 §10）；两家 key 沿用环境变量（本期未入 DB，非目标保持，见 SPEC 非目标清单） |

## 验收自查

1. **AGENTS.md 队列数 = 9**：对照 `fetcher/fetcher/cli/main.py` `_build_registry()` 实测 9 条 QueueSpec：
   `crawl_1688_contact` / `crawl_mic_contact` / `crawl_mic_shop` / `crawl_1688_shop` / `crawl_1688_company` / `wa_check` / `crawl_fb_post` / `discover_fb` / `crawl_fb_group` ✅
2. **AGENTS.md 批次模型清单含两新类型**：`platform/server/app/runner.py` BATCH_TYPES 实测含 `fb_post` / `fb_discover` / `fb_group`（另 wa_check），与文档列举一致 ✅
3. **渠道文档 §10 与实现一致**：`FetchDdgSerp`（`atoms/facebook_discover.py`）、`FbDiscoverTask`（`sites/facebook/discover_task.py`）、`FbGroupTask`（`sites/facebook/group_task.py`）、`discover_fb`/`crawl_fb_group` 队列、平台 `fb_discover`/`fb_group` 批次均在码，Step 5.1 冒烟已验证全链路 ✅
4. **渠道文档 §12 与实现一致**：key 仍走环境变量（BRIGHTDATA_API_KEY / APIFY_TOKEN，未入 DB，本期非目标保持），表述准确未夸大 ✅
5. 未改其他文件；两份文档其余内容（含 daemon 有头、WA_CHECK_ACCOUNTS）原样保留 ✅

## Commit

- `docs(fb): Step 5.3 同步 AGENTS.md 队列 9 条与批次模型、渠道文档发现层已落地`
- 仅 add：AGENTS.md、docs/channel-research/facebook-groups.md、本 Step brief/report（无 `-A`/`.`/`-am`）
