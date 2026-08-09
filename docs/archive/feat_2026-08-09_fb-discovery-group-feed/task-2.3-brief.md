# Step 2.3 — FbPostTask.on_success 群 upsert 补位（TDD）

> 这是你的需求唯一来源。PLAN Step 2.3 原文 + SPEC §5.5 精确规格抄录如下。

## PLAN Step 2.3 原文（验收以 checkbox 为准）

- [ ] `fetcher/fetcher/sites/facebook/post_task.py on_success` 追加：group_id 非空时
      `db.upsert_fb_groups([{"url": 派生群URL, "group_id", "name": item.get("name")}])`
      （SPEC §5.5）
- [ ] 测试（扩展 test_fb_post_task.py）：抓帖后 fb_groups 出现该群（pending、name
      溯源）；无 group_id 时零写入；既有 on_success 测试零回归
- 预估 20min；验收：新断言全绿 + 既有 test_fb_post_task.py 全绿

## SPEC §5.5 FbPostTask.on_success 改动（**唯一既有 Task 改动点，幂等**）

在现有「save_fb_contacts + mark_fb_post_done」之后追加：

```python
if group_id:
    db.upsert_fb_groups([{"url": f"https://www.facebook.com/groups/{group_id}",
                          "group_id": group_id, "name": item.get("name") or ""}])
```

语义：**每抓到一帖 = 发现一个群**（种子路径②）；INSERT OR IGNORE 幂等、不触碰
既有群状态机（只写 pending 新行），对既有 fb_posts/fb_contacts 状态流零影响。

## 协调者裁定（覆盖 SPEC 未定细节）

1. **group_id 来源**：post_task.py 的 on_success 已有 `group_id = _group_id_from_url(
   item.get("domain") or "")`——注意 Step 2.1 修复后该函数已提取到共享位置
   `fetcher/fetcher/sites/facebook/urls.py`（公共名 `group_id_from_url`），post_task.py
   现在从那里导入。**本 Step 不要重复定义，直接用既有导入的 group_id_from_url。**
2. **upsert 调用位置**：在「save_fb_contacts + mark_fb_post_done」之后、sidecar
   result_json 设置之前（与 SPEC §5.5 语义一致）。group_id 非空才调用。
3. **name 溯源**：`item.get("name") or ""`（item payload 的 name 来自平台
   enqueue_fb_post_batch 的 payload {"url","domain","name"}）。
4. **source 键**：Step 1.1 裁定的 upsert_fb_groups 条目可选 `"source"` 键——本 Step
   显式传 `"source": "fb_post"`（群由帖派生，SPEC §4.1 source ∈ {ddg, fb_post}）。
   注意：仅当条目 source 键存在时 upsert 才写 fb_post；不传则缺省 ddg。所以**必须
   显式传 source="fb_post"**。
5. **幂等/状态机**：INSERT OR IGNORE 已存在行不动 status（保持采集进度）；对既有
   fb_posts/fb_contacts 状态流零影响（回归由既有 on_success 测试守护）。
6. **测试**：扩展 test_fb_post_task.py——
   - 抓帖 on_success 后 fb_groups 出现该群行（url=派生群 URL、group_id、name=payload
     name、status=pending、source='fb_post'）；
   - item 无 domain/group_id 时 upsert 零写入（fb_groups 无新行）；
   - 既有 on_success 测试零回归（save_fb_contacts/mark_fb_post_done/sidecar 断言不动）。

## 代码库上下文

- `fetcher/fetcher/sites/facebook/post_task.py`：on_success 在约 135-163 行（save_fb_contacts
  → mark_fb_post_done → sidecar → stats）。group_id 已由 `group_id_from_url`（从
  urls.py 导入）解析。
- `fetcher/fetcher/sites/facebook/urls.py`：Step 2.1 新建的共享函数（group_id_from_url）。
- `fetcher/tests/test_fb_post_task.py`：既有 on_success 测试（mock FetchFbPost 原子 +
  临时 ShopDB）。参照其构造方式加新断言。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
  -s tests -p "test_fb_post_task.py"`；回归 `-p "test_fb_*.py"`。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。
2. 测试覆盖（brief 已列）：抓帖后 fb_groups 出现群行（字段断言全）+ 无 group_id
   零写入 + 既有零回归。
3. 输出干净。

## Commit 约束

- 只 `git add`：`fetcher/fetcher/sites/facebook/post_task.py`、
  `fetcher/tests/test_fb_post_task.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 2.3 ...`。
