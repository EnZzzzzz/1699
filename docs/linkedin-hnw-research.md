# 领英美国高净值人群采号调研与验证（2026-08-24）

> 需求：采美国手机号，高净值人群，需带职业、性别字段。
> 结论：**管线技术成立，但有效命中率约 39%、号码为历史号码包不区分手机/座机，
> 单条州级验证带号线索 ≈ $0.046**。是否常驻取决于人工抽查号码真实性的结果。

## 1. 方案选型（Apify actor 调研）

领英无任何 actor 能直接拿到手机号（平台不公开），只能拼「领英选人 + 查号 actor 补电话」两段式：

| 环节 | Actor | 价格 | 说明 |
|---|---|---|---|
| 搜人 | `harvestapi~linkedin-profile-search` | Full $4/千条 + 搜索页 $0.1/25 条 | 无 cookie，按地区/职位/公司过滤，Full 模式含 headline/经历/位置 |
| 查号 | `apivault_labs~skip-trace-people-finder` | $6.5/千条命中记录，查不到不收费 | 输入「姓名; 城市, 州缩写」，公开记录源返回电话/地址/亲属 |
| 备选查号 | parseforge/intelscrape/bovi 等 skip-trace actor | 同价位 | Spokeo 等同类数据源 |
| profile 补全 | `dev_fusion~linkedin-profile-scraper` | $10/千条 | 第三方 enrichment 手机号，实测命中率 20–60%（B2B），锁付费套餐，未采用 |

计费坑：Apify 全 pay-per-event，事件定义各异；5/7 的 actor 无套餐折扣；第三方开发者可随时改价。

## 2. 字段可行性

| 需求字段 | 结论 |
|---|---|
| 职业 | ✅ 领英核心字段（headline + 完整经历）。注意职位过滤是模糊匹配，结果混入非高管，需按 headline 二次过滤 |
| 性别 | ⚠️ 领英无性别字段，按 first name 推断。genderize.io 免费版 100 次/天不够正式用；正式方案用美国 SSA 名字-性别离线数据集（免费无限制） |
| 美国手机号 | ⚠️ skip-trace 可查，但同名错人严重 + 历史号码包（详见 §3） |
| 高净值 | ❌ 无财富字段，只能职位代理：CEO/Founder/Owner/President/Managing Partner + 公司规模 |

## 3. 100 条小样验证结果（总花费 $1.81）

验证脚本：`util/_test_linkedin_hnw.py`；明细：`.cache/linkedin_hnw_test.json`。

| 环节 | 结果 |
|---|---|
| ① 搜人 | 100 条 profile，$0.80 |
| 位置可解析到城市+州 | 78/100 |
| ② 查号查到人 | 89/100 |
| 查到人且带电话 | 62/100（名义命中率 62%） |
| 电话记录地址与领英所在州一致 | **39/100（有效口径）** |
| 单条州级验证带号线索成本 | **≈ $0.046（千条约 $46）** |

查号质量问题（实测明细）：

- **同名错人严重**：一个输入返回多个同名者（实测 Lincoln NE 的目标返回 TN/NJ/OH 三地同名人的号码包），甚至把亲属当本人。只有城市级位置消歧不够，正式管线需地址史/年龄/亲属交叉验证。
- **历史号码包**：每条记录中位 5 个、最多 62 个历史号码，不区分手机/座机、不标在用车。
- 高净值人群天然更难查（数据经纪 opt-out、资产挂 LLC/信托名下）。

失败原因（已修复）：actor 单 run 时间预算截断 → 分批 50；姓名带 "Randy Z." 中间名缩写被名字校验拒 → 脚本剥除。

## 4. 合规前提（美国）

- TCPA 管未经同意的电话/短信营销（按通计费赔偿，集体诉讼高发）；DNC 名单必须过滤；CCPA 及各州隐私法适用。
- skip-trace 数据源自带 complianceNotice：非 FCRA 报告，禁止用于信贷/就业/住房/保险决策。

## 5. 下一步

~~挑 20 条州级验证通过的线索人工抽查号码真实性（反查/试拨），命中率决定管线是否值得常驻。~~

2026-08-25 更新：用户拍板直接常驻——`scraper/linkedin_us_search.py`（目标 500 个
WA 已注册美国号，仅州级验证通过的号入 `us_contacts`，预算刹车 $80，启动命令与
表口径见 AGENTS.md §1 ④ / §4）。人工抽查号码真实性仍待做；性别推断改用 SSA 离线
数据集（ssa.gov 直连 403，names.zip 需经 web.archive.org 镜像取回放
`.cache/ssa_names/` 构建 `.cache/ssa_gender.json` 缓存）。

## 6. 脚本用法

```bash
python3 util/_test_linkedin_hnw.py                       # 100 条全流程
python3 util/_test_linkedin_hnw.py --limit 20 --dry-run  # 小样冒烟（只搜人）
python3 util/_test_linkedin_hnw.py --titles CEO,Founder --location "Texas"
python3 util/_test_linkedin_hnw.py --search-run-id <runId>  # 中断续跑，不重复扣费
```

- token 取自 providers 表（kind=apify），与 wa_check_apify.py 同口径。
- 已知坑：api.apify.com 偶发 TLS 层断连（2026-08-24 实测约 10 分钟自愈），脚本已内置重试 + run 续跑。
