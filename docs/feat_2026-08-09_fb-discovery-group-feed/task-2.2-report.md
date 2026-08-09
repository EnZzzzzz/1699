# Step 2.2 报告 — crawl_fb_group 队列注册（TDD）

## 实现了什么

按 SPEC §5.4 / PLAN Step 2.2 精确规格，在 `fetcher/fetcher/cli/main.py` 的
`_build_registry` 中、紧随 discover_fb 块之后（`if selected_queues:` 过滤之前）追加：

```python
# crawl_fb_group（FB 群全量采集：本地队列，无 site、无浏览器，
# LocalLoop 消费；货源=平台批次参数（fb_groups pending）直接入
# work_items，无自喂 → topup=None）
from fetcher.sites.facebook.group_task import FbGroupTask  # 延迟导入
specs.append(QueueSpec(
    queue="crawl_fb_group",
    site=None,
    task=FbGroupTask(),
    topup=None,
    domain_suffix="",
    requires={"local"},
))
```

与协调者裁定逐条对齐：
1. 插入位置：discover_fb 块之后、`if selected_queues:` 之前 ✓
2. 延迟导入 FbGroupTask（与 discover_fb 的 FbDiscoverTask 延迟导入一致）✓
3. 测试位置 `fetcher/tests/test_cli_fb.py`，仿 `test_discover_fb_registered` 写法 ✓
4. `--queues crawl_fb_group` 动态校验：argparse choices 派生自 `_build_registry`
   （与 Step 1.4 同机制）✓
5. 未改 `if selected_queues:` 过滤、`reset_daemon_state` ✓

## 测了什么

`fetcher/tests/test_cli_fb.py` 新增 `test_crawl_fb_group_registered`，断言全齐：

- registry 含 `crawl_fb_group`
- `spec.queue == "crawl_fb_group"`
- `spec.site is None`
- `spec.domain_suffix == ""`
- `spec.requires == {"local"}`
- `spec.task` 是 `FbGroupTask` 实例
- `spec.topup is None`

## 测试结果

- 单文件：`python -m unittest discover -s tests -p "test_cli_fb.py"` → `Ran 6 tests OK`
- 回归：`-p "test_fb_*.py"` → `Ran 56 tests OK`
- 动态校验：`python -m fetcher daemon --queues crawl_fb_group --help` → argparse
  接受（exit 0）；`--queues bogus_q` 报错列出的可选队列含 `crawl_fb_group`。

## TDD 证据

### RED

先只加测试、不加实现，运行：

```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
F.....
FAIL: test_crawl_fb_group_registered ...
AssertionError: 'crawl_fb_group' not found in {'crawl_1688_contact': ..., 'discover_fb': ...}
Ran 6 tests in 0.035s
FAILED (failures=1)
```

失败输出正是预期：`crawl_fb_group` 不在 registry 里（可选队列列表里也没有它）。
符合预期——队列尚未注册，测试先行暴露缺口。

### GREEN

加最小实现（main.py 追加一个 QueueSpec 块）后：

```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
Ran 6 tests in 0.036s
OK
```

输出干净（daemon 启动日志行 `[0] ... [1] ...` 是既有 reset 测试的正常 stdout，
非失败信息）。

## 改动的文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/cli/main.py` | `_build_registry` 追加 crawl_fb_group QueueSpec（含延迟导入） |
| `fetcher/tests/test_cli_fb.py` | 新增 `test_crawl_fb_group_registered` + 顶部导入 FbGroupTask |
| `docs/feat_2026-08-09_fb-discovery-group-feed/task-2.2-report.md` | 本报告 |

## 自查

- **完整性**：brief 两项 checkbox 全落实（注册存在+字段断言、`--queues crawl_fb_group`
  校验通过）。
- **质量**：QueueSpec 字段与既有 discover_fb 块逐字段对齐（site=None/topup=None/
  domain_suffix=""/requires={"local"}），注释风格一致（中文、说明货源与消费者）。
- **纪律**：YAGNI——只加注册与测试，未触碰 selected_queues 过滤、reset_daemon_state、
  消费者装配等无关代码。
- **测试**：真实断言（registry 内容 + 全部 6 个字段），TDD 先红后绿，输出干净。
- 疑虑：无。daemon 实跑未做冒烟（本 Step 只注册，消费逻辑在 Step 2.1 已实现
  并有独立测试；冒烟属于 Phase 末 Step 的范畴，不在本 Step 验收内）。
