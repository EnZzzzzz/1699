# Step 2.4 — 群采集运行时冒烟

> 这是你的需求唯一来源。PLAN Step 2.4 原文 + 环境事实抄录如下。

## PLAN Step 2.4 原文（验收以 checkbox 为准）

- [ ] 起 daemon（`--queues crawl_fb_group --local-workers 1`），手工灌 1 条
      work_items（真实群 URL × provider，key 用环境变量或 mock）
- [ ] 观察：FetchFbGroupPosts 执行 → fb_contacts 新增（post_url 溯源正确）→ 群
      done + post_count/has_contact 回写；缺 key 场景验证 FATAL → 群 failed
- [ ] 冒烟记录写入 ledger.md
- 预估 30min；验收：群状态机完成一轮 pending→done（或 key 缺失→failed），
      fb_contacts 落号正确

## 环境事实（协调者已验证，勿重复调查）

1. **无真实 key**：BRIGHTDATA_API_KEY / APIFY_TOKEN 环境变量均未设置（本机）。
   按 SPEC §11.3 用 mock 场景覆盖验收 #2：**不依赖真实 key**。
2. **缺 key 行为（代码已核实）**：FetchFbGroupPosts 原子缺 API key → FATAL；
   LocalLoop（fetcher/fetcher/control/local_loop.py:56-60）对 FATAL 调
   `task.on_giveup(ctx, item, detail, "fatal")` 后停止；FbGroupTask.on_giveup
   会 `mark_fb_group_failed(item["url"])` → **群置 failed**。这是真实链路可验证的
   分支。
3. **done 分支必须 mock**：无真实 key 时 FetchFbGroupPosts 永远 FATAL，无法真实走
   done。用 mock 场景（monkeypatch FetchFbGroupPosts.run 返回构造的帖子数据，或
   mock fetch_brightdata_posts）驱动 FbGroupTask 全链路（acquire→fetch→on_success），
   在临时库验证 fb_contacts 落号 + 群 done 回写。这与 Step 2.1 的单元测试不同：
   冒烟要验证的是 **daemon 装配下的完整流转**（work_items 认领 → 状态机 → 落库），
   尽量用真实 daemon 起 crawl_fb_group 队列 + mock 原子注入（python 冒烟脚本内
   monkeypatch 后起 LocalLoop，或起 daemon 前用 sitecustomize/patch 注入——选你
   能力范围内最贴近真实链路的方案，在 report 里说明方案）。
4. **临时 DB 用 `--db`**：daemon 只认 `--db` CLI 参数（Step 1.5 已证实 FETCHER_DB_PATH
   无效）。临时库 /tmp/fb_group_smoke_<ts>/1688.db，绝不碰生产库 .cache/1688.db。
5. **同机生产 daemon 在跑**（PID 34402）：冒烟 daemon 只跑 crawl_fb_group 单队列
   local 消费者，不碰生产队列；consumer_status local0 心跳会短暂同键（10s 心跳
   自动写回，Step 1.5 已验证无害）。
6. **真实群 URL 示例**（可作 mock 输入）：https://www.facebook.com/groups/
   676368063029200/（Step 1.5 冒烟已确认真实存在）。

## 冒烟步骤（建议）

**A. 缺 key 真实链路（FATAL → 群 failed）**
1. 临时库建表：`platform/server/.venv/bin/python -c "from fetcher import ShopDB; from pathlib import Path; ShopDB(Path('/tmp/.../1688.db'))"`。
2. 手工 INSERT 1 条 work_items（queue='crawl_fb_group'，site=NULL，requires='["local"]'，
   payload `{"url":"https://www.facebook.com/groups/676368063029200/","provider":"brightdata","limit":50}`）。
3. 起 daemon（后台）：`python -m fetcher daemon --db <临时库> --queues crawl_fb_group
   --local-workers 1`（不带 key 环境）。
4. 观察日志：原子 FATAL（缺 key）→ on_giveup → 群 status=failed。
5. 查询：fb_groups 该行 status='failed'；work_items 终态。

**B. mock done 链路（pending→done + fb_contacts 落号）**
1. 新建临时冒烟脚本（/tmp 下，不入库）：构造临时 ShopDB → 插入 1 条 pending 群行 +
   1 条 work_items → mock `fetcher.atoms.facebook_group.FetchFbGroupPosts.run` 返回
   构造的 ActionResult（含 posts 带 phones）→ 用真实 daemon 的装配方式跑一轮
   LocalLoop（或直接驱动 FbGroupTask 方法链，report 说明方案）→ 验证：
   - fb_contacts 新增行（post_url=帖子 URL 溯源、group_id 正确）
   - 群 status='done' + post_count + has_contact + last_crawled_at 回写
   - work_items 终态 done
2. 若你选择「monkeypatch 后起真实 daemon 进程」不可行（daemon 子进程内 patch 不
   传递），退而驱动 FbGroupTask 全方法链 + LocalLoop（同进程 patch 生效）——
   report 里写明方案与理由。

## 冒烟记录要求（追加到 ledger.md）

```
## Step 2.4 冒烟记录（<日期时间>）
- 临时 DB：<路径>
- A. 缺 key 链路：daemon <PID>，FATAL 观测 <日志>，群 <url> status=failed ✓
- B. mock done 链路：方案 <说明>，fb_contacts 新增 <n> 行（post_url 溯源）、
  群 status=done + post_count=<n> + has_contact=<0/1> ✓
- 验收判定：<满足/不满足 + 原因>
```

## 你的工作

1. 按上述步骤执行（命令输出全程保留在 report）。
2. 验证验收标准（A 或 B 至少走通一轮完整状态机；有 fb_contacts 落号证据）。
3. **不需要 commit 代码**（临时脚本在 /tmp 不入库）——ledger.md 冒烟记录需 commit
   （只 add ledger.md，禁止 -A）。发现代码 bug → BLOCKED 上报（不自己修）。
4. 完整证据写入 report。

工作目录：/Volumes/DataDrive/proj/public/1699

## 报告格式

完整报告写入 `/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.4-report.md`：
- 执行过程与命令输出（A/B 两段）
- **验收证据**：fb_contacts/fb_groups/work_items 查询结果（真实行数+内容）、状态流转、日志片段
- ledger.md 追加内容
- 疑虑/观测

然后只回复（15 行以内）：
- **状态：** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- commit（短 SHA + 标题）
- 一行验收结论
- 疑虑（如有）
- report 路径
