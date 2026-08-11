# Facebook 群组采集 — 现行方案与运行结论

> 2026-08-11 合并版：整合原 `facebook-groups.md`（可行性调研）、
> `facebook-runtime-conclusions.md`（运行结论）、`facebook-summary.md`（选型经济账），
> 只保留**现行方案**与仍有效的实测结论；被取代路线的过程叙述已删（git 历史可查）。
> 业务目标：采集中国外贸从业者的 WhatsApp 联系方式（只要中国号）。

## 1. 现行管线（三个常驻脚本）

```
BD Google SERP 数据集                BD 群 feed 数据集                 Apify 查号 actor
site:facebook.com/groups <词>   →    按群 URL 抓最新 15 帖       →     批量验证注册态
fb_group_discover_bd.py              fb_group_bd.py                    wa_check_apify.py
        ↓ fb_groups                        ↓ fb_contacts（四桶）            ↓ wa_registered / wa_source
```

| 脚本 | 职责 | 平台 | 关键参数（默认） |
|---|---|---|---|
| `scraper/fb_group_discover_bd.py` | 群发现：BD SERP 查 `site:facebook.com/groups <关键词>`，群落 `fb_groups`（source='bd_serp'） | Bright Data | `--keywords` 16 词（外贸/货代/跨境电商/亚马逊卖家/china sourcing + 新能源/锂电池/光伏/solar panel + 工程机械/挖掘机/重型机械/machinery + 汽车配件/汽配/auto parts × whatsapp/微信），`--pages 1`，`--interval 3600` 每小时一轮 |
| `scraper/fb_group_bd.py` | 联系人采集：BD 群 feed 数据集按群抓帖，`parse_post` 四桶分号落 `fb_contacts` | Bright Data | `--posts 15`、`--cooldown-hours 24`、`--conc 25`、`--interval 300` |
| `scraper/wa_check_apify.py` | WA 注册态验证，回写 `wa_registered` / `wa_source` | Apify | `--bucket declared_wa,cn_uncertain --min-batch 100`（攒够 100 个才开火），循环间隔 10 分钟 |

三个脚本都是常驻看护循环；BD 报 `Customer is not active`（欠费）时自动 10 分钟重试，
充值后无需重启即可自愈。凭证存 SQLite `providers` 表（kind='brightdata' / 'apify'，
apify 一行一账号、402 自动轮换），代码里不写死。

### 采集端的两个降本机制（2026-08-11 落地）

- **增量抓取**：重抓群时 trigger 带 `start_date`=该群 last_crawled_at 日期
  （MM-DD-YYYY 官方格式，`--date-format iso` 可切换）。无新帖的群 BD 返回
  `dead_page` 错误记录**不计费**；首次采的群仍全量拉 15 帖。
- **零产出群淘汰**：`due_groups` 按 `fb_contacts.group_id` 子查询计数，
  零产出且已采过的群冷却 ×`--zero-cooldown-factor`（默认 3），不重复烧钱。
  实测 1103 已采群中 623 个零产出被降频。
- 注意：两个机制只对**重抓轮**生效，首次全量扫新群的成本不变。

## 2. 路线为什么长这样（仍有效的底层结论）

- **FB 匿名采集面极窄**：群搜索/群主页匿名一律 302 登录墙；公开群帖 permalink
  匿名可读，但纯 HTTP 被 TLS/HTTP 指纹拦截（一律 400），必须真实浏览器渲染；
  评论区匿名可见性随会话随机，不能当稳定采集面。→ 采集交给 BD 云端执行，
  本地不再自渲染（原 CloakBrowser 路线 ~10.6s/帖，已退役）。
- **私密群花钱也买不到**：官方 Graph API、Ad Library API、Apify/BD/Oxylabs/Decodo
  全部只支持公开群、全部不支持登录态；登录态批量翻群 feed 封号率高，已否决。
  官方 API 全部不接（Graph API 需 Page Public Content Access 过审无望；
  Ad Library 商业广告仅欧盟定向可查）。
- **分桶策略**（`parse_post` 四桶，fetcher/sites/facebook/post.py）：
  `declared_wa`（帖内自声明 WhatsApp，实测注册率 **93%**，主价值桶）、
  `cn_uncertain`（裸手机号，实测注册率仅 **6%**，低价值）、
  `overseas`（非中国号）、群邀请链接。
- **只保留中国号**（2026-08-10 晚定口径）：裸 11 位 1 开头或 86/0086+11 位，
  非中国号落库前即弃（fb_group_bd.py `is_cn_number` 过滤）。

## 3. Bright Data 接入要点（坑位，勿踩）

