# Step 1.1 Report — DB 前置：fb_groups 建表 + save_fb_posts + upsert_fb_groups（TDD）

> 状态：DONE。需求唯一来源 = task-1.1-brief.md，实现严格按 brief/协调者裁定，不多不少。

## 实现了什么

1. **建表区**（`fetcher/fetcher/db.py` SCHEMA 常量，fb_contacts 之后、consumer_status 之前）：
   追加 `fb_groups` 表 + `idx_fb_groups_status` 索引，SQL 与 SPEC §4.1 逐字一致（CREATE IF NOT EXISTS 幂等），
   注释沿用 db.py 既有风格（状态机对齐 fb_posts、source 语义、回写列说明）。
2. **写函数区**（`class ShopDB`，`reset_fb_posts_in_progress` 之后、category_progress 分区之前，与既有 FB 写函数相邻）：
   - `save_fb_posts(keyword, source, posts) -> int`：INSERT OR IGNORE（url UNIQUE 去重），
     落 keyword/source/group_id/group_name/first_seen_at（`_now()` 北京时间字符串），返回新增行数；
     posts 条目键按协调者裁定 `{"url", "group_id", "group_name"}`；空 url 跳过。
   - `upsert_fb_groups(groups) -> int`：INSERT OR IGNORE（url UNIQUE 去重），status 默认 pending；
     已存在行不动 status/name（保持采集进度）；source 按 entry 可选键落库、缺省 `'ddg'`
     （`g.get("source") or "ddg"`），返回新增行数。
   - 两者均短事务 + `self.conn.commit()`，busy_timeout 由 `ShopDB.__init__` 已设 30000，
     完全参照 save_fb_contacts / mark_fb_post_done 既有模式。
3. **测试**：新文件 `fetcher/tests/test_db_fb_groups.py`（7 个用例，模式参照 test_db_fb.py）。

## 测了什么、测试结果

| 用例 | 覆盖点 | 结果 |
|---|---|---|
| test_tables_created_and_idempotent | 二次初始化不报错；fb_groups 表 + idx_fb_groups_status 索引存在 | ✅ |
| test_save_posts_traceability_and_count | keyword/source/group_id/group_name 溯源落库、status=pending、first_seen_at 非空、返回 2 | ✅ |
| test_save_posts_explicit_source | source='fb_post' 显式落库、返回 1 | ✅ |
| test_save_posts_dedup_same_url_returns_zero | 同 url 二次插入返回 0、仅 1 行、首见 keyword 不覆盖 | ✅ |
| test_upsert_groups_default_source_and_count | source 缺省 ddg、status=pending、name/group_id 落库、返回 2 | ✅ |
| test_upsert_groups_explicit_source | source='fb_post' 显式落库、返回 1 | ✅ |
| test_upsert_groups_dedup_keeps_status_and_name | 已存在行（置 in_progress 模拟采集进行中）同 url 不同 name/source upsert → 0 行、status/name 保持原值 | ✅ |

- 验收命令：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_db_fb_groups.py"` → **7 tests OK**。
- 相关回归：`-p "test_db_fb*.py"`（test_db_fb.py 10 例 + 新 7 例）→ **17 tests OK**，输出干净。

## TDD 证据

- **RED**：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_db_fb_groups.py"`（实现前）
  → `Ran 7 tests ... FAILED (failures=1, errors=6)`。失败即预期：
  - `AssertionError: 'fb_groups' not found in {...}`（表未建）；
  - 6 个 `AttributeError: 'ShopDB' object has no attribute 'save_fb_posts'/'upsert_fb_groups'`（函数未实现）。
  符合预期——测试先于实现，验证的是真实 DB 行为而非 mock。
- **GREEN**：同一命令（实现后）→ `Ran 7 tests in 0.035s OK`。

## SPEC §8.1 回填（协调者裁定第 5 条，不重发真实请求）

DDG 分页行「依据」列追加：
> **2026-08-09 复核（PLAN Step 1.1）：`&s=10` 实测 HTTP 200、响应 33KB、含 `class="result__a"` 结果锚点、无 anomaly 字样，分页可用**

（协调者已实测，限流预算留给 Step 1.5 冒烟。）

## 改动的文件

