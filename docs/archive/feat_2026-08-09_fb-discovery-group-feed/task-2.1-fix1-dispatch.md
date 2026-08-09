你正在修复 Step 2.1 的 review 发现（第 1 轮修复）。

## 任务描述

先读你的任务 brief：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-brief.md`（需求唯一来源）
再读 implementer 的完整 report：`/Volumes/DataDrive/proj/public/1699/docs/feat_2026-08-09_fb-discovery-group-feed/task-2.1-report.md`

## Review 发现（逐条修复）

1. **`_group_id_from_url` 与 `post_task.py` 逐字重复**（group_task.py:27-31 vs post_task.py:25-29）：
   两个文件各自定义完全相同的 4 行函数与正则，未来改正则需同步两处。**提取共享**：
   把 `_GROUP_RE` 正则与 `_group_id_from_url` 移到共享位置（建议 `fetcher/fetcher/sites/
   facebook/__init__.py` 或新建 `fetcher/fetcher/sites/facebook/urls.py`——选一个
   职责清晰且不引循环依赖的位置），group_task.py 与 post_task.py 都从共享位置导入。
   post_task.py 的改动保持行为不变（既有测试必须零回归）。注意：Step 2.3 也会改
   post_task.py，共享函数现在提取好，后续直接复用。
2. **on_success stats 分支依赖 `data["phones"]` 顶级聚合，与逐帖落号使用
   `post["phones"]` 口径不一致**（group_task.py:127 vs 122-125）：改用逐帖口径——
   stats 的 ok/empty 判定基于逐帖 `post["phones"]` 是否非空（任一帖有号码 → ok），
   不依赖原子顶级聚合字段，消除对原子输出结构的隐含依赖。

## 你的工作

1. 按 TDD：发现 2 是行为变更，先写失败测试（构造原子返回 posts 但顶级 phones 缺失/
   不一致的场景，断言 stats 按逐帖口径判定）→ 改代码 → 转绿。发现 1 是重构（行为
   不变），先有共享函数提取后的测试仍绿即可（既有 test_fb_group_task.py +
   test_fb_post_task.py 是守护）。
2. 重跑覆盖改动代码的测试 + 回归：`cd fetcher && ../platform/server/.venv/bin/python
   -m unittest discover -s tests -p "test_fb_group_task.py"`、
   `-p "test_fb_post_task.py"`、`-p "test_fb_*.py"`。
3. **把修复报告追加**到 report 文件末尾（改了什么、覆盖测试、命令、输出）。
4. commit 修复（只 add 你的文件：group_task.py、post_task.py、共享位置文件、
   test_fb_group_task.py、test_fb_post_task.py（若改动）、docs/ 下本 Step 文件；
   **严禁 git add -A**）。
5. 短契约回复（状态 / commit / 测试总结 / 疑虑 / report 路径）。

工作目录：/Volumes/DataDrive/proj/public/1699。TDD skill 已加载。
