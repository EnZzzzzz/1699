# Spike Report — CloakBrowser 多 context 席位计数实测

> P3-0 Step 0.1 | 执行时间: 2026-08-13
> 来源: SPEC §4 C1 / PLAN.md P3-0 Step 0.1

## 目标

实测 CloakBrowser 会话席位按「浏览器二进制进程」还是按「BrowserContext」计数。
结论直接决定 P3-2 浏览器层「一进程多 context 只占 1 席」方案是否成立。

## 方法

脚本 `/tmp/spike_cloak_multicontext.py`，严格按以下序列执行：

1. **n0** — baseline：读取当前 `get_active_session_count(key)`
2. **n1** — headless 直连 launch CloakBrowser（无代理），读计数
3. **n2** — `browser.new_context(locale="zh-CN")`，读计数
4. **n3** — `ctx2.new_page()` → `page.goto("about:blank")`，读计数
5. **n4** — `browser.close()`，读计数

每次计数之间等待 3 秒（服务端租约注册/释放有延迟）。

Launch 参数：`headless=True, license_key=<key>, humanize=True, locale="zh-CN", timezone="Asia/Shanghai", stealth_args=False`（无代理、无 geoip）。

## 原始结果

| 步骤 | 操作 | 实测值 | 预期值 | 判定 |
|------|------|--------|--------|------|
| n0 | baseline | **0** | — | — |
| n1 | launch | **1** | n0 + 1 = 1 | ✓ |
| n2 | new_context | **1** | n1 = 1 | ✓ |
| n3 | ctx2.new_page() + goto("about:blank") | **1** | n2 = 1 | ✓ |
| n4 | browser.close() | **0** | n0 = 0 | ✓ |

### 第二个 context 可用性

- `ctx2.new_page()` — 成功
- `page.goto("about:blank")` — 成功
- context 完全可用，不受席位计数影响

## 预期 vs 实测（逐条）

| 断言 | 实测 | 预期 | 结果 |
|------|------|------|------|
| n1 = n0 + 1 | 1 | 1 | ✓ |
| n2 = n1（多 context 不占新席位） | 1 | 1 | ✓ |
| n3 = n2（goto 不占新席位） | 1 | 1 | ✓ |
| n4 = n0（关闭释放席位） | 0 | 0 | ✓ |

## 结论

**C1「一进程多 context 只占 1 席位」= 已验证。**

证据：launch 后席位 +1（n0→n1），创建第二个 BrowserContext 并实际使用（new_page + goto）后计数未变（n2=n3=n1=1），关闭浏览器后席位释放回基线（n4=n0=0）。CloakBrowser 会话席位以浏览器二进制进程为粒度计数，同一进程内的多个 BrowserContext 不额外占用席位。

## 环境说明

- 时间：2026-08-13（北京时间）
- Python：系统 python3
- 活爬虫占席情况：n0=0（本次执行时无活爬虫运行）
- 套餐类型：solo（5 席上限）
- 本次占用：最多 1 席（已确认释放）

## 复现命令

```bash
cd /Volumes/DataDrive/proj/public/1699
python3 /tmp/spike_cloak_multicontext.py
```

脚本内容见 `/tmp/spike_cloak_multicontext.py`（不入库）。

## 对后续的影响

P3-2 浏览器层「一进程多 context 只占 1 席」方案可安全推进。方案核心逻辑：
一个 CloakBrowser 进程内可创建多个 BrowserContext，各自绑定不同的 site+identity，
只占用 1 个会话席位，从而在有限席位下实现多队列跨站填充。
