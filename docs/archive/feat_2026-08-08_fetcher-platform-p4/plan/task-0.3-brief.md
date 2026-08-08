# task-0.3-brief — P4-0 Step 0.3：consumer_status 心跳 + proxy_channels 租约

## 位置

P4 平台切换第 0 阶段第 3 步（daemon 可观测底座）。改动范围：
`fetcher/fetcher/db.py`（建表 + 写方法）+ 新增 `fetcher/fetcher/control/status.py`
（心跳/租约管理）+ 测试 `fetcher/tests/test_consumer_status.py`。
daemon 装配接线在 P4-2 Step 2.3（start.sh 纳管）与 P4-3 看板读取，本 Step
只做 fetcher 侧写方与建表。

## 需求（SPEC §3.5 + PLAN Step 0.3）

### 1. consumer_status 表（幂等建表，fetcher db.py SCHEMA）

```sql
CREATE TABLE IF NOT EXISTS consumer_status (
    consumer_id TEXT PRIMARY KEY,     -- "w0".."wN" / "local0"..
    kind TEXT NOT NULL,               -- browser / local
    tunnel TEXT, exit_ip TEXT,
    current_queue TEXT, current_item_id INTEGER, current_batch_id INTEGER,
    cooldowns_json TEXT,              -- {"1688": 到期epoch, ...}
    updated_at TEXT NOT NULL          -- 北京时间
);
```

放在 work_items 建表之后。加注释：写方 = fetcher daemon（claim/finish/
release/冷却登记即时 + 10s 心跳 + 退出清空）；读方 = 平台 dispatcher API。

### 2. ConsumerStatusStore（fetcher/fetcher/control/status.py 新模块）

封装 daemon 侧对 consumer_status 与 proxy_channels 的写入（短事务 +
busy_timeout，WAL 并发安全）。类方法：

- `ConsumerStatusStore(db_path)`：持 ShopDB 连接（每线程独立，仿现有模式）。
- `upsert(consumer_id, kind, *, tunnel=None, exit_ip=None, queue=None,
  item_id=None, batch_id=None, cooldowns=None) -> None`：UPSERT 一行，updated_at
  = 北京时间。cooldowns 为 dict[site, epoch] → cooldowns_json。
- `clear(consumer_id) -> None`：删除该 consumer 行（daemon 退出时调用）。
- `heartbeat_all(consumers) -> None`：批量 UPSERT 全部在册 consumer
  （10s 心跳线程用；只更新 updated_at，保留其余字段——用现有行值回填）。
- `lease_channels(consumer_id, tunnels: list[str]) -> int`：
  `UPDATE proxy_channels SET used_by_task=consumer_id WHERE tunnel IN (...)`，
  返回行数（daemon 启动按 tunnel 匹配认领）。
- `release_channels(consumer_id) -> int`：`UPDATE proxy_channels SET
  used_by_task=NULL WHERE used_by_task=consumer_id`，返回行数（退出清零）。
  列名不改（SPEC §3.5 裁定：语义复用为 consumer 租约 + 注释，避免改名迁移）。

### 3. proxy_channels 列注释

proxy_channels.used_by_task 在 fetcher SCHEMA 中不存在（该表由平台建）——
fetcher 侧**不建表**，只通过 `UPDATE proxy_channels SET used_by_task=?` 写入。
生产库已有该表（平台 migrate 建）。**冒烟临时库需整体拷贝生产库**（含
proxy_channels 表），绝不直接对生产库写。测试用临时库需手工建 proxy_channels
表（仿平台 migrate 的 DDL，见 brief 末尾）。

## 验收（TDD，先写失败测试）

1. `upsert` 插入/更新行；updated_at 为北京时间格式 `YYYY-MM-DD HH:MM:SS`。
2. `clear` 删除行。
3. `heartbeat_all` 批量刷新 updated_at，且保留其他字段（不改 queue/item 等）。
4. `lease_channels` 按 tunnel 匹配写入 used_by_task；`release_channels` 清零。
5. 幂等：重复 lease 不产生重复；release 无租约时返回 0。
6. daemon 侧写入与平台读共存（WAL 并发）——单元层不测并发，留给 Step 2.3 冒烟。

## 测试基建（proxy_channels 临时表 DDL）

测试临时库需在建库后手工补 proxy_channels 表（fetcher SCHEMA 不建它）：

```sql
CREATE TABLE IF NOT EXISTS proxy_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER,
    tunnel TEXT, exit_ip TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    used_by_task INTEGER,
    ip_expires_at TEXT, last_probe_at TEXT,
    UNIQUE(provider_id, tunnel)
);
```

## 环境约束

- 测试全部临时 sqlite；绝不碰生产库 .cache/1688.db。
- 提交前 `cd fetcher && python3 -m pytest tests -q` 全量绿。
- 冒烟（临时库整体拷贝）在 Step 2.3 做，本 Step 只做单元测试。
