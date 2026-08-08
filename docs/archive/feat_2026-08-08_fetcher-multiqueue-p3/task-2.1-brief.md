# Task 2.1 Brief — Session/SiteView 重构（多 context 结构 + 路由 + 两层关闭）

> 来源：PLAN.md P3-2 Step 2.1 全文 + SPEC §3.6/§4 C1/C2 + 主 Agent 裁定（ledger 7）。本文件是本次任务的唯一需求来源。

## 目标

把 `Session` 从「单 browser+单 context+单 page」重构为「browser + views: dict[site, SiteView]」的多 context 结构，`ctx.page`/`session.page`/`session.ctx` 路由到「活动站点 view」。**单站点路径行为等价**（1688 contact 旧 CLI 冒烟）是验收口径；多站点视图结构就绪（P3-3 router 才真正多站点装配）。

## 背景（C1/C3 已验证）

- C1 已验证：CloakBrowser 席位按**浏览器进程**计租约，一进程多 context 只占 1 席（spike 报告 docs/feat_2026-08-08_fetcher-multiqueue-p3/spike-cloakbrowser-multicontext.md）
- C3：同进程多 context 共享进程级指纹/代理旗标——`browser.new_context()` 是进程内纯 Playwright API，**不需要也不能传代理**（代理是 launch 时进程级配置）
- identity 键已是 `site:ip`（P2）：每个 view 有独立 identity（Cookie/簿记按 site 分桶）

## 规格

### 1. Session 结构（core/session.py）

```python
@dataclass
class SiteView:
    """一个站点在本浏览器进程内的独立上下文视图。"""
    context: Any = None          # Playwright BrowserContext
    page: Any = None             # Playwright Page
    identity: str = ""           # f"{site}:{ip}" 或 f"{site}:direct"（P2 键）
    seed_kit: dict | None = None
    domain: str = ""             # 该站 Cookie 域（close_site 回写过滤用）

@dataclass
class Session:
    browser: Any = None
    channel: "Channel | None" = None
    req_proxies: dict | None = None
    views: dict[str, SiteView] = field(default_factory=dict)  # site 注册名 → view
    seed_kit: dict | None = None   # 进程级种子（首个 view 播种用；保留兼容）
    extra: dict = field(default_factory=dict)
    _active_site: str | None = None   # 当前活动站点（view 路由用；由控制层设置）

    @property
    def page(self): ...   # 路由到活动 view 的 page
    @property
    def ctx(self): ...    # 路由到活动 view 的 context
    @property
    def identity(self): ...  # 路由到活动 view 的 identity
```

- **路由规则**：`_active_site` 非空且 views 有该 site → 返回该 view 的 page/ctx/identity；否则 views 唯一（len==1）时返回唯一 view 的；否则返回 None/空串
- **`_active_site` 设置**：控制层（loop/engine/router）在 item 装配时经 `ctx.state["active_site"]` 设置后调用 `session.set_active_site(site)`（新增小方法）；未设置时回退唯一 view
- 保留 `bare_identity`/`is_direct` 模块级函数（不动）
- `use_proxy` property 保留（channel 判断）

### 2. ensure_site（net/browser.py，BrowserManager 方法）

```python
def ensure_site(self, session: Session, site_name: str, site_domain: str) -> SiteView:
    """确保 session 有 site_name 的 view；无则懒建。

    懒建：browser.new_context(locale="zh-CN") → 按 f"{site_name}:{bare}"
    装载 Cookie（库优先；直连无库时 JSON 种子兜底；代理新 IP 播种
    seed_kit——复用 launch 的 Cookie 装载段逻辑）→ new_page →
    warmup（该站首页现场签发 Cookie）。返回 view。
    """
```

- **Cookie 装载逻辑必须与 launch 现状逐字一致**（直连种子导入、代理播种、白板启动、无 Cookie 直连报错等分支），只是目标从「进程级单 context」改为「该 site 的 view」
- **warmup 改造**：现 `warmup(session, homepage, stop, block_check)` 操作 session.page/ctx/identity——改为操作**指定 view**（`warmup(session, site_name, homepage, stop, block_check)` 或等价签名），内部用 view.page/view.ctx/view.identity；回写按 **view.domain** 过滤
- 单站点路径：`launch()` 建进程后调用 ensure_site(site_name=site_name, site_domain=store.domain 或站点 cookie_domain) 建初始 view——保证 CLI 路径行为等价

### 3. 两层关闭（core/session.py）

```python
def close_site(self, site: str, store=None, log=None):   # 回写该 view Cookie（按 view.domain 过滤）→ 关 context → 从 views 移除
def close(self, store=None, log=None):                    # 全部 view close_site → browser.close()
```

- 回写过滤：`cookies = [c for c in view.context.cookies() if view.domain in c.get("domain","")]`（与现 close/save_from_context 同语义，域改 per-view）
- `close()` 保留现有关闭语义（loop._cleanup 用）；`close_site` 供 P3-3 SwapIP 两阶段用
- **IdentityStore.save_from_context 需要 per-view 域过滤**：新增 `domain` 参数（`save_from_context(identity, ctx, log, domain=None)`，None 时回落 store.domain）或 BrowserManager 内联过滤后 store.save——选实现简单且不破坏现有调用的方案

### 4. relaunch 适配（net/browser.py）

- 现 `relaunch(session, ...)` 调 `session.close(store, log)` 后 launch 新进程
- 改为：**全部 view 回写 Cookie（close_site 语义）→ browser.close() → launch 新进程（新 IP）→ views 清空懒重建**（初始 view 由 launch 建）
- `check_ip_fresh` 不变（进程级 session.req_proxies/bare_identity）

