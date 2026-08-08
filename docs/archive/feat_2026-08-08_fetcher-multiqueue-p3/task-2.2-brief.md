# Task 2.2 Brief — needs_relaunch 状态位 + 种子池 (worker, site) 粒度

> 来源：PLAN.md P3-2 Step 2.2 全文 + SPEC §3.5/§3.6/§5。本文件是本次任务的唯一需求来源。

## 目标

1. 建立 `needs_relaunch` 状态位机制（SPEC §5 职责表：SwapIP 两阶段置位 / relaunch 完成清除 / context 懒建路径消费）——本 Step 建机制 + 单测，P3-3 Step 3.2 接 SwapIP 置位
2. 种子身份池认领粒度从「每 worker 一份」改为「每 (worker, site) 一份」（SPEC §3.6）——分配函数改造 + 单测，P3-3 daemon 装配接入；**CLI 单站点路径行为逐字不变**
3. relaunch 全 view 回写 + views 清空懒重建（Step 2.1 已完成主体，本 Step 复核/补缺）+ 旧 CLI 等价冒烟确认

## 规格

### 1. needs_relaunch 状态位（net/browser.py + core/session.py）

- 存储：`session.extra["needs_relaunch"]` = dict[site, True]（session.extra 是现成状态暂存区；SPEC 写作 session.state，实现落 extra 并注释对应）
- API（BrowserManager 或 Session 上，选职责清晰处）：
  - `mark_needs_relaunch(session, site)`：置位（SwapIP 两阶段第一步调用）
  - relaunch 完成路径清除：`session.extra["needs_relaunch"].pop(site, None)`
- **懒建消费（核心机制）**：`ensure_site(session, site, ...)` 入口处——若 `needs_relaunch.get(site)` 为真 → **先走完整 relaunch**（全部 view 回写关闭 → browser.close → 新进程 → 清除该 site 标记）→ 继续正常懒建本站 view。语义对应 SPEC §3.5 步骤 4：「冷却到期后再次被认领时，context 懒建路径发现 needs_relaunch → 走完整 relaunch」
- 注意与 Step 2.1 的 relaunch 路径协调：ensure_site 触发的完整 relaunch 应复用现有 relaunch 逻辑（全部 view close_site 回写 + 新进程 launch），不要另写一遍；用标志参数或内部 helper 避免递归（ensure_site → relaunch → launch → ensure_site 初始 view）
- 单测：置位后 ensure_site 触发 relaunch（browser.close 与新 launch 各一次）且清除标记；未置位时正常懒建不 relaunch；多 site 只 relaunch 一次（非每 site 各 relaunch——relaunch 是进程级，一次即可，其余 site 后续懒建）

### 2. 种子池 (worker, site) 粒度（control/engine.py）

现状：`_alloc_seed_kits(workers) -> list`（每 worker 一份，kits[i] 或 None，CLI 用）。

改造：

```python
def _alloc_seed_kits(self, workers: int, sites: list = None):
    """种子身份池分配。

    sites=None（CLI 单站点路径）：返回现状 list[kit]（每 worker 一份，
    行为逐字不变）。
    sites 非空（daemon 多站点路径）：返回 dict[site_name, list[kit]]
    ——每 (worker, site) 一份；load_seed_kits(domain=该站点 cookie_domain)
    逐站点加载后按下标分配（越界 None=白板，日志同现状）。
    """
```

- sites 元素需有 `name`（注册名）与 `cookie_domain`——daemon 分支（P3-3）会传注册表各 site 插件；本 Step 用鸭子类型即可（测试用 SimpleNamespace）
- **CLI 路径（sites=None）返回类型与现状完全一致**（list），engine.run 的消费逻辑不破坏
- seed_x5sec A/B 实验：多站点路径按 (worker,site) 同样适用（偶数 worker A 组），实现保持一致即可
- 日志：逐站点打印池大小（复用现状 [seed] 行格式）
- 单测：sites=None 返回 list 与现状一致；多站点返回 dict[site][worker] 正确映射（每 worker 每 site 独立）；越界 None；cookie_domain 过滤生效（不同 site 不同域加载不同池）

### 3. relaunch 复核 + 冒烟等价

- 复核 Step 2.1 的 relaunch（browser.py relaunch → session.close 全 view 回写 → launch 新进程 → 新 views）无缺漏：确认 close_site 在 relaunch 前对全部 views 生效、views 清空、_exit_ip 缓存重建（新进程新 IP）
- 冒烟：旧 CLI 1688 contact 直连（环境铁律 --workers 1、临时库 /tmp、+1 席内）等价确认——Step 2.1 的 smoke-fix1-raw.txt 已是该形态证据；本 Step 可选复跑或引用既有证据并说明（**不要为了跑而跑**，若跑则 raw 输出落盘 smoke-step2.2/）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖：

1. mark_needs_relaunch 置位 / relaunch 清除
2. ensure_site 消费：needs_relaunch[site] 置位 → 触发完整 relaunch（新 launch 一次）且清除；未置位正常懒建
3. 多 site 场景只 relaunch 一次（进程级）
4. _alloc_seed_kits：sites=None 返回 list 与现状一致（逐字等价断言）；多站点 dict[site][worker] 映射正确；越界 None；seed_x5sec 分支
5. cookie_domain 过滤：两站点不同域 → 各自池按各自域加载（mock load_seed_kits 或注入）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 379 passed）
- 现状（已读码）：`net/browser.py:317-356` relaunch（session.close 全回写 + launch 重建）；`:361-460+` ensure_site（含 _exit_ip 缓存、Cookie 装载、warmup per-view）；launch 建初始 view（:292 ensure_site(session, self.site_name, ...)）；`control/engine.py:86-111` _alloc_seed_kits（每 worker 一份 + seed_x5sec A/B）；`net/seeds.py` load_seed_kits(seeds_dir, keep_x5sec, domain, log)
- Session.extra 是现成状态暂存 dict（Step 2.1 已用 extra["_exit_ip"] 缓存 IP）
- 本 Step 不动 db.py、control/loop.py、daemon_task.py、queue_router.py、strategies.py（SwapIP 两阶段 P3-3）；engine.py 只改 _alloc_seed_kits（含签名）与其调用点（engine.run 里 worker_kits 消费——sites=None 时保持现状）
- 若 _alloc_seed_kits 返回结构变化影响 engine.run：保持 sites=None 时返回 list，engine.run 无需改动；多站点返回结构由 P3-3 daemon 分支消费

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/net/browser.py`、`fetcher/fetcher/core/session.py`（如改动）、`fetcher/fetcher/control/engine.py`、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step2.2/`（如冒烟）
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`
- 若 commit 遇 `.git/index.lock` 竞态，sleep 几秒重试一次，仍失败则保留工作区不 commit 并在 report 注明

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 单测覆盖：needs_relaunch 置位/清除/懒建消费、种子池 (worker,site) 映射与 CLI 等价
4. 冒烟等价确认（复跑或引用既有证据+说明）
5. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.2-report.md`：实现摘要、测试列表、TDD 证据、冒烟说明、改动文件、自查发现
