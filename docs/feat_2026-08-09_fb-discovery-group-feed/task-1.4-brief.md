# Step 1.4 — discover_fb 队列注册（TDD）

> 这是你的需求唯一来源。PLAN Step 1.4 原文 + SPEC §5.4 精确规格抄录如下。

## PLAN Step 1.4 原文（验收以 checkbox 为准）

- [ ] `fetcher/fetcher/cli/main.py _build_registry` 追加
      `QueueSpec(queue="discover_fb", site=None, task=FbDiscoverTask(), topup=None,
      domain_suffix="", requires={"local"})`
- [ ] 测试（并入 test_fb_discover_task.py 或 test_cli_fb.py）：注册存在 + 字段
      断言（site=None、requires={"local"}、topup=None）
- 预估 20min；验收：注册测试全绿 + `--queues discover_fb` 动态校验通过

## SPEC §5.4 队列注册（精确规格）

```python
specs.append(QueueSpec(
    queue="discover_fb", site=None,
    task=FbDiscoverTask(),
    topup=None,                      # 货源=平台批次参数，无自喂
    domain_suffix="",
    requires={"local"},
))
```

## 协调者裁定

1. **插入位置**：`fetcher/fetcher/cli/main.py` 的 `_build_registry` 中，wa_check 条件
   守卫块之后、`if selected_queues:` 过滤之前（与 crawl_fb_post 等既有队列并列；
   参照现有 crawl_fb_post QueueSpec 的写法）。
2. **导入**：main.py 顶部或函数内延迟导入 FbDiscoverTask（延迟导入对齐 crawl_fb_post
   的 site_fb.make_task 模式——但 FbDiscoverTask 是直接实例化，参考 wa_check 的
   `from fetcher.wa_task import WaCheckTask` 延迟导入方式）。
3. **测试位置**：并入 `fetcher/tests/test_cli_fb.py`（既有文件，含 crawl_fb_post 注册
   测试模式）或新建断言。参照 test_cli_fb.py 既有注册测试的写法——先读它，按它的
   模式加 discover_fb 注册断言（spec.queue/site/task 类型/requires/topup/domain_suffix）。
4. **`--queues discover_fb` 动态校验**：daemon argparse 的 choices 来自
   `_build_registry()` 的 queue 列表——新增队列后 `python -m fetcher daemon
   --queues discover_fb --help` 或注册测试断言 registry 含该队列即可（若既有测试
   已覆盖 choices 派生，沿用）。

## 代码库上下文

- `fetcher/fetcher/cli/main.py`：`_build_registry(selected_queues)` 函数（约 222 行起），
  wa_check 块在约 294-303 行，`if selected_queues:` 过滤在约 307 行。QueueSpec 从
  `fetcher.control.queue_router` 导入。
- `fetcher/tests/test_cli_fb.py`：既有 crawl_fb_post 注册测试，读它按同模式加断言。
- 测试运行：`cd fetcher && ../platform/server/.venv/bin/python -m unittest discover
  -s tests -p "test_cli_fb.py"`；回归 `-p "test_fb_*.py"`。

## TDD 纪律

1. 先失败测试 → RED → 最小实现 → GREEN。
2. 测试覆盖：registry 含 discover_fb、字段断言（queue/site=None/task 是
   FbDiscoverTask 实例/requires=={"local"}/topup is None/domain_suffix==""）。
3. 输出干净。

## Commit 约束

- 只 `git add`：`fetcher/fetcher/cli/main.py`、`fetcher/tests/test_cli_fb.py`（或新
  测试文件）、`docs/feat_2026-08-09_fb-discovery-group-feed/` 下本 Step 的 brief/report。
- **严禁** `git add -A` / `git add .` / `git commit -am`。
- commit message 风格：`feat(fb): Step 1.4 ...`。
