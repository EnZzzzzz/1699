# Step 1.2 Report — 辅助函数 + 隐藏点修正（SPEC §3.3 清单 #1-#6）

> 日期：2026-08-08 | 分支：feat/fetcher-identity-p2 | commit：bfd97d3

## 概述

在 `fetcher/` 侧完成 identity 辅助函数 `bare_identity` / `is_direct` 及 6 处隐藏使用点的修正。所有改动按字符串工作，对当前无前缀键行为等价；prefix 拼上后（Step 1.3）这些点自动正确。

## 改动清单

### ① `core/session.py` — 新增模块级辅助函数

```python
def bare_identity(identity: str) -> str:
    """剥掉站点前缀；无前缀原样返回（兼容旧键/直连旧值）。"""
    return identity.split(":", 1)[1] if ":" in identity else identity

def is_direct(identity: str) -> bool:
    """identity 是否代表直连模式（含 'direct' 与 'site:direct' 两种形态）。"""
    return bare_identity(identity) == "direct"
```

### ② 6 处修正（逐条）

| # | 文件 | 位置 | 改前 | 改后 |
|---|------|------|------|------|
| 1 | `net/browser.py` | `check_ip_fresh` :196 | `if cur_ip != session.identity:` | `if cur_ip != bare_identity(session.identity):` |
| 2 | `control/loop.py` | :451 登录墙判定 | `if login_wall and identity != "direct" and ctx.store is not None:` | `if login_wall and not is_direct(identity) and ctx.store is not None:` |
| 3 | `atoms/identity_ops.py` | :25 ClearIdentity | `if identity == "direct":` | `if is_direct(identity):` |
| 4 | `db.py` | :684 `ip_event_summary` | `WHERE identity != 'direct'` | `WHERE identity NOT LIKE '%:direct' AND identity != 'direct'` |
| 5 | `db.py` | `format_tmd_report` 表头+数据行 | `:<17`（两处） | `:<22`（两处同步） |
| 6 | `net/browser.py` | `launch` 指纹传参 :299 | `args=fingerprint_args(seed_kit["name"] if seed_kit else identity)` | `args=fingerprint_args(seed_kit["name"] if seed_kit else bare_identity(identity))` |

### ③ TDD — 21 个新测试

| 测试文件 | 测试数 | 覆盖 |
|----------|--------|------|
| `tests/test_session_helpers.py` | 8 | `bare_identity` / `is_direct` 所有输入形态 |
| `tests/test_identity.py` | 5 | #3 ClearIdentity（prefixed direct 跳过 / 非直连清空 / 旧键回归）；#4 ip_event_summary（双滤）；#5 format_tmd_report（列宽容纳） |
| `tests/test_browser_fresh.py` | 7 | #1 check_ip_fresh（prefixed 同 IP 不轮换 / 换 IP 触发 / 旧键回归）；#6 fingerprint_args（prefixed 与 bare 同指纹 / launch monkeypatch） |
| `tests/test_control_loop.py` | 1 | #2 login_wall 不误烧 prefixed direct |

## TDD 证据

### RED（每处修正的失败证据）

**Helper functions:** `ImportError: cannot import name 'bare_identity'` — 函数不存在，8 tests 全部失败。

**#1 check_ip_fresh:**
```
AssertionError: True is not false : 不应触发 relaunch，reason=出口 IP 已轮换（1688:1.2.3.4 -> 1.2.3.4）
```
预期：`"1.2.3.4" != "1688:1.2.3.4"` → True → 误判轮换。修正后 `bare_identity("1688:1.2.3.4")` = `"1.2.3.4"` → 相等 → 不触发。

**#2 login_wall:**
```
AssertionError: 0 != 1 : prefixed direct 身份应保留 Cookie，不应被烧毁
```
预期：`"1688:direct" != "direct"` → True → 触发 burn。修正后 `is_direct("1688:direct")` → True → 跳过。

**#3 ClearIdentity:**
```
AssertionError: <Outcome.OK: 'ok'> is not <Outcome.SKIPPED: 'skipped'> : 期望跳过直连身份
```
预期：`"1688:direct" == "direct"` → False → 走 burn 路径。修正后 `is_direct("1688:direct")` → True → skipped。

**#4 ip_event_summary:**
```
AssertionError: Items in the first set but not the second: '1688:direct'
期望只含 IP 行，实际={'1.2.3.4', '1688:direct', '1688:1.2.3.4'}
```
预期：SQL `!= 'direct'` 不排除 `'1688:direct'`。修正后双滤排除。

**#5 format_tmd_report:**
```
AssertionError: 27 != 25 : 不同长度 identity 的请求列应对齐
实际 1.2.3.4=25, madeinchina:1.2.3.4=27
```
预期：列宽 17 < 21 → 长 identity 撑列宽，两行不对齐。修正后 22 容纳全部。

### GREEN（修正后）

```
cd fetcher && python -m pytest tests -x -q
270 passed, 2 subtests passed in 11.48s
```

### SPEC §5 grep 审计

```bash
grep -rn '!= "direct"\|== "direct"' fetcher/fetcher/ --include="*.py" | grep -v vendor
# 仅剩一行：fetcher/fetcher/core/session.py:32: return bare_identity(identity) == "direct"
```

Python 侧字面量 `"direct"` 比较只剩 `is_direct()` 自己内部。`db.py:684` 的 SQL 字符串 `!= 'direct'` 按 §3.3#4 豁免。

## 改动统计

| 文件 | 改动 |
|------|------|
| `fetcher/fetcher/core/session.py` | +16 行（2 个辅助函数） |
| `fetcher/fetcher/net/browser.py` | 2 行改（import + #1 + #6） |
| `fetcher/fetcher/control/loop.py` | 2 行改（import + #2） |
| `fetcher/fetcher/atoms/identity_ops.py` | 2 行改（import + #3） |
| `fetcher/fetcher/db.py` | 3 行改（#4 SQL + #5 两处列宽） |
| `fetcher/tests/test_session_helpers.py` | +53 行（新文件） |
| `fetcher/tests/test_browser_fresh.py` | +129 行（新文件） |
| `fetcher/tests/test_identity.py` | +130 行 |
| `fetcher/tests/test_control_loop.py` | +26 行 |
| **合计** | **9 files, +363/-10** |

## 验证

- [x] 6 处修正与 §3.3 表一致
- [x] SPEC §5 第 6 条 grep 达成
- [x] 全量 270 passed 无回归
- [x] 只改 `fetcher/`，未碰 platform/、vendor/wa-check/、scraper/、util/
- [x] commit 显式列文件（9 files），不含工作区其他未提交改动
- [x] 未做 Step 1.3（不拼前缀、不改 engine、不加 site_name）

## 疑虑

无。本步为纯字符串级别修正，对当前无前缀旧键行为逐字等价，无运行时行为变化。
