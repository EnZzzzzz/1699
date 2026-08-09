# Step 2.2 — crawl_fb_group 队列注册（TDD）

> 这是你的需求唯一来源。PLAN Step 2.2 原文 + SPEC §5.4 精确规格抄录如下。

## PLAN Step 2.2 原文（验收以 checkbox 为准）

- [ ] `_build_registry` 追加 `QueueSpec(queue="crawl_fb_group", site=None,
      task=FbGroupTask(), topup=None, domain_suffix="", requires={"local"})`
- [ ] 测试：注册存在 + 字段断言
- 预估 15min；验收：注册测试全绿 + `--queues crawl_fb_group` 校验通过

## SPEC §5.4 队列注册（精确规格）

```python
specs.append(QueueSpec(
    queue="crawl_fb_group", site=None,
    task=FbGroupTask(),
    topup=None,                      # 货源=平台批次参数（fb_groups pending）
    domain_suffix="",
    requires={"local"},
))
```

## 协调者裁定

1. **插入位置**：`fetcher/fetcher/cli/main.py` 的 `_build_registry` 中，紧随
   discover_fb 队列之后（Step 1.4 已加的块）、`if selected_queues:` 过滤之前。
2. **导入**：延迟导入 FbGroupTask（与 discover_fb 的 FbDiscoverTask 延迟导入一致）。
3. **测试位置**：`fetcher/tests/test_cli_fb.py`，参照 Step 1.4 的
   `test_discover_fb_registered` 写法加 `test_crawl_fb_group_registered`
   （queue/site=None/task 是 FbGroupTask 实例/requires=={"local"}/topup is None/
   domain_suffix==""）。
4. **`--queues crawl_fb_group` 动态校验**：注册测试断言 registry 含该队列即可
   （argparse choices 派生自 _build_registry，与 Step 1.4 同机制）。
5. 不改 selected_queues 过滤 / reset_daemon_state。

## 代码库上下文

- `fetcher/fetcher/cli/main.py`：`_build_registry` 约 222 行起，discover_fb 块在
  约 316-328 行（Step 1.4 加入），紧随其后插入 crawl_fb_group 块。
- `fetcher/tests/test_cli_fb.py`：Step 1.4 已加 `test_discover_fb_registered`
  （63-73 行附近），按同模式加新断言。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
  -s tests -p "test_cli_fb.py"`；回归 `-p "test_fb_*.py"`。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。
2. 测试覆盖：registry 含 crawl_fb_group、字段断言全齐。
3. 输出干净。

## Commit 约束

- 只 `git add`：`fetcher/fetcher/cli/main.py`、`fetcher/tests/test_cli_fb.py`、
  `docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 2.2 ...`。
