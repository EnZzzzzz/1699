# Task 3.3 Brief — 跨站 view 懒建补缺 + 双队列跨站填充冒烟

> 来源：PLAN.md P3-3 Step 3.3 全文 + SPEC §3.1/§3.6 验收口径 + 主 Agent 独立检视发现。本文件是本次任务的唯一需求来源。

## 背景（主 Agent 独立检视发现的缺口，须先补）

grep 复核发现：**router/loop 均未调用 ensure_site**——只有 `BrowserManager.launch` 建初始 view（site_name）。跨站填充的核心场景（router 认领的 item 站点 ≠ 初始 view 站点）下，该 site 没有 view，`ctx.page` 路由会失败（`_active_site` 非空但 views 无该 site → None），fetch 将崩。SPEC §3.6 明确「懒建：router 绑定 item 站点时 session.ensure_site(site)」；Step 3.1 brief 也写了「多 site 的 view 由 router 调 ensure_site 懒建」但实现未落实（reviewer 依赖假浏览器测试未触达真实装配，属 ⚠️ 漏检）。

**本 Step 第一部分先补该缺口（TDD），第二部分做双队列跨站冒烟（验收证据）。**

## 规格

### 1. 跨站 view 懒建（control/loop.py `_bind_item_site` 或等价位置，选职责清晰处）

`loop._bind_item_site()`（Step 3.1 已建，绑定 ctx.site/inspector/policy）内补：

```python
site_name = self.ctx.state.get("active_site")
if site_name and site_name != self._bound_site:
    plugin = self.sites.get(site_name) if self.sites else None
    if plugin is not None:
        self.ctx.site = plugin
        # 跨站 view 懒建（SPEC §3.6）：无 view 则建，路由活动站点
        if (self.ctx.session is not None
                and self.ctx.browser_manager is not None):
            self.ctx.browser_manager.ensure_site(
                self.ctx.session, site_name, plugin.cookie_domain)
            self.ctx.session.set_active_site(site_name)
        self.inspector = SceneInspector.for_site(plugin)
        self.policy = self.policies.get(site_name, self.policy)
        self._bound_site = site_name
```

- 保证点：`_bind_item_site` 在 run() 里 acquire 返回后（设 item 后）与 `_process_item` 内被调（Step 3.1 已有调用点，确认位置覆盖两种场景）
- `ensure_site` 已存在（Step 2.1，幂等：view 存在直接返回）；`set_active_site` 已存在（Step 2.1）；`plugin.cookie_domain` 各站点插件有
- **异常容错**：ensure_site 可能 raise（如直连无该站 Cookie）——`_bind_item_site` 不应让 worker 崩：包 try/except 记日志，item 处理继续（fetch 若因无 view 失败走既有 BROWSER_DEAD/NET_ERROR 链处置）？还是直接视为 item 失败？——**裁定：try/except 记日志后继续**（view 建失败的 item 由 fetch 层既有错误处置兜底；不因单站 view 失败崩 worker）。若你认为继续会导致更坏后果（如后续 fetch 全崩），在 report 说明并给方案。
- CLI 单站点路径：sites 为空 dict → `_bind_item_site` 无操作（现状不变）

### 2. 双队列跨站冒烟（验收证据）

环境铁律：--workers 1、直连、临时库放 /tmp、CloakBrowser +1 席以内。

**临时库预置**（python + sqlite3 或复用 fetcher.db.ShopDB，写 /tmp 临时库不碰生产库）：
1. 1688 店铺 2 个（domain 后缀 .1688.com）
2. mic 店铺 2 个（domain 后缀 .cn.made-in-china.com）
3. **madeinchina:direct 桶插 1 条 dummy cookie**（域 .cn.made-in-china.com，name/value 随意）——原因：直连模式下 ensure_site 无该站 Cookie 会 raise BrowserLaunchError；mic 免登录静态页无 Cookie 也能抓，dummy cookie 只为了让 ensure_site 直连分支通过（不改产品代码）

**冒烟命令**：

```
cd fetcher
python -m fetcher daemon --db /tmp/smoke_p3_33.db --workers 1 --limit 6 -n 1 \
  --queues crawl_1688_contact,crawl_mic_contact \
  --batch-rest 60 --max-consecutive-fail 3   # 参数可按需微调（小批量快速收工）
```

**取证（跨站填充核心证据，日志落 plan 目录 smoke-step3.3/）**：
1. 1688 滑块墙失败 → block_rest/策略冷却让出型登记（冷却期间 1688 队列不可见）
2. **冷却期间同 worker 认领并执行 mic 工作项**（认领日志 + mic item 处理开始）
3. mic 处理结果（成功或按环境失败，记录）
4. 1688 冷却到期 → 恢复认领 1688 item（反向证据）
5. work_items 终态（done/failed/pending 分布）、shops/contacts 落库口径
- 若 mic 也因环境失败，取「认领顺序」结构证据即可（1688 冷却 → mic 认领），不要求抓取成功
- 运行时长控制：预期 3~5 分钟内收工（--limit 6）；若超 10 分钟，取证当前输出后 Ctrl-C 收尾并记录
- 直连滑块墙全 failed 是环境噪声（用户已声明），不要在此耗时间

**冒烟日志**：`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/`（命令 + raw 输出 + 取证分析 md，随跑随写）

## TDD 要求（第一部分跨站懒建，先写失败测试亲眼看失败）

至少覆盖：

1. **跨站懒建**：daemon 装配（sites 注入）+ 假浏览器（mock ensure_site 记录调用）→ 处理 site B item 时 ensure_site(siteB) 被调 + set_active_site(siteB) 被调 + ctx.site 切换
2. **幂等**：同 site 连续两 item → ensure_site 只调一次（view 已存在）
3. **回切**：site B item 后 site A item → ensure_site(siteA) 幂等返回 + active_site 回切 A
4. **异常容错**：ensure_site raise → 记日志不崩 worker（loop 继续/退出语义按裁定）
5. **CLI 单站点**：sites 为空 → 无 ensure_site 调用（现状不变，回归断言）

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 440 passed）
- 现状（已读码）：loop.py `_bind_item_site`（Step 3.1，绑 ctx.site/inspector/policy，未含 ensure_site）；browser.py `ensure_site`（:386，幂等 + needs_relaunch 消费 + Cookie 装载 + warmup）；session.py `set_active_site`/`page`/`ctx`/`identity` 路由（Step 2.1）；queue_router.py QueueRouter（Step 3.1，acquire 写三个状态键，未调 ensure_site）
- daemon 装配（cli/main.py）：sites dict 已注入 loop（Step 3.1 的 sites/policies 参数）
- 冒烟临时库操作：可写 /tmp 脚本（python + fetcher.db.ShopDB 或 sqlite3），不碰生产库 .cache/1688.db（只读纪律）

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/control/loop.py`（+测试文件）、`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/` 冒烟日志、`docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md`
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. 冒烟证据落 smoke-step3.3/：命令 + raw 输出 + 跨站填充取证分析（1688 冷却 → mic 认领顺序可证）
4. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-3.3-report.md`：实现摘要、测试列表、TDD 证据、冒烟取证、改动文件、自查发现
