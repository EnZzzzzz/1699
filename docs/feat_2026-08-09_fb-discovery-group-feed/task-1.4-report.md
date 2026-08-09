# Step 1.4 报告 — discover_fb 队列注册（TDD）

## 实现了什么

`fetcher/fetcher/cli/main.py` 的 `_build_registry`（约 wa_check 条件守卫块之后、
`if selected_queues:` 过滤之前）追加 discover_fb QueueSpec：

```python
# discover_fb（FB discovery：本地队列，无 site、无浏览器，LocalLoop 消费；
# 货源=平台批次参数直接入 work_items，无自喂 → topup=None）
from fetcher.sites.facebook.discover_task import FbDiscoverTask  # 延迟导入
specs.append(QueueSpec(
    queue="discover_fb",
    site=None,
    task=FbDiscoverTask(),
    topup=None,
    domain_suffix="",
    requires={"local"},
))
```

- 与 wa_check 并列的第二个 local 队列（`requires={"local"}`，LocalLoop 消费）；
- `site=None`（非站点队列，不占浏览器席位、不进 policies/browser_specs）；
- `topup=None`（货源=平台批次参数直接入 work_items，无自喂）；
- 延迟导入对齐协调者裁定（参考 wa_check 直接实例化方式，不改顶部 import）。

## 测了什么（`fetcher/tests/test_cli_fb.py`，新增 1 个测试，共 5 个）

- `test_discover_fb_registered`：registry 含 `discover_fb`，断言
  `queue=="discover_fb"`、`site is None`、`domain_suffix==""`、
  `requires=={"local"}`、`task` 是 `FbDiscoverTask` 实例、`topup is None`。
  参照既有 `test_crawl_fb_post_registered` 的字段断言模式（spec.queue/site/task
  类型/requires/topup/domain_suffix）。
- 既有 `test_queues_choices_accept_fb` 已覆盖「registry 即 argparse choices 派生
  来源」的动态校验模式——discover_fb 入 registry 后 `--queues discover_fb` 自然
  通过（协调者裁定 4：沿用既有覆盖即可）。

## TDD 证据

**RED**（实现前，测试先写）：
```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
AssertionError: 'discover_fb' not found in {'crawl_1688_contact': QueueSpec(...), ...}
----------------------------------------------------------------------
Ran 5 tests in 0.028s
FAILED (failures=1)
```
失败原因符合预期：discover_fb 尚未注册进 `_build_registry`（功能缺失，不是断言
笔误——registry 里 7 条既有队列全在，只缺新队列）。

**GREEN**（最小实现后）：
```
$ ../platform/server/.venv/bin/python -m unittest discover -s tests -p "test_cli_fb.py"
Ran 5 tests in 0.037s
OK
```

**验收动态校验**（`--queues discover_fb`）：
```
$ python -c "from fetcher.cli.main import _build_registry; print([s.queue for s in _build_registry(['discover_fb'])])"
['discover_fb']
$ python -m fetcher daemon --queues discover_fb --help   # argparse 接受（choices 动态派生）
```

**回归**：
- `-p "test_fb_*.py"`：Ran 42 tests, OK
- 全量 `-p ""`：Ran 721 tests, OK（27.5s，输出干净无 error/warning）

## 改动的文件

- `fetcher/fetcher/cli/main.py`（`_build_registry` 追加 discover_fb QueueSpec）
- `fetcher/tests/test_cli_fb.py`（新增 `test_discover_fb_registered` + docstring/import）
- `docs/feat_2026-08-09_fb-discovery-group-feed/task-1.4-report.md`（本报告）

## 自查发现

- **完整性**：brief 两项 checkbox 全部落实（注册存在+字段断言、`--queues discover_fb`
  动态校验）；插入位置/导入方式/测试位置对齐协调者裁定 1-4。
- **质量**：写法对齐 wa_check（直接实例化 local 队列）与 crawl_fb_post（注释标注
  队列语义）；`topup=None` 语义与 crawl_mic_shop 等 feeder 队列一致。
- **纪律**：未改 `if selected_queues:` 过滤、`reset_daemon_state`（discover_fb
  topup=None 且 domain_suffix=""，天然不参与 in_progress 重置）等范围外代码；
  测试仅加 1 个断言方法（不重复既有 choices 派生测试）。
- **疑虑**：无。`reset_daemon_state` 对 discover_fb 无影响（topup=None 跳过），
  Step 1.5 冒烟时 daemon 启动重置日志的 domain_suffix 列表会多一个空串后缀，
  与 crawl_fb_post/wa_check 行为一致，属既有格式。
