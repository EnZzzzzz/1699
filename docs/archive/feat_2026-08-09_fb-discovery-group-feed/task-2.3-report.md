# Step 2.3 报告 — FbPostTask.on_success 群 upsert 补位

> 状态：DONE

## 实现了什么

`fetcher/fetcher/sites/facebook/post_task.py` 的 `FbPostTask.on_success`：在
「save_fb_contacts → mark_fb_post_done」之后、sidecar result_json 设置之前追加：

```python
# 每抓到一帖 = 发现一个群（种子路径②，SPEC §5.5）：INSERT OR IGNORE
# 幂等，不触碰既有群状态机；source 显式传 fb_post（缺省 ddg）
if group_id:
    db.upsert_fb_groups([{
        "url": f"https://www.facebook.com/groups/{group_id}",
        "group_id": group_id,
        "name": item.get("name") or "",
        "source": "fb_post",
    }])
```

- `group_id` 复用 Step 2.1 已提取的共享函数 `group_id_from_url`（post_task.py
  既有导入，**未重复定义正则/函数**）。
- `source="fb_post"` 显式传入（upsert 仅在条目带 source 键时才写 fb_post，
  不传缺省 ddg——协调者裁定 #4）。
- `name` 溯源 `item.get("name") or ""`（协调者裁定 #3）。
- 仅 `group_id` 非空时调用（无 domain/group_id 的 item 零写入）。

未改动：`db.upsert_fb_groups` 本身（Step 1.1 已实现）、群状态机、
fb_posts/fb_contacts 状态流。

## 测了什么（test_fb_post_task.py，+4 个测试，15 → 19）

| 测试 | 断言 |
|---|---|
| `test_on_success_upserts_group_row` | 抓帖后 fb_groups 恰 1 行：url=派生群 URL、group_id、name=payload name、source='fb_post'、status='pending'（落真库真断言） |
| `test_on_success_group_name_defaults_to_empty` | payload 无 name 时 name 缺省空串、source 仍为 fb_post |
| `test_on_success_no_group_id_zero_writes` | item 无 domain/group_id 时 fb_groups 零写入 |
| `test_on_success_repeat_fetch_is_idempotent` | 同群帖二次 on_success：仍 1 行，name/status 不被覆盖（INSERT OR IGNORE 守护） |

既有 on_success 测试（save_fb_contacts 分桶 / mark_fb_post_done / sidecar /
stats）零改动零回归。

## 测试结果

- 验收命令：`cd fetcher && ../platform/server/.venv/bin/python -m unittest
  discover -s tests -p "test_fb_post_task.py"` → **Ran 19 tests, OK**
- 回归：`-p "test_fb_*.py"` → **Ran 60 tests, OK**

## TDD 证据

**RED**（先加前 3 个测试，未实现）：

```
FAIL: test_on_success_upserts_group_row
AssertionError: 0 != 1          # fb_groups 无行（实现前 on_success 不写群）

ERROR: test_on_success_group_name_defaults_to_empty
TypeError: 'NoneType' object is not subscriptable   # 同上，无行可取

Ran 18 tests — FAILED (failures=1, errors=1)
```

符合预期：实现缺失时群表必然为空，两个群行断言失败；`zero_writes` 测试在
实现前即通过（无写入自然零行，作为守护）。

**GREEN**（最小实现后）：

```
Ran 19 tests in 0.086s
OK
```

**补充说明**：第 4 个幂等测试（`test_on_success_repeat_fetch_is_idempotent`）
在 GREEN 后追加——它守护的是已实现行为（INSERT OR IGNORE + url UNIQUE），
本身无独立 RED 阶段；前 3 个 brief 要求的测试均有真实 RED。

## 改动的文件

- `fetcher/fetcher/sites/facebook/post_task.py`（on_success 追加 7 行 upsert 块）
- `fetcher/tests/test_fb_post_task.py`（+4 测试，全部走真库断言）

## 自查

- **完整性**：SPEC §5.5 逐条落实（调用位置、group_id 非空条件、name 缺省、
  source='fb_post'、幂等不碰状态机）；边界（无 group_id 零写入、name 缺省、
  重复抓帖幂等）均有测试。
- **质量**：命名/注释对齐既有 on_success 模式；upsert 块紧邻
  mark_fb_post_done，与 sidecar 段由注释分隔，职责清晰。
- **纪律**：YAGNI——只加了 brief 要求的一处调用与测试，未重构任何既有代码；
  未触碰 upsert_fb_groups 实现（Step 1.1 产物）。
- **测试**：真实行为（临时 ShopDB 真库断言，全 mock 原子无网络）；既有
  on_success 测试零回归；测试输出与基线一致（prepare 的 print 为既有行为）。

## 疑虑

- 无阻塞性疑虑。唯一说明：第 4 个幂等测试为 GREEN 后追加的守护测试
  （见上），非严格 TDD 顺序，但覆盖的是 brief 明示的「INSERT OR IGNORE 幂等」
  语义，且无实现时同样会失败（与 upsert 行为绑定）。
