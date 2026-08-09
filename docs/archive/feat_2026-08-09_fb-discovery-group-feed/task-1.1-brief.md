# Step 1.1 — DB 前置：fb_groups 建表 + save_fb_posts + upsert_fb_groups（TDD）

> 这是你的需求唯一来源。PLAN Step 1.1 原文 + SPEC 相关精确规格抄录如下。

## PLAN Step 1.1 原文（验收以 checkbox 为准）

- [ ] `fetcher/fetcher/db.py` 建表区追加 fb_groups 表 + idx_fb_groups_status 索引
      （SPEC §4.1 精确 SQL，幂等）
- [ ] 实现 `save_fb_posts(keyword, source, posts) -> int`（INSERT OR IGNORE，url
      UNIQUE，带 keyword/source/group_id/group_name/first_seen_at；返回新增数）
- [ ] 实现 `upsert_fb_groups(groups) -> int`（INSERT OR IGNORE，url UNIQUE；已存在
      行不动 status；返回新增数）
- [ ] 测试（新文件 `fetcher/tests/test_db_fb_groups.py`）：建表幂等 + save_fb_posts
      去重/溯源 + upsert_fb_groups 去重/不动状态（参照 test_db_fb.py 模式）
- [ ] spike 复核：DDG 恢复后单次验证 `&s=10` 分页 200 态（若限流窗口内则等待）；
      复核结论回填 SPEC §8.1
- 预估 40min；验收：上述测试全绿 + `cd fetcher && ../platform/server/.venv/bin/
  python -m unittest discover -s tests -p "test_db_fb_groups.py"`

## SPEC §4.1 新表 fb_groups（精确 SQL，幂等）

```sql
CREATE TABLE IF NOT EXISTS fb_groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,     -- 群 URL https://www.facebook.com/groups/{gid}
    group_id        TEXT,                     -- 群 id（数字或 slug，URL 解析）
    name            TEXT,                     -- 群名（发现层取自 SERP 标题，溯源用，近似值）
    source          TEXT NOT NULL DEFAULT 'ddg',  -- 发现来源 ddg / fb_post（帖派生）
    status          TEXT NOT NULL DEFAULT 'pending', -- pending/in_progress/done/failed
    post_count      INTEGER,                  -- 已采帖数（fb_group on_success 回写）
    has_contact     INTEGER,                  -- 是否提到联系方式（fb_group 回写）
    first_seen_at   TEXT NOT NULL,            -- 北京时间字符串
    last_crawled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fb_groups_status ON fb_groups(status, id);
```

状态机对齐 fb_posts：`pending → in_progress → done/failed`。

## SPEC §5.6 fetcher/db.py 新增（本 Step 只做前两个写函数）

- 建表区：fb_groups 表 + idx_fb_groups_status 索引（§4.1，幂等 CREATE IF NOT EXISTS）。
- `save_fb_posts(keyword, source, posts) -> int`：INSERT OR IGNORE（url UNIQUE），
  带 keyword/source/group_id/group_name/first_seen_at；返回新增行数。
- `upsert_fb_groups(groups) -> int`：INSERT OR IGNORE（url UNIQUE），status 默认
  pending；已存在行不动 status（保持采集进度）；返回新增行数。
- （mark_fb_group_done / mark_fb_group_failed / reset_fb_groups_in_progress 属
  Step 2.1，本 Step 不做。）

## 协调者裁定（覆盖 SPEC 未定细节）

1. **upsert_fb_groups 的 source 语义**：group 条目可带可选 `"source"` 键，缺省
   `"ddg"`。FbDiscoverTask（Step 1.3）传的条目不带 source 键（默认 ddg）；
   FbPostTask（Step 2.3）会传 `"source": "fb_post"`。实现时按 entry 的 source 值
   落库，缺省 'ddg'。
2. **save_fb_posts 的 posts 条目键**：`{"url", "group_id", "group_name"}`。
3. **时间戳**：一律 `_now()`（db.py 模块内已有，北京时区字符串）。
4. **事务**：短事务 + busy_timeout（ShopDB.__init__ 已设 30000，直接用
   self.conn.execute + commit，参照 save_fb_contacts / mark_fb_post_done 模式）。
5. **spike 复核结论（协调者已实测，2026-08-09）**：
   `https://html.duckduckgo.com/html/?q=site%3Afacebook.com%2Fgroups+%E5%A4%96%E8%B4%B8+whatsapp&s=10`
   → HTTP 200、响应 33KB、含 `class="result__a"` 结果锚点、无 anomaly 字样。
   **你不需要再发真实请求**（限流预算留给 Step 1.5 冒烟）。把上述结论回填
   SPEC §8.1 表格「DDG 分页」行的依据（追加一行日期+结论）。

## 代码库上下文（brief 之外你需要知道的）

- `fetcher/fetcher/db.py`：
  - `SCHEMA` 常量（约 79 行起）含全部 CREATE TABLE/INDEX，fb_posts（200 行起）
    与 fb_contacts（218 行起）在其内；fb_groups 表追加在 fb_contacts 之后、
    consumer_status 之前即可（保持现有注释风格）。
  - `class ShopDB`（254 行起）：`self.conn`（row_factory=Row）、`_now()` 在 250 行。
  - 既有 FB 写函数模式参照：`save_fb_contacts`（791 行）、`mark_fb_post_done`
    （819 行）、`reset_fb_posts_in_progress`（836 行附近）——短事务 + commit。
  - **注意**：db.py 是既有大文件，只在建表区与写函数区做增量，不改其他区域。
- `fetcher/tests/test_db_fb.py`：测试模式参照（`from fetcher import ShopDB`、
  `tempfile.TemporaryDirectory` + `ShopDB(Path(tmp)/"t.db")`）。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest
  discover -s tests -p "test_db_fb_groups.py"`（venv 已就绪，勿新建环境）。

## TDD 纪律（必须遵守）

1. 先写失败测试 → 亲眼看它失败（RED，记录输出）→ 最小实现 → 看它通过（GREEN）。
2. 测试覆盖：
   - 建表幂等（重复初始化不报错、表与索引存在）
   - save_fb_posts：URL 去重（同 url 二次插入返回 0）、keyword/source/group_id/
     group_name 溯源落库、返回新增数正确
   - upsert_fb_groups：url 去重、已存在行 status 不被改动（先插入一条 pending，
     再同 url 不同 name 的 upsert → 行数 0 且 status 保持原值）、source 缺省 ddg、
     显式 source 落库、返回新增数正确
3. 全部测试通过后再跑一次相关回归：`test_db_fb.py`（`-p "test_db_fb*.py"`）。

## Commit 约束（重要）

- **只 `git add` 你自己的文件**：`fetcher/fetcher/db.py`、`fetcher/tests/test_db_fb_groups.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/SPEC.md`（§8.1 回填）、本 brief/report 文件。
- **严禁** `git add -A` / `git add .` / `git commit -am`：工作区有另一条工作线
  （daemon-headed-queues）的未提交改动（runner.py 等），与本任务无关，不得卷入。
- commit message 风格：`feat(fb): Step 1.1 ...`（参照 git log 既有风格）。
