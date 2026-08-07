# Step 3.1 修复报告 — summary 透传 db_path

> commit: `5fc0dbd` — fix(identity-p2): summary 透传 db_path（临时库运行不再触碰生产库）
> 分支: `feat/fetcher-identity-p2`
> 基线: 38296b5 (303 passed) → 5fc0dbd (309 passed)

## 问题

冒烟发现：`Task.summary()` 内部 `ShopDB()` 不带 db 路径 → 默认打开生产库 `.cache/1688.db`。P2 `_migrate` 追加 cookies 前缀迁移后，临时库运行收尾时会对生产库产生写副作用。

## 改动清单（12 文件）

### ① 协议层

| 文件 | 改前 | 改后 |
|------|------|------|
| `fetcher/fetcher/control/task.py` | `def summary(self, all_stats: dict) -> str:` | `def summary(self, all_stats: dict, db_path=None) -> str:` |
| `fetcher/fetcher/control/engine.py` | `self.task.summary(self.state['stats'])` | `self.task.summary(self.state['stats'], self.config.resolved_db_path())` |

### ② 8 处站点实现

| 文件 | 签名变更 | ShopDB 调用变更 |
|------|----------|----------------|
| `sites/alibaba1688/contact.py` | `+ db_path=None` | `ShopDB()` → `ShopDB(db_path)` |
| `sites/alibaba1688/shop.py` | `+ db_path=None` | `ShopDB()` → `ShopDB(db_path)` |
| `sites/alibaba1688/company.py` | `+ db_path=None` | `ShopDB()` → `ShopDB(db_path)` |
| `sites/madeinchina/contact.py` | `+ db_path=None` | `ShopDB()` → `ShopDB(db_path)` |
| `sites/madeinchina/shop.py` | `+ db_path=None` | `ShopDB()` → `ShopDB(db_path)` |
| `sites/yiwugo/contact.py` | `+ db_path=None` | 无（本就不调 ShopDB） |
| `sites/yiwugo/search.py` | `+ db_path=None` | 无（本就不调 ShopDB） |
| `sites/taobao/search.py` | `+ db_path=None` | 无（本就不调 ShopDB） |

### ③ 测试（新增 + 修改）

| 文件 | 变更 |
|------|------|
| `tests/test_summary_db_path.py` | **新文件**：5 个测试，覆盖 5 处有 ShopDB 调用的站点 |
| `tests/test_engine.py` | FakeTask.summary 签名适配 + 原有测试传入 db_path + 新增 `test_summary_receives_db_path_from_config` |

## TDD 证据

### RED（5 条全失败）

```
$ cd fetcher && python -m pytest tests/test_summary_db_path.py -q
FFFFF
TypeError: CompanyTask.summary() takes 2 positional arguments but 3 were given
TypeError: ContactTask.summary() takes 2 positional arguments but 3 were given
TypeError: ShopTask.summary() takes 2 positional arguments but 3 were given
TypeError: MadeInChinaContactTask.summary() takes 2 positional arguments but 3 were given
TypeError: MadeInChinaShopTask.summary() takes 2 positional arguments but 3 were given
5 failed in 0.05s
```

每个失败都是 `takes 2 positional arguments but 3 were given` — 证明当前 summary 不接受 db_path。

### GREEN（5 条全通过）

```
$ cd fetcher && python -m pytest tests/test_summary_db_path.py -x -q
.....
5 passed in 0.04s
```

每一条都 assert fake ShopDB 收到的 path 等于传入的 db_path，证明 summary 已将 db_path 透传给 ShopDB 而非默认开生产库。

### 全量回归

```
$ cd fetcher && python -m pytest tests -x -q
309 passed, 2 subtests passed in 13.91s
```

基线 303 → 309（+6 新测试），零回归。

## grep 自查

```
$ grep -rn "ShopDB()" fetcher/fetcher/sites/ fetcher/fetcher/control/ --include="*.py"
(no output)
```

sites/ 与 control/ 下已无裸 `ShopDB()` 残留。`db.py` 内的 2 处（docstring 示例 + `__main__`）属模块自身文档/CLI，非本步范围。

## 改动文件统计

```
fetcher/fetcher/control/engine.py            |   2 +-
fetcher/fetcher/control/task.py              |   8 +-
fetcher/fetcher/sites/alibaba1688/company.py |   4 +-
fetcher/fetcher/sites/alibaba1688/contact.py |   4 +-
fetcher/fetcher/sites/alibaba1688/shop.py    |   4 +-
fetcher/fetcher/sites/madeinchina/contact.py |   4 +-
fetcher/fetcher/sites/madeinchina/shop.py    |   4 +-
fetcher/fetcher/sites/taobao/search.py       |   2 +-
fetcher/fetcher/sites/yiwugo/contact.py      |   2 +-
fetcher/fetcher/sites/yiwugo/search.py       |   2 +-
fetcher/tests/test_engine.py                 |  19 +++-
fetcher/tests/test_summary_db_path.py        | 129 ++++++++++++++++++++
12 files changed, 165 insertions(+), 19 deletions(-)
```
