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

---

## Fix Round 1（reviewer 发现 I1/I2/M1）

> commit: `<TBD>` | 日期: 2026-08-08 | 状态: DONE

### I1 — company 队列未冒烟 → 已补

补 crawl_1688_company daemon 短冒烟（`--db /tmp/smoke_p3_52c.db --workers 1 --limit 4 -n 1`），
取证结果：
- discover 播种 ✅ → 2080 pending category items，全部 keyword 为 `"company:..."` 前缀
- 1 discover done + 1 category failed（company:女装, 滑块墙）+ 1 category claimed（company:男装）
- make_task("company") → Alibaba1688CompanyTask 实例化正常、注册表装配无故障
- 运行时 company: 前缀证据：sqlite3 查询 pending payload_json 全部以 `"keyword": "company:..."` 开头
- 滑块墙为环境噪声；未被遮挡的结构路径（播种→认领→payload 前缀→进度写入）全部走通

Trade-off：Step 5.1 的 test_1688_feeder.py 已通过 mock 完整覆盖 prefix 隔离，
本次补齐无 mock 运行时证据。

### I2 — DB 取证缺原始 SQL 命令/输出 → 已补

对全部 3 次冒烟（A/B/C），把实际执行的 sqlite3 命令与原文输出贴入 analysis.md，
含 work_items 分组计数、category_progress 行、shops 样本、payload_json 前缀检查。

### M1 — test_feeder_queues_topup_is_none 范围不全 → 已修复

feeder_names 集合加入 `"crawl_mic_shop"`，断言从 len=2 → len=3，覆盖全部 3 条 feeder。

### 改动文件（Fix Round 1）

| 文件 | 改动 |
|---|---|
| `fetcher/tests/test_cli.py` | test_feeder_queues_topup_is_none: feeder_names 加 crawl_mic_shop, len=2→3 |
| `smoke-step5.2/analysis.md` | 补 I2 原始 SQL+输出；补冒烟 C（company）完整节 |
| `smoke-step5.2/company-run.log` | company 冒烟原始输出 |
| `task-5.2-report.md` | 本次 Fix Round 1 追加 |

### 测试

全量 512 passed, 2 subtests passed（0 regression）。
