# task-1.1-brief.md — Step 1.1 fetcher 数据面：两表 + 四个写函数

需求唯一来源：PLAN Step 1.1 + SPEC §4.1/§4.2/§4.3/§8（职责表）。本文件是
本 Step 的完整需求提取，精确值只出现在本文件与上述 SPEC 章节。

## 目标

在 `fetcher/fetcher/db.py`（ShopDB 类）新增 FB 数据面：

1. 两张表（schema 精确值见 SPEC §4.1/§4.2，原文照抄）：
   - `fb_posts`：帖子发现表，url UNIQUE，状态机 `pending → in_progress →
     done/failed`（对齐 shops 语义）。
   - `fb_contacts`：号码表，number UNIQUE，四桶分桶 + wa_source 三态。
   - 建表时机对齐 work_items：加入 SCHEMA（executescript，
     CREATE TABLE IF NOT EXISTS 幂等）；索引
     `idx_fb_posts_status ON fb_posts(status, id)`。
2. 四个写函数（全部短事务 + PRAGMA busy_timeout 已在连接层，WAL 安全）：
   - `topup_fb_post_work_items(queue, site, limit)`：复刻
     `topup_contact_work_items` 事务模式（BEGIN IMMEDIATE 单事务 SELECT
     pending → INSERT work_items → 源行置 in_progress）。payload 键
     `{"url","domain","name"}`（SPEC §3.2：domain=群 URL、name=群名、
     url=帖子 permalink）；fb_posts 无群 URL 列 → domain 由
     `https://www.facebook.com/groups/{group_id}` 拼接（group_id 为空则
     domain=""）。limit>0 限量（<=0 不限）。返回入队行数。
   - `save_fb_contacts(post_url, group_id, phones)`：phones 为 parse_post
     输出 `[{"number","bucket","source"}, ...]`；逐号 INSERT OR IGNORE
     （number UNIQUE 去重；同号后帖不覆盖 first_seen/post_url —— SPEC §8
     职责表）。declared_wa 桶 → `wa_source='declared'`；cn_uncertain /
     overseas 桶 → `wa_source=NULL`。返回本次实际新增行数。
   - `mark_fb_post_done(url, has_contact)`：`status='done'` + `has_contact`
     + `fetched_at`（北京时间字符串）。
   - `mark_fb_post_failed(url)`：`status='failed'`。

## 验收（TDD 先行）

`fetcher/tests/test_db_fb.py`（unittest 风格，参照 test_wa_task.py 的
临时库模式）覆盖：
- 建表幂等：同一库文件重复 ShopDB() 初始化无错，两表存在；
- topup 状态流转与防重：seed N 条 pending → topup → work_items 生成
  （payload url/domain/name 正确、queue/site 透传）、fb_posts 置
  in_progress；再 topup → 0 新行；
- 并发 topup 无双写：双线程各自持独立 ShopDB 实例（sqlite 连接不可跨
  线程）同刻 topup，断言 work_items 总数 = pending 总数、无重复行、
  无漏置 in_progress（BEGIN IMMEDIATE 串行化写）；
- save_fb_contacts 去重与 wa_source 规则：declared_wa→'declared'；
  cn_uncertain/overseas→NULL；同号二次写入不覆盖 first_seen_at/post_url；
- mark_* 流转：done（status/has_contact/fetched_at）、failed。

## 硬约束

- 不动既有 37 例 FB 测试、不动 scraper/ util/。
- 时间戳一律北京时间字符串（`%Y-%m-%d %H:%M:%S`），与 db.py `_now()`
  一致。
- 中文注释；模块职责一行注释。
- TDD Iron Law：先写失败测试（亲眼看它失败）→ 最小实现 → 转绿。
