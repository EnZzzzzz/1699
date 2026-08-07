# Step 3.1 修复 brief — summary 尊重 --db（Task.summary 透传 db_path）

> 来源：Step 3.1 冒烟发现（生产库被意外迁移的根因）。本文本是你的需求唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699

## 背景与问题

冒烟（`daemon --db /tmp/xxx.db`）结束时，`Task.summary()`（各站点实现的 exit 汇总打印）内部 `ShopDB()` **不带 db 路径 → 默认打开生产库** `.cache/1688.db`。P2 的 `_migrate` 追加了 cookies 前缀迁移后，该既有路径在任意临时库运行收尾时会对生产库产生写副作用（本次冒烟已实际触发生产库 18095 行 Cookie 迁移）。修复目标：**summary 尊重传入的 db 路径，临时库运行不再触碰生产库**。

## 内容

### ① 签名透传（Task 协议）

- `fetcher/fetcher/control/task.py`：基类 `summary(self, all_stats)` → `summary(self, all_stats, db_path)`（db_path: str | Path；基类实现不读它，保持 `return str(all_stats)`）。
- `fetcher/fetcher/control/engine.py:223`：`self.task.summary(self.state['stats'])` → `self.task.summary(self.state['stats'], self.config.resolved_db_path())`。

### ② 8 处站点实现全部改

以下文件里的 `summary(self, all_stats)`：方法签名加 `db_path`，内部 `db = ShopDB()` 改 `db = ShopDB(db_path)`。**逐文件核对**（每个实现内的 stats/tmd 逻辑不动，只换 db 构造）：

- `fetcher/fetcher/sites/alibaba1688/contact.py`（:127，含 stats + format_tmd_report）
- `fetcher/fetcher/sites/alibaba1688/shop.py`（:212）
- `fetcher/fetcher/sites/alibaba1688/company.py`（:207）
- `fetcher/fetcher/sites/madeinchina/contact.py`（:201）
- `fetcher/fetcher/sites/madeinchina/shop.py`（:269）
- `fetcher/fetcher/sites/yiwugo/contact.py`（:159）
- `fetcher/fetcher/sites/yiwugo/search.py`（:134）
- `fetcher/fetcher/sites/taobao/search.py`（:163）

（grep 确认没有漏：`grep -rn "def summary" fetcher/fetcher/` 应只剩基类 + 这 8 处 + 不再有裸 `ShopDB()`）

### ③ 测试（TDD，先红后绿）

- **核心行为测试**：patch 各站点模块内的 `ShopDB`（如 `patch("fetcher.sites.alibaba1688.contact.ShopDB")`）为记录 db_path 的 fake，调用 `summary({...}, "/tmp/target.db")`，断言 fake 收到的路径 == "/tmp/target.db"（**证明 summary 不再默认开生产库**）。至少覆盖 1688 contact（含 tmd 分支）+ madeinchina contact + 一处 shop（如 1688 shop）；其余可抽查。RED 阶段：未修时 `ShopDB()` 收到的是 None/默认 → fake 记录的是默认路径 → 断言失败。
- **engine 装配**：`test_engine.py` 的 `test_summary_aggregates_all_workers`（:130）调用改为 `summary(stats, <db_path>)`（FakeTask/基类实现忽略 db_path，仅签名适配）；再补一条断言 engine 传给 summary 的是 `config.resolved_db_path()`（patch 基类 summary 记录入参，或 patch 各站点 ShopDB 配合现有 engine 测试——选可断言的）。
- 跑法：`cd fetcher && python -m pytest tests -x -q`（聚焦迭代，commit 前全量）。

## 验收

- [ ] grep：`fetcher/fetcher` 下无裸 `ShopDB()` 调用残留（只剩 `ShopDB(db_path)` / `ShopDB(path)` 形态）
- [ ] summary 行为测试证明传入了指定 db_path；全量无回归

## 约束

- 只改上述 fetcher/ 文件与测试；不碰 platform/、不碰生产库（**测试只读临时库**；本步不要打开 .cache/1688.db）
- 不动 summary 的 stats/tmd 内容逻辑，只换 db 构造
- **commit 纪律**：git add 显式列文件（禁止 -A/`.`）；commit 信息 `fix(identity-p2): summary 透传 db_path（临时库运行不再触碰生产库）`；自查 `git status` / `git diff --cached --stat`
- 注释中文、遵循既有模式

## 报告

完整报告写入 `docs/feat_2026-08-08_fetcher-identity-p2/task-3.1-fix-report.md`：
- 每处改动的改前/改后（8 处站点 + task.py + engine.py）
- **TDD 证据**：RED（命令 + 失败输出 + 为何符合预期）/ GREEN（命令 + 通过输出）
- grep 无裸 ShopDB() 证据
- 全量测试结果（总数）、改动的文件、commit（短 SHA + 标题）
