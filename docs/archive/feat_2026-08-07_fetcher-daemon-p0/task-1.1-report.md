# Step 1.1 report — 确认 item 访问契约（SPEC §4 假设 1、2）

> 执行日期：2026-08-07。范围：只读代码 + 回填 SPEC.md §4 表格假设 1、2 两行，未改任何 fetcher 代码。

## 1. item 全部访问点清单（ContactTask 及其间接消费方）

`ContactTask`（`fetcher/fetcher/sites/alibaba1688/contact.py`）对 item（shops 表一行，`sqlite3.Row`，见 `db.py:188` row_factory）的全部访问点——**全部为 `item["key"]` 键访问，零属性访问**：

| file:line | 所在方法 | 访问形式 | 键名 |
|---|---|---|---|
| contact.py:163 | `label` | `item["name"] or item["domain"]` | `name`、`domain` |
| contact.py:168 | `cold_start` | `item is None`（空值判断，非键访问） | — |
| contact.py:171 | `cold_start` | `item['domain']` | `domain` |
| contact.py:180 | `fetch` | `item["domain"]` | `domain` |
| contact.py:182 | `fetch` | `item["url"] or f"https://{domain}/"` | `url` |
| contact.py:227 | `on_success` | `item["domain"]`（save_contact） | `domain` |
| contact.py:230 | `on_success` | `item["domain"]`（mark_shop_no_contact） | `domain` |
| contact.py:245 | `on_giveup` | `item["domain"]`（mark_shop_failed） | `domain` |
| contact.py:252 | `on_abort` | `item['domain']` | `domain` |

不访问 item 的方法（逐一确认）：

- `validate`（209-219）：只读 `result.data`，不碰 item。
- `giveup_cost`（255-257）：常量返回 1。
- `after_item`：ContactTask 未覆盖，基类 `control/task.py:113` 默认为空实现。
- `prepare`/`summary`/`compose`/`make_stats`/`rest_counter`/`empty_message`：签名不含 item。
- 辅助函数 `parse_contact_text`（49-82）：只处理页面文本，与 item 无关。
- `on_success` 235-238 行的 `info[...]` 是 `result.data` 的拷贝，不是 item。

item 离开 ContactTask 后的间接消费方（CrawlLoop 透传链）：

| file:line | 访问形式 | 说明 |
|---|---|---|
| control/loop.py:154 | `self.ctx.state["item"] = item` | 只存不读键，类型无关 |
| atoms/browser_ops.py:103-106 | `ctx.state.get("item")` → `ctx.site.cold_start(page, item, ...)` | 透传给站点插件 |
| sites/alibaba1688/__init__.py:73-74 | `item["domain"] if isinstance(item, dict) else getattr(item, "domain", None)` | **已显式兼容 dict**；注：sqlite Row 无属性访问，现行为走 getattr 分支得 None 退回站点首页，dict 反而能命中 domain 分支（差异方向对 daemon 有利，且该原子失败不阻断） |

**键集合结论：{`domain`, `name`, `url`}**。`domain` 为必需键；`name`/`url` 允许 falsy（两处均带 `or` 兜底），但键必须存在——dict 缺键会 `KeyError`，而 sqlite Row 缺列在 `item["name"]` 处同样抛错，语义一致。

## 2. isinstance 特判 grep 结果

命令：

```
grep -rn -E 'isinstance|type\(.*\)\s*(is|==)|__class__' fetcher/fetcher/
```

命中 13 处，**无一处针对 Task 具体类型**。逐条分类：

- `strategy/policy.py:125` — 判 `Scenario` 枚举 key
- `atoms/facebook_group.py:186`、`net/proxy/qingguo.py:140`、`yiwugo/features.py:183` 等 — 判 `dict`/`list` 数据形态
- `net/browser.py:333` — 判 `Channel`
- `sites/alibaba1688/__init__.py:73`、`sites/madeinchina/__init__.py:84` — 判 `dict`（即上述 item 兼容分支，反而是对 dict payload 友好的证据）
- `sites/__init__.py:27` — 判 `str`

重点文件逐一确认：

- `control/engine.py`：全文无 isinstance；task 仅经 `self.task.compose`（172）、`self.task.summary`（214）调用，构造器 36-41 行 task 经参数传入、53 行 `loop_factory or CrawlLoop`。
- `control/loop.py`：无 isinstance；task 仅经协议方法调用（`make_stats`/`cold_start_before_acquire`/`acquire_item`/`label`/`fetch`/`validate`/`on_success`/`on_abort`/`on_giveup`/`giveup_cost`/`after_item`/`rest_counter`/`batch_unit`/`unit`/`ip_request_budget`/`empty_message`）。
- `control/task.py`：协议基类，无类型判断。
- `cli/main.py`：`task = site.make_task(args.task)`（166 行）→ `task.prepare(cfg)`（167）→ `Engine(cfg, task, ...)`（179），无类型分支。

补充：`Engine` 文档注释明确「Task 对象跨 worker 共享」——DaemonTaskProxy 内的条件变量等共享状态需注意线程安全（Step 2.1 实现时注意，不影响本假设结论）。

## 3. SPEC 回填结论

- **假设 1 → 成立：dict 可直接替代** sqlite Row，无需 `SimpleNamespace`/dict 子类等适配。约束：payload 必须含 `domain`/`name`/`url` 三键（与 SPEC §3.2 DDL 注释的 `{"domain","name","url"}` 一致，无需变更）。
- **假设 2 → 成立：无特判**。Engine/CrawlLoop/CLI 对 task 全程鸭子类型，只走 Task 协议方法；`DaemonTaskProxy` 实现协议即可经 `Engine(cfg, task=proxy, ..., loop_factory=...)` 注入。

SPEC.md §4 表格两行已更新：「依据」列由「推断」改为「已读码验证（附 file:line）」，「验证方式」列写入上述明确结论。

## 4. 改动与提交

- 改动文件（仅 1 个）：`docs/feat_2026-08-07_fetcher-daemon-p0/SPEC.md`（§4 表格假设 1、2 两行）
- 本 report：`docs/feat_2026-08-07_fetcher-daemon-p0/task-1.1-report.md`
- commit：见下方最终汇报（`docs(daemon-p0): ...`）
- 未改任何 fetcher 代码；本 Step 无代码改动，未跑测试套件（按 brief 要求）。
