# Task 5.2 Report — crawl_1688_shop/company 入注册表 + feeder 冒烟 + 旧 CLI 等价确认

> 分支：`feat/multiqueue-p3` | 日期：2026-08-08 | 状态：DONE

## 实现摘要

在 `_build_registry()` 新增 2 条 feeder 队列（crawl_1688_shop / crawl_1688_company，topup=None），注册表从 3 条扩展至 5 条全部就位。feeder 队列不参与 in_progress reset（已有逻辑通过 topup=None 跳过，无需改动）。

## 改动文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/cli/main.py` | `_build_registry()` 追加 crawl_1688_shop + crawl_1688_company（topup=None, domain_suffix="", requires={"channel","browser"}） |
| `fetcher/tests/test_cli.py` | 新增 3 测试 + 扩展 1 测试（见下） |

## 测试列表（新增 3 条，基线 509→512）

| 测试 | 方法 | 覆盖项 |
|---|---|---|
| 注册表 5 条队列 | `test_daemon_queues_dynamic_from_registry`（扩展） | 断言 len=5，含 crawl_1688_shop/company |
| feeder topup=None | `test_feeder_queues_topup_is_none`（新增） | topup=None, domain_suffix="", requires correct |
| task 类型正确 | `test_registry_task_types_correct`（新增） | Alibaba1688ShopTask / Alibaba1688CompanyTask |
| reset 跳过 feeder 回归 | `test_reset_skips_feeder_full_registry`（新增） | 5 队列 registry → reset 只重置 contact domain_suffix，feeder 跳过 |

## TDD 证据

- **RED**（7e8c9a9 前）：3 测试失败——registry len=3≠5、feeder count=0≠2、KeyError 'crawl_1688_shop'
- **GREEN**（实施后）：全量 512 passed, 2 subtests passed

## 冒烟取证

- 冒烟 A（daemon 1688 shop）：discover 播种→首页类目提取→2082 category items + 50 shops 落库 ✅
- 冒烟 B（CLI 1688 shop）：prepare→discover 播种→work_items 认领（3 claimed） ✅（滑块墙为环境噪声）
- 取证文档：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step5.2/analysis.md`

## 自查发现

1. `reset_daemon_state` 的 `topup is not None` 检查已有，feeder 队列自动跳过，无需额外改动
2. `--queues` choices 动态从 registry 派生，新增队列自动出现在 help 中
3. `policies` 装配逻辑：1688 三个队列共享一个 Policy（按 site 去重），已有逻辑无需改动
4. company 的 `company:` 前缀隔离在 test_1688_feeder.py 已有覆盖，本次仅加 registry 层类型断言
5. 全量测试 512 passed（0 regression）