- `fetcher/fetcher/db.py`（建表区 +18 行、写函数区 +46 行，仅增量）
- `fetcher/tests/test_db_fb_groups.py`（新增，7 用例）
- `docs/feat_2026-08-09_fb-discovery-group-feed/SPEC.md`（§8.1 一行回填）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md`（本报告）

## 自查发现

- **完整性**：PLAN checkbox 5 项全部落实（建表+索引 / save_fb_posts / upsert_fb_groups / 测试 / spike 回填）；
  边界：空 url 条目跳过不计数（与 save_fb_contacts 空 number 跳过模式一致）。
- **质量**：命名/注释沿用 db.py 既有风格；两函数放 FB 写函数区而非散落。
- **纪律**：未做 brief 之外的事（mark_fb_group_done/failed/reset 属 Step 2.1，未动）；
  未改 db.py 其他区域；未动 PLAN.md checkbox（commit 约束文件清单未含 PLAN.md，勾选留给协调者/后续 Step）。
- **测试**：真实 SQLite 文件 + 真实 INSERT，无 mock；每个测试都先看过 RED。

## 问题或疑虑（concern）

1. db.py 是既有大文件（>1100 行），本次只在指定两处做增量，未重构任务范围外内容——
   后续 Step 若继续在其上加代码，建议考虑按域拆分模块，但非本 Step 职责。
2. `upsert_fb_groups` 的 source 缺省用了 `g.get("source") or "ddg"`（空串也归 ddg），
   与协调者裁定「缺省 'ddg'」一致；若未来需要区分「显式空串」语义需另行约定，目前无此需求（YAGNI 不处理）。

---

## 修复报告（第 1 轮 review 发现，Fix 1）

> 状态：DONE。依据 task-1.1-review.md 三条发现逐条修复，TDD 流程（先 RED 后 GREEN）。

### 修复内容

1. **`fetcher/fetcher/db.py` upsert_fb_groups source 缺省语义收窄**（review 发现 1）：
   `g.get("source") or "ddg"` → `g.get("source") if g.get("source") is not None else "ddg"`。
   现在仅 key 不存在或值为 None 时缺省 'ddg'；显式空字符串 `""` 是合法显式值，原样落库
   （与协调者裁定「缺省」= key 不存在时默认一致）。
2. **`fetcher/tests/test_db_fb_groups.py` 新增 schema 契约固化断言**（review 发现 2）：
   `test_tables_created_and_idempotent` 内补 `PRAGMA table_info('fb_posts')` 断言
   `status` 列 `dflt_value == "'pending'"`——固化 save_fb_posts 依赖的 schema 契约，
   防未来改 DEFAULT 静默破坏。
3. **`fetcher/tests/test_db_fb_groups.py` 补 source 不覆盖断言**（review 发现 3）：
   `test_upsert_groups_dedup_keeps_status_and_name` 补一行
   `assertEqual(rows[0]["source"], "ddg")`——二次 upsert（带 source='fb_post'）后
   该行 source 仍保持首次 'ddg'（INSERT OR IGNORE：已存在行全字段不动）。
4. **新增测试**：`test_upsert_groups_explicit_empty_source_kept`——显式传 `{"source": ""}`
   期望原样落库为 `""`（review 发现 1 的失败测试）。

### TDD 证据

- **RED**（仅改测试后、改代码前）：`cd fetcher && ../platform/server/.venv/bin/python
  -m unittest discover -s tests -p "test_db_fb_groups.py"` → `Ran 8 tests ... FAILED (failures=1)`：
  ```
  FAIL: test_upsert_groups_explicit_empty_source_kept
  AssertionError: 'ddg' != ''
  ```
  正是 review 发现 1 的 bug（空串被吞成 ddg）。发现 2/3 为 schema 契约固化断言，
  首次运行即绿（schema 本已正确），属守护而非修复。
- **GREEN**（改代码后）：同一命令 → `Ran 8 tests in 0.037s OK`。
- **回归**：`-p "test_db_fb*.py"`（test_db_fb.py 10 例 + test_db_fb_groups.py 8 例）
  → `Ran 18 tests in 0.106s OK`，输出干净。

### 改动的文件

- `fetcher/fetcher/db.py`（upsert_fb_groups 内 1 行语义修正 + docstring 措辞对齐，仅增量）
- `fetcher/tests/test_db_fb_groups.py`（+3 断言、+1 新测试用例，共 8 用例）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.1-report.md`（本报告）

### 遗留疑虑

- 显式空串 `source=""` 现在落库为空串；若未来数据面要求空串也归一 'ddg'，需在调用方
  （FbDiscoverTask/FbPostTask）显式不传 key 或传 None，db 层语义已按裁定收窄，不再吞空串。
