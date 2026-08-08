# Task 3.3 Report — 跨站 view 懒建补缺 + 双队列跨站填充冒烟

> 日期：2026-08-08 | 分支：feat/multiqueue-p3

## 实现摘要

### 第一部分：跨站 view 懒建补缺（TDD）

**缺口**：`loop._bind_item_site` 在 Step 3.1 中建立了 ctx.site/inspector/policy 绑定，但未调用 `ensure_site` 和 `set_active_site`。跨站 item（router 认领的 item 站点 ≠ 初始 view 站点）无 view 会导致 `ctx.page` 路由失败。

**修复**：在 `_bind_item_site` 中补入 ensure_site + set_active_site 调用（`fetcher/control/loop.py:331-345`）：

```python
plugin = self.sites.get(site_name)
if plugin is not None:
    self.ctx.site = plugin
    # 跨站 view 懒建（SPEC §3.6）
    if (self.ctx.session is not None
            and self.ctx.browser_manager is not None):
        try:
            self.ctx.browser_manager.ensure_site(
                self.ctx.session, site_name, plugin.cookie_domain)
            self.ctx.session.set_active_site(site_name)
        except Exception as e:
            self.log(f"[!] ensure_site({site_name}) 失败: {e}，"
                     f"继续处理 item（fetch 兜底）")
    self.inspector = SceneInspector.for_site(plugin)
    ...
```

- **异常容错**：ensure_site 可能 raise（直连无 Cookie 等）→ try/except 记日志后继续，由 fetch 层既有错误链兜底
- **CLI 单站点**：sites=None 时提前返回，不变

### 第二部分：双队列跨站填充冒烟

见 `smoke-step3.3/analysis.md` 详细取证分析。核心证据：
- 初始 launch 建 1688 view → mic item 认领时 ensure_site("madeinchina") 被调
- mic 的 dummy cookie 从 DB 正确装载（1 条）
- mic 页面请求通过 mic view 成功发出（tmd 统计 "madeinchina:direct" 1 请求/0 触发）
- 直连 1688 滑块墙导致 worker 在策略链预存 bug 中崩溃，阻止了完整的 1688→mic 手递手证据（环境噪声，用户已声明）

## 测试列表

### 新增测试（test_control_loop.py::CrossSiteLazyViewTest，5 个）

| # | 测试 | 覆盖点 |
|---|---|---|
| 1 | `test_cross_site_lazy_build` | daemon 多站点装配 → ensure_site(siteB) + set_active_site(siteB) + ctx.site 切换 |
| 2 | `test_ensure_site_idempotent` | 同 site 连续两 item → ensure_site 只调一次（view 已存在） |
| 3 | `test_switch_back_to_original_site` | site B item 后 site A item → active_site 回切 A，ensure_site(A) 幂等 |
| 4 | `test_ensure_site_exception_tolerance` | ensure_site raise → 记日志不崩 worker |
| 5 | `test_cli_single_site_no_ensure_site` | sites=None → 无 ensure_site 调用（回归） |

### 全量结果

```
445 passed, 2 subtests passed in 25.92s
```

（基线 440 + 新增 5 = 445，无回归）

## TDD 证据

1. **RED**：先写 5 个测试 → 4 FAIL + 1 PASS（CLI 回归测试原本绿）
2. **GREEN**：实现 `_bind_item_site` 中 ensure_site + set_active_site 调用后 → 5/5 PASS
3. **REFACTOR**：无需重构（改动点精确集中在 `_bind_item_site` 方法内）

## 冒烟取证

详见 `smoke-step3.3/analysis.md`。关键取证要点：

| 证据 | 来源 |
|---|---|
| ensure_site("madeinchina") 被调 | daemon-run-4.log: `[cookie] identity=madeinchina:direct，可用 1 个` |
| mic dummy cookie 被装载 | DB 预置 1 条 madeinchina:direct cookie |
| mic 页面请求穿过 mic view | tmd 统计: `madeinchina:direct 1 1 0 0.0%` |
| 1688→mic 认领顺序 | 环境限制：直连 1688 滑块墙导致 worker 崩溃（预存 bug），未达完整手递手 |

## 改动文件

| 文件 | 改动 |
|---|---|
| `fetcher/fetcher/control/loop.py` | `_bind_item_site` 补 ensure_site + set_active_site + try/except 容错 |
| `fetcher/tests/test_control_loop.py` | 新增 MockPlugin、MultiSiteMockBrowserManager、MultiSiteScriptedTask、CrossSiteLazyViewTest（5 测试） |
| `docs/feat_2026-08-08_fetcher-multiqueue-p3/smoke-step3.3/` | 冒烟日志（daemon-run-1~4.log）+ analysis.md |

## 自查发现

1. **预存 bug**：直连 1688 滑块墙触发策略链时 worker 异常退出（'empty'/'failed' 字符串异常）。该问题在 git stash 回退本次改动后仍可复现，确认非本次引入。建议开独立 issue 跟踪。
2. **嗅探风险**：ensure_site 的 try/except 兜底策略合理——view 建失败不崩 worker，item 处理由 fetch 层兜底。但如果 session 无任何 view（首个 site 的 view 也建失败），所有后续 fetch 都会失败。当前实现不会恶化此场景（worker 逐步给 up 所有 item 后正常退出）。
3. **Mock 完整性**：MultiSiteMockBrowserManager 的 launch() 覆盖了 ensure_site 懒建路径，但未覆盖 ensure_site 的 needs_relaunch 消费路径（该路径依赖真实 BrowserManager.relaunch 的两阶段逻辑）。如需覆盖建议后续添加集成测试。
