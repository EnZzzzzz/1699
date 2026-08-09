# Step 5.3 — 文档同步

> 这是你的需求唯一来源。PLAN Step 5.3 原文 + 精确要求抄录如下。

## PLAN Step 5.3 原文（验收以 checkbox 为准）

- [ ] AGENTS.md：§1 队列数量 7→9（discover_fb / crawl_fb_group）、§5 批次模型清单
      补两类型
- [ ] docs/channel-research/facebook-groups.md §10/§12「未做」清单更新（发现层已
      自建落地、群 feed 已接队列）
- 预估 15min；验收：两文档与实现一致

## 精确改动要求

### 1. AGENTS.md（/Volumes/DataDrive/proj/public/1699/AGENTS.md）

- **§1（12-13 行）**：「7 条 work_items 队列：1688/madeinchina 双站 contact +
  shop/company feeder + wa_check + crawl_fb_post」→ 改为 **9 条**并补两新队列：
  「...双站 contact + shop/company feeder + wa_check + crawl_fb_post +
  discover_fb + crawl_fb_group」。保持行内列表风格（<= 宽度可折行）。
- **§5 批次模型清单（64 行）**：「（1688/madeinchina 采集、wa_check、fb_post 均走
  此模型）」→ 补两类型：「（1688/madeinchina 采集、wa_check、fb_post、fb_discover、
  fb_group 均走此模型）」。
- **不动其他内容**（daemon 有头/WA_CHECK_ACCOUNTS 等已有改动是 daemon-headed-queues
  工作线并入的，保留）。

### 2. docs/channel-research/facebook-groups.md

- **§10「未做」段（约 153-159 行）**：原写「Google 发现层（P2 Apify SERP 路线
  规划就绪，待 APIFY_TOKEN 实调 spike...）」。更新为：发现层已换 **DDG html 端点
  自建**落地（`docs/feat_2026-08-09_fb-discovery-group-feed/`，fetcher 侧
  FetchDdgSerp 原子 + FbDiscoverTask + discover_fb 队列 + 平台 fb_discover 批次），
  群 feed 已接队列（FbGroupTask + crawl_fb_group + 平台 fb_group 批次）；Apify
  SERP 路线仍为非目标（自建优先）。
- **§12「未做」段（约 223-226 行）**：原写「发现层 P2 待 token 推进」。更新为：
  发现层已自建落地（DDG SERP，见上）；两家 key 沿用环境变量（本期未入 DB，
  非目标保持）。
- 保持文档既有语气与格式（「未做（日期更新）」前缀可改为「已做（2026-08-09 三期
  落地后更新）」或保留「未做」但内容改为剩余项——以准确反映现状为准）。

## 协调者裁定

1. 只改这两个文件；纯文档，无测试可写（TDD 例外：文档类）。
2. 准确反映实现现状（Step 5.1 冒烟已验证全链路），不夸大。
3. 验收：两文档与实现一致（AGENTS.md 队列数 9、批次模型含两新类型；渠道文档
   §10/§12 反映发现层自建 + 群 feed 接队列）。

## Commit 约束

- 只 `git add`：AGENTS.md、docs/channel-research/facebook-groups.md、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`docs(fb): Step 5.3 ...`。

## 报告格式

完整报告写入 /Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-5.3-report.md：
- 改了什么（两文件各处的 old→new 摘要）
- 验收自查（AGENTS.md 队列数/批次清单、渠道文档 §10/§12 与实现一致性）

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行文档总结
- 疑虑（如有）
- report 路径