### 5. SPEC §6.1 消费方迁移（本 Step 范围：session/browser 两侧）

- `core/session.py`：Session 定义/ctx property/close —— 本 Step 重构
- `net/browser.py`：launch/relaunch/warmup/save_cookies/check_ip_fresh —— 本 Step 适配
- `save_cookies(session)`：改为遍历 views 全部回写（或活动 view 回写——选遍历全部，保证进程退出不丢任何站点 Cookie）
- loop/atoms/strategies 的 `ctx.page`/`session.page`/`session.ctx` 消费方（detect/generic.py、atoms/browser_ops.py、atoms/human.py、atoms/slider.py、atoms/refresh.py、sites/* 共 20+ 处）**经 ctx.page 统一路由，本 Step 零改动**（worker 的 ctx.session 仍是 Session，page property 路由自动跟随）——grep 复核无直接持有 page 跨 item 的引用
- `WorkerContext.page` property（context.py:121）不变（它调 session.page）

## TDD 要求（先写失败测试、亲眼看它失败、再最小实现）

至少覆盖：

1. **路由规则**：设 _active_site="1688" 时 page/ctx/identity 返回 views["1688"] 的；未设时唯一 view 回落；两 view 无 active 时返回 None/空
2. **C2 隔离单测**（SPEC C2）：同 browser 两 context Cookie 互不可见——优先用真实 Playwright（`playwright.sync_api`，context A set cookie → context B 读不到）；本机若无 playwright 浏览器二进制则用两个 fake context 对象模拟隔离语义（context 对象带独立 cookies()/add_cookies()），并注明
3. **ensure_site 懒建**：已存在 view 不重建（browser.new_context 调用次数断言）；新建后 view 的 identity/domain 正确
4. **close_site 回写过滤**：view 的 cookies 中本站域落库、他站域不落
5. **close 两层**：全部 view 回写 + browser.close 一次
6. **relaunch 全 view 回写**：两 view 的 Cookie 都回写后新进程
7. **单站点等价**：CLI 路径（engine+loop 假基建或最小装配）下 Session 行为与旧结构一致（page 路由、identity、close）

## 冒烟（等价确认，report 附证据）

旧 CLI `1688 contact` 直连冒烟（环境铁律：--workers 1、临时库放 /tmp、+1 席以内）：

```
cd /Volumes/DataDrive/proj/public/1699/fetcher
python -m fetcher 1688 contact --db /tmp/smoke_p3_21.db --workers 1 --limit 2 -n 1
```

- 直连滑块墙全 failed 是环境噪声；取结构证据：launch→warmup→认领→处理→退出 全链路无异常、Cookie 回写路径正常（日志）、exit 干净
- 冒烟日志写 `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step2.1/`（随跑随写）
- 若席位满（活爬虫占席）等待超时，报告环境情况，可稍后重跑或降级为单测证据+说明

## 上下文

- 项目根 `/Volumes/DataDrive/proj/public/1699`；工作目录 `fetcher/`；全量测试 `cd fetcher && python -m pytest tests -q`（基线 342 passed）
- 现状（已读码）：`core/session.py:26-81`（Session 单 page/ctx/identity + close 按 store.domain 过滤）；`net/browser.py:204-284` launch（identity 拼前缀 :221/:237、context 创建 :256-261、Cookie 装载 :228-254、warmup 调用 :262-267）；`:344-384` relaunch（session.close 后 launch）；`:398-460` warmup（操作 session.page/ctx/identity）；`:497` save_cookies（save_from_context）；`net/identity.py:60-73` save_from_context（store.domain 子串过滤）
- `WorkerContext.page`（context.py:121）→ session.page；loop._cleanup（loop.py:250-263）调 session.close(store, log)；RelaunchBrowser 原子（atoms/browser_ops.py:30-60）调 mgr.relaunch 后 ctx.session 替换
- `_active_site` 与本 Step 的关系：P3-3 router 才设置它；本 Step 先把路由规则与 set_active_site 做好，单站点路径（CLI/daemon 单队列）靠「唯一 view 回落」等价
- 不要动 `fetcher/fetcher/control/`（loop/daemon_task/queue_router）、`fetcher/fetcher/db.py`、`fetcher/fetcher/core/context.py`（Step 1.2/1.3 已完成）；策略层（strategies.py）的 SwapIP 两阶段是 P3-3 Step 3.2，本 Step 只保证其消费的 session 结构就绪

## Git

- 分支 `feat/multiqueue-p3`；scoped add：`fetcher/fetcher/core/session.py`、`fetcher/fetcher/net/browser.py`、`fetcher/fetcher/net/identity.py`（如改动）、`fetcher/tests/` 下本次改动文件、`docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step2.1/` 冒烟日志
- 工作区有他人未提交改动（platform/*、fetcher/vendor/wa-check/check.js 等），**绝不碰绝不带**，不要 `git add -A`
- commit 标题风格：`feat(multiqueue-p3): <一句话>`
- 若 commit 遇 `.git/index.lock` 竞态，sleep 几秒重试一次，仍失败则保留工作区不 commit 并在 report 注明

## 验收

1. TDD 证据（RED→GREEN）
2. 全量 `cd fetcher && python -m pytest tests -q` 绿
3. C2 隔离单测通过（真实 playwright 或 fake context + 注明）
4. 冒烟证据落 smoke-step2.1/（或如实说明环境受限）
5. 报告 `docs/feat_2026-08-08_fetcher-multiqueue-p3/task-2.1-report.md`：实现摘要、测试列表、TDD 证据、冒烟证据、改动文件、自查发现
