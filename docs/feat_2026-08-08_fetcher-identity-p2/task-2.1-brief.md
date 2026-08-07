# Step 2.1 brief — Session.close 域过滤 + _migrate 前缀迁移

> 来源：PLAN.md Phase 2 Step 2.1。本文本是你的需求唯一来源。工作目录：/Volumes/DataDrive/proj/public/1699

## 内容

### ① `Session.close()` 回写按 store.domain 过滤（SPEC §3.4）

`fetcher/fetcher/core/session.py` `Session.close()`（:53-58 一带）现状：

```python
if store is not None and self.page is not None:
    try:
        cookies = [c for c in self.ctx.cookies()]
        if cookies:
            store.save(self.identity, cookies)
    except ...
```

改为与 `IdentityStore.save_from_context` 同语义的域过滤（`fetcher/fetcher/net/identity.py:67` 的写法是 `self.domain in c.get("domain", "")`）：

```python
if store is not None and self.page is not None:
    try:
        cookies = [c for c in self.ctx.cookies()
                   if getattr(store, "domain", "") in c.get("domain", "")]
        if cookies:
            store.save(self.identity, cookies)
    except ...
```

- store 为 None 时保持现状（无回写）；`getattr(store, "domain", "")` 防御任何 store 形态——`"" in c.get("domain","")` 恒真则不过滤（与 save_from_context 的 `self.domain in ...` 语义对齐，实际调用方都是 IdentityStore）。
- 注释说明：多站共存前提下的桶纯度保证——同 IP 两站点各存各桶，回写不串站。

### ② `_migrate()` 幂等前缀迁移（SPEC §3.4，映射清单已回填）

`fetcher/fetcher/db.py` `_migrate()`（:225 起，现以 ip_events 补列结尾）末尾追加 cookies 表迁移。**映射清单（SPEC §3.4 回填，唯一依据）**：

| LIKE 模式 | 前缀 |
|---|---|
| `%made-in-china.com%` | `madeinchina:` |
| `%1688.com%` | `1688:` |
| `%taobao.com%` | `taobao:` |
| `%yiwugo.com%` | `yiwugo:` |

- 逐映射一条：`UPDATE cookies SET identity = '<prefix>' || identity WHERE identity NOT LIKE '%:%' AND domain LIKE '<pattern>'`
- **检测顺序**：先 made-in-china 再 1688 再 taobao 再 yiwugo（SPEC 裁定「先长后短更安全」）
- `identity NOT LIKE '%:%'` 保证幂等（已带前缀的行不再动）；无法映射的第三方域（如 `.mmstat.com`、`.ynuf.aliapp.org`）不匹配任何 pattern，自然保持原样
- 注释说明迁移语义与部署窗口（旧进程裸键读不到新前缀 Cookie → 白板重启一次，SPEC §3.4 运维注意）
- `_migrate()` 在 ShopDB 构造的 WAL/短事务上下文内执行（:204-218 已有），沿用即可，不另开连接

### ③ 单测（TDD，先红后绿）

- **close 域过滤**：构造 `Session(browser=MagicMock(), page=MagicMock(context=FakeBrowserContext([...1688.com cookie, .taobao.com cookie, .mmstat.com cookie])), identity="1688:1.2.3.4")`，`store=IdentityStore(db, domain="1688.com")`，调 `session.close(store=store)`，断言库中该 identity 下只存了 1688 域 Cookie（.taobao.com/.mmstat.com 不入库）；对照 store=IdentityStore(domain="made-in-china.com") 时只存 made-in-china 域。
- **迁移幂等**（SPEC §5 第 4 条）：
  1. 临时库手工插旧格式行（bare identity）：`1.2.3.4` 名下 `.1688.com`、`insights.1688.com`、`s.1688.com` 各一条；`5.5.5.5` 名下 `.made-in-china.com`、`cn.made-in-china.com` 各一条；`6.6.6.6` 名下 `.taobao.com` 一条；`7.7.7.7` 名下 `.yiwugo.com` 一条；`8.8.8.8` 名下 `.mmstat.com` 一条（无法映射对照）
  2. 打开库触发 `_migrate()`，断言：1688 域行 identity → `1688:1.2.3.4`、made-in-china 域 → `madeinchina:5.5.5.5`、taobao → `taobao:6.6.6.6`、yiwugo → `yiwugo:7.7.7.7`、mmstat 行保持 `8.8.8.8` 裸键
  3. 迁移后 `store.load("1688:1.2.3.4")` 能取到 1688 Cookie（SPEC §5.4「迁移后 1688 Cookie 可被新键正常 load」）
  4. **再迁移零变化**：关闭重开库（或重跑 `_migrate`）后全表快照逐行一致；`identity NOT LIKE '%:%'` 计数只含 mmstat 行
- 测试文件：可在 `fetcher/tests/test_identity.py` 追加或新建 `fetcher/tests/test_migration.py`（看既有组织习惯，新建文件注意 import 路径与既有 fixture 复用）
- 跑法：`cd fetcher && python -m pytest tests -x -q`（TDD 阶段聚焦，commit 前全量）

## 背景

P2：identity 键已升级为 `f"{site}:{ip}"`（Step 1.3）。生产库 18095 行存量 Cookie 全是裸键——本步的迁移让旧数据进新桶；close 回写过滤保证新桶内只有本站 Cookie（多站共存前提下的桶纯度）。本步起生产库打开即触发迁移（预期行为，部署窗口已记录）。

## 验收

- [ ] SPEC §5 第 4 条达成：迁移幂等（对新格式库重复执行零变化）；迁移后 1688 Cookie 可被新键正常 load
- [ ] 全量无回归（TDD 先红后绿，report 附 RED/GREEN 证据）

## 约束

- 只改 `fetcher/` 下代码与测试；不碰 platform/、fetcher/vendor/wa-check/、scraper/、util/
- **不碰生产库**（.cache/1688.db 只读都不必，测试全用临时库；不要打开生产库触发迁移）
- 不做 Step 2.2 内容（隔离性单测是下一步）
- **commit 纪律**：git add 显式列文件（禁止 -A/`.`）；commit 信息 `feat(identity-p2): Step 2.1 …`；自查 `git status` / `git diff --cached --stat`
- 注释中文、遵循既有模式；只改任务范围内代码

## 报告

完整报告写入 `docs/feat_2026-08-08_fetcher-identity-p2/task-2.1-report.md`：
- 每处改动的改前/改后
- **TDD 证据**：RED（命令 + 失败输出 + 为何符合预期）/ GREEN（命令 + 通过输出）
- 迁移测试的断言输出（含再迁移零变化的证据）
- 全量测试结果（总数）、改动的文件、commit（短 SHA + 标题）
- 自查发现与疑虑