- 群帖发现**只能异步** `POST /datasets/v3/trigger`（dataset_id=
  `gd_lz11l67o2cb3r0lkj3`）；误用同步 `/scrape` 会报误导性错误
  `Customer is not active`（账号本身正常）。请求体是**裸数组** `[{"url":...}]`。
- 逐帖 collect-by-URL 数据集（gd_lkaxegm826bjpoo9m5）对群帖全部 dead_page，
  不可用——只能按群 URL 抓 feed。
- trigger→progress→snapshot 三段式，单群 ~30s，高并发排队时**轮询超时要给到
  900s**（300s 实测会误判失败）。
- **扣费实测 ~2.9 credits/帖**（非文档的 $1.5/1K 条口径，全量校正后实际单价
  ~$2.5/千帖）；免费 5000 credits/月 ≈ 1700 帖。真欠费时也报
  `HTTP 400 Customer is not active`，与同步误报同形，注意区分。
- 私密群匿名抓不到（快照 error 记录），库内全是公开群，无实际损失。

## 4. Apify 查号要点

- actor：`devscrapper~whatsapp-number-validator`，**$0.004/号**，支持 100 号/run
  批量（脚本已按 100 分批）。
- **限流 2 run/分钟**：超限 run 直接 FAILED，限流原因要二次查
  `/v2/actor-runs/{id}` 的 statusMessage；脚本处理 = 退避 70s 重试 ×6。
- `status=invalid`（虚拟段/运营商拒收）永远查不出，落库标 `wa_source='invalid'`
  且 `wa_checked_at` 置位，免疫重查不浪费额度。
- 中国号库内可能存裸 11 位或带 86，匹配做 86 前缀双向兼容。
- 多账号：`providers` 表 kind='apify' 一行一账号，402 欠费自动轮换。
- Baileys 小号协议查号（xiaohao-4/5）已被 WA 403 封死，查号全走 Apify。

## 5. 成本与产能实测

**首日全量（2026-08-10，612 存量群 × 15 帖）**

| 指标 | 数值 |
|---|---|
| 联系人 | 435 → 1797（+1362，后按中国号口径清理至 865） |
| BD 花费 | $23.34（含试错），实际单价 ~$2.5/千帖 |
| 查号 | 1584 号全查完，$6.34（两个 Apify 账号轮换） |
| 注册率 | declared_wa **93.1%** / overseas 91.2% / cn_uncertain **6.0%** |

**$10 轮（2026-08-11 02:20–03:12，52 分钟烧完 $10）**

| 指标 | 数值 |
|---|---|
| 采集群 | 454（首次全量 15 帖/群，零产出率 **72%**） |
| 新增号码 | 245（单号成本 $0.041 ≈ ¥0.29） |
| 验证 | 155 号（$0.62）：注册 76 / 未注册 26 / 无效 53，注册率 74.5% |

教训：这轮单产（0.54 号/群）只有历史水平（1.05 号/群）的一半——
采的是积压待采群 + 新行业英文关键词（machinery/auto parts whatsapp）带出的
大量海外群（零产出率 72% vs 历史 56%）；SERP 发现另分走 ~13% 花费。
关键词质量直接决定单产，增量抓取+零产出淘汰的收益在重抓轮才体现。

## 6. 退役路线（一句话存档）

- **CloakBrowser 本地渲染 permalink**（`scraper/fb_group_wa.py`，留档）：慢、
  占 license 席位 → 2026-08-10 被 BD 群 feed 全面取代。
- **DDG 直连 / Apify Google SERP 群发现**：DDG 单 IP 限流率 85-95% 不可用；
  Apify SERP 能用但收费 → 现为 BD SERP（`fb_group_discover_bd.py`）。
- **Apify Groups Scraper 采群帖**：$5/1K 帖，比 BD 贵 3 倍，未采用。
- **青果代理出海**：通道是给国内站设计的，DDG/FB 都在墙外，用不上。
- **fetcher 平台侧 fb 链路**（atoms/daemon 队列/平台批次）：仍连通，留作备用；
  现役生产链路是上述三个 scraper 常驻脚本。

## 7. 深入调研存档

- 官方渠道（Graph API / Ad Library / 网页版广告库 / Meta Content Library）：
  `facebook-apis/README.md`、`facebook-apis/AD_LIBRARY.md`。
- 第三方服务横向对比（Apify / Bright Data / Oxylabs / Decodo 详档）：
  `facebook-apis/third-party-*.md`。
- 网页版广告库（匿名可搜全球在投广告）是二期候选补充线索源，未实施。
